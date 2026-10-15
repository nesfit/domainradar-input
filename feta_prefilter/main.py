import json
import logging
import os
import time
from json import JSONDecodeError
from pathlib import Path

from kafka import KafkaConsumer, KafkaProducer

from feta_prefilter.Filters import filter_classes
from feta_prefilter.Filters.BaseFilter import FilterAction
from feta_prefilter.Outputs import output_classes
from feta_prefilter.Sources import source_classes
from feta_prefilter.utils import make_ssl_context, filter_credentials

logger = logging.getLogger(__name__)

# Backoff for re-initializing blocks whose constructor failed (a source that could not
# reach its backend). The last value repeats for further attempts.
INIT_RETRY_DELAYS = (5, 15, 45, 120, 300)
IDLE_SLEEP = 1.0


def main():
    config = init_config()
    logging.basicConfig(level=os.environ.get("DOMAINRADAR_LOG_LEVEL", "INFO"))

    sources, filters, outputs, pending = create_app(config)

    idle_warned = False
    while True:
        if update_config(config):
            sources, filters, outputs, pending = create_app(config)
            idle_warned = False

        pending = retry_pending(pending)

        if sources:
            idle_warned = False
        elif not idle_warned:
            logger.error("No sources initialized, idle until one initializes")
            idle_warned = True

        domains = set()
        for s in sources:
            try:
                domains.update(d.lower() for d in s.collect())
            except Exception as e:
                logger.warning(
                    f"Source {type(s).__name__} failed to collect: {type(e).__name__}: {e}"
                )

        filter_results = {}
        for f in filters:
            filter_results[f] = f.filter(domains)
        ###
        # filter_results[f1] = [PASS, DROP, PASS...]
        # filter_results[f2] = [DROP, PASS, PASS...]

        ###
        # transform into:
        # [
        #   { domain, f_results= {f1: PASS, f2: DROP} }
        #   { domain, f_results= {f1: DROP, f2: PASS} }
        #   { domain, f_results= {f1: PASS, f2: PASS} }
        # ]
        filtered_domains = []
        for i, domain in enumerate(domains):
            domain_results = {
                f.filter_name: filter_results[f][i]
                for f in filter_results.keys()
            }
            max_domain_result = max(domain_results.values(), default=FilterAction.PASS)
            if max_domain_result == FilterAction.DROP:
                continue
            elif max_domain_result == FilterAction.STORE:
                filtered_domains.append({"domain": domain, "f_results": domain_results})
            else:
                # if all are PASS-analyze, then we don't need to store the json
                filtered_domains.append(
                    {
                        "domain": domain,
                        "f_results": {},
                    }
                )

        for o in outputs:
            o.output(filtered_domains)

        if not sources or pending:
            # nothing to collect or waiting for an init retry, don't spin
            time.sleep(IDLE_SLEEP)


def init_config() -> dict:
    config = {
        "kafka_broker": os.environ.get("DOMAINRADAR_KAFKA_BROKER_URL", ""),
        "kafka_secrets": {
            "ca_cert_file": os.environ.get("DOMAINRADAR_KAFKA_SECRETS_CA_CERT_FILE", ""),
            "cert_file": os.environ.get("DOMAINRADAR_KAFKA_SECRETS_CERT_FILE", ""),
            "private_key_file": os.environ.get(
                "DOMAINRADAR_KAFKA_SECRETS_PRIVATE_KEY_FILE", ""
            ),
            "private_key_password_file": os.environ.get(
                "DOMAINRADAR_KAFKA_SECRETS_PRIVATE_KEY_PASSWORD_FILE", ""
            ),
        },
        "dynamic_config": {
            "sources": [],
            "filters": [],
            "outputs": [],
        },
    }

    init_consumer = KafkaConsumer(
        "configuration_states",
        client_id="loader-consumer-init",
        bootstrap_servers=config["kafka_broker"],
        security_protocol="SSL",
        ssl_context=make_ssl_context(config["kafka_secrets"]),
        auto_offset_reset="earliest",
        consumer_timeout_ms=500,
    )
    inited = False
    for msg in init_consumer:
        logger.debug(msg)

        try:
            if msg.key.decode() != "loader":
                continue

            state = json.loads(msg.value)
        except (AttributeError, UnicodeDecodeError, JSONDecodeError):
            continue

        if not state["success"]:
            continue
        logger.info(state)
        config["dynamic_config"] = state["currentConfig"]
        inited = True

    config["kafka_producer"] = KafkaProducer(
        client_id="loader-producer",
        bootstrap_servers=config["kafka_broker"],
        security_protocol="SSL",
        ssl_context=make_ssl_context(config["kafka_secrets"]),
    )

    if not inited:
        # if we didn't get any config messages from kafka (or they were invalid) we send the empty default
        notify_config_change(True, config)

    config["kafka_consumer"] = KafkaConsumer(
        "configuration_change_requests",
        client_id="loader-consumer",
        group_id="loader-consumer",
        bootstrap_servers=config["kafka_broker"],
        security_protocol="SSL",
        ssl_context=make_ssl_context(config["kafka_secrets"]),
        consumer_timeout_ms=500,
    )

    update_config(config)
    return config


def update_config(config: dict) -> bool:
    changed = False
    consumer = config["kafka_consumer"]
    for msg in consumer:
        logger.debug(msg)
        if msg.key is None:
            continue

        try:
            if msg.key.decode() != "loader":
                continue
        except UnicodeDecodeError:
            logger.debug("Cannot decode message key")
            continue

        try:
            change_request = json.loads(msg.value)
        except JSONDecodeError as e:
            logger.debug(f"Cannot decode message JSON value")
            notify_config_change(False, config, str(e))
            continue

        logger.info(f"Change request received: {change_request}")
        if validate_dynamic_config(change_request):
            config["dynamic_config"] = change_request
            success = True
            changed = True
        else:
            success = False

        notify_config_change(success, config)

    return changed


def notify_config_change(success: bool, config: dict, message: str = None):
    producer = config["kafka_producer"]
    msg = {
        "success": success,
        "errors": None,
        "message": message,
        "currentConfig": config["dynamic_config"],
    }

    producer.send(
        "configuration_states", key="loader".encode(), value=json.dumps(msg).encode()
    )
    return


def create_app(config: dict):
    def _init_block(blocks, registry, label: str):
        items = []
        pending = []
        for blk in blocks:
            cls_name = blk["type"]
            if cls_name not in registry:
                logger.error(f"Unknown {label} class type {cls_name}")
                continue

            try:
                cls = registry[cls_name]
                obj = cls(*blk["args"], **blk["kwargs"])
            except Exception as e:
                logger.warning(
                    f"Failed {label} initialization, retrying later: {type(e).__name__}: {e}"
                )
                pending.append(PendingBlock(blk, registry, label, items))
                continue

            name = getattr(obj, f"{label}_name", "unnamed")
            logger.info("%s initialized: %s (%s)", label, cls_name, name)

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("%s args: %s", label, filter_credentials(blk["args"]))
                logger.debug("%s kwargs: %s", label, filter_credentials(blk["kwargs"]))

            items.append(obj)
        return items, pending

    sources, pending_sources = _init_block(
        config["dynamic_config"]["sources"], source_classes, "source"
    )

    filters, pending_filters = _init_block(
        config["dynamic_config"]["filters"], filter_classes, "filter"
    )

    outputs, pending_outputs = _init_block(
        config["dynamic_config"]["outputs"], output_classes, "output"
    )

    return (
        sources,
        filters,
        outputs,
        pending_sources + pending_filters + pending_outputs,
    )


class PendingBlock:
    """Block whose constructor failed, re-initialized with backoff until it succeeds."""

    def __init__(self, block: dict, registry: dict, label: str, sink: list):
        self.block = block
        self.registry = registry
        self.label = label
        self.sink = sink
        self.attempts = 1
        self.next_attempt = time.monotonic() + self.next_delay()

    def next_delay(self) -> float:
        index = min(self.attempts - 1, len(INIT_RETRY_DELAYS) - 1)
        return INIT_RETRY_DELAYS[index]

    def due(self) -> bool:
        return time.monotonic() >= self.next_attempt

    def try_init(self) -> bool:
        """True once the block is resolved (re-initialized or permanently unknown)."""
        cls = self.registry.get(self.block["type"])
        if cls is None:
            logger.error(f"Unknown {self.label} class type {self.block['type']}")
            return True

        try:
            obj = cls(*self.block["args"], **self.block["kwargs"])
        except Exception as e:
            self.attempts += 1
            delay = self.next_delay()
            self.next_attempt = time.monotonic() + delay
            logger.warning(
                f"Failed {self.label} initialization, retrying in {int(delay)}s "
                f"(attempt {self.attempts}): {type(e).__name__}: {e}"
            )
            return False

        logger.info(f"{self.label} initialized after retry: {self.block['type']}")
        self.sink.append(obj)
        return True


def retry_pending(pending: list[PendingBlock]) -> list[PendingBlock]:
    """Re-initializes failed blocks that are due, returns the still pending ones."""
    still_pending = []
    for block in pending:
        if block.due() and block.try_init():
            continue
        still_pending.append(block)
    return still_pending


def validate_dynamic_config(change_request):
    try:
        for src in change_request["sources"]:
            validate_config_block(src)
        for f in change_request["filters"]:
            validate_config_block(f)
        for output in change_request["outputs"]:
            validate_config_block(output)
    except:
        logger.exception(f"Failed validation of config change request {change_request}")
        return False

    return True


def validate_config_block(block: dict):
    block["type"]
    block["args"]
    block["kwargs"]


if __name__ == "__main__":
    main()
