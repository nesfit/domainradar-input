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
from feta_prefilter.domain import canonical_domain
from feta_prefilter.origins import normalize_origin, origin_key
from feta_prefilter.utils import make_ssl_context, filter_credentials

logger = logging.getLogger(__name__)

# Backoff for re-initializing blocks whose constructor failed (a source that could not
# reach its backend). The last value repeats for further attempts.
INIT_RETRY_DELAYS = (5, 15, 45, 120, 300)
IDLE_SLEEP = 1.0

# Bounded reads from the Kafka consumers. Iterating a consumer directly is unbounded: a
# coordinator/rebalance storm kept update_config() inside the loop while kafka-python
# re-logged every retry (528k lines / 100 MB in 90 s, no MISP request during it).
CONFIG_POLL_TIMEOUT_MS = 500
CONFIG_POLL_MAX_RECORDS = 100
KAFKA_LOG_LEVEL = os.environ.get("DOMAINRADAR_KAFKA_LOG_LEVEL", "WARNING")


def main():
    # before init_config(): everything it logs (which config was loaded, consumer setup,
    # the first config-change poll) is dropped if logging is configured afterwards
    logging.basicConfig(level=os.environ.get("DOMAINRADAR_LOG_LEVEL", "INFO"))
    logging.getLogger("kafka").setLevel(KAFKA_LOG_LEVEL)

    config = init_config()

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

        domains = collect_origins(sources)
        filtered_domains = filter_domains(domains, filters)

        for o in outputs:
            o.output(filtered_domains)

        if not sources or pending:
            # nothing to collect or waiting for an init retry, don't spin
            time.sleep(IDLE_SLEEP)


def collect_origins(sources) -> dict[str, dict[tuple[str, str], dict]]:
    """Collect every source into canonical domain -> {origin key: origin}.

    A domain seen by several sources keeps one origin per source, and the same attribute
    seen twice is deduplicated on its registry identity. Domains without a known origin
    are collected too - the registry simply has nothing to say about them.
    """
    domains: dict[str, dict[tuple[str, str], dict]] = {}
    for s in sources:
        try:
            for raw_domain, raw_origin in s.collect_with_origin():
                domain = canonical_domain(raw_domain)
                if not domain:
                    continue
                origins = domains.setdefault(domain, {})
                origin = normalize_origin(raw_origin)
                if origin is not None:
                    origins[origin_key(origin)] = origin
        except Exception as e:
            logger.warning(
                f"Source {type(s).__name__} failed to collect: {type(e).__name__}: {e}"
            )
    return domains


def filter_domains(
    domains: dict[str, dict[tuple[str, str], dict]], filters
) -> list[dict]:
    """Filter the domains and build the per-domain output entries.

    The filters get the domain list in the same order their actions are returned in; the
    entries stay ``{domain, f_results, origins}`` - ``f_results`` is empty for domains
    that go straight to analysis and holds the per-filter actions for STORE domains.
    """
    domain_list = list(domains)
    filter_results = {f: f.filter(domain_list) for f in filters}

    filtered_domains = []
    for i, domain in enumerate(domain_list):
        domain_results = {
            f.filter_name: filter_results[f][i] for f in filter_results.keys()
        }
        max_domain_result = max(domain_results.values(), default=FilterAction.PASS)
        if max_domain_result == FilterAction.DROP:
            continue
        if max_domain_result == FilterAction.STORE:
            # the domain is stored but not analysed, so the filter results are kept
            entry = {"domain": domain, "f_results": domain_results}
        else:
            entry = {"domain": domain, "f_results": {}}
        entry["origins"] = list(domains[domain].values())
        filtered_domains.append(entry)
    return filtered_domains


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
    while True:
        messages = poll_messages(init_consumer)
        if not messages:
            break

        for msg in messages:
            logger.debug(msg)

            try:
                if msg.key.decode() != "loader":
                    continue

                state = json.loads(msg.value)
            except (AttributeError, UnicodeDecodeError, JSONDecodeError):
                continue

            if not state["success"]:
                continue
            logger.info("Config loaded: %s", describe_config(state["currentConfig"]))
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
    for msg in poll_messages(consumer):
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

        logger.info("Change request received: %s", describe_config(change_request))
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


def instantiate(block: dict, registry: dict):
    """Build one configured block and attach its optional ``origin`` identity."""
    obj = registry[block["type"]](*block["args"], **block["kwargs"])
    origin = block.get("origin")
    if origin is not None:
        obj.origin = origin
    return obj


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
                obj = instantiate(blk, registry)
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
            obj = instantiate(self.block, self.registry)
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


def describe_config(config: dict) -> str:
    """Block types only - the whole payload carries MISP keys and API tokens."""

    def describe(blocks: list[dict]) -> list[str]:
        return [block.get("type", "?") for block in blocks]

    return "sources=%s filters=%s outputs=%s" % (
        describe(config.get("sources", [])),
        describe(config.get("filters", [])),
        describe(config.get("outputs", [])),
    )


def poll_messages(
    consumer,
    timeout_ms: int = CONFIG_POLL_TIMEOUT_MS,
    max_records: int = CONFIG_POLL_MAX_RECORDS,
) -> list:
    """Bounded read from a KafkaConsumer, returns the polled records as a flat list."""
    batch = consumer.poll(timeout_ms=timeout_ms, max_records=max_records)
    return [record for records in batch.values() for record in records]


def validate_dynamic_config(change_request):
    try:
        for src in change_request["sources"]:
            validate_config_block(src)
        for f in change_request["filters"]:
            validate_config_block(f)
        for output in change_request["outputs"]:
            validate_config_block(output)
    except:
        logger.exception(
            "Failed validation of config change request %s",
            filter_credentials(change_request),
        )
        return False

    return True


def validate_config_block(block: dict):
    block["type"]
    block["args"]
    block["kwargs"]

    # optional provenance identity; a source without it still collects domains, the
    # registry just gets no row for them
    origin = block.get("origin")
    if origin is None:
        return
    if not isinstance(origin, dict):
        raise ValueError("origin must be an object")
    if origin.get("sourceId") is not None and not isinstance(origin["sourceId"], str):
        raise ValueError("origin.sourceId must be a string")
    for key in ("feedEventIds", "feedThreatTypes"):
        if origin.get(key) is not None and not isinstance(origin[key], dict):
            raise ValueError(f"origin.{key} must be an object")


if __name__ == "__main__":
    main()
