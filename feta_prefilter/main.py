import json
import logging
import os
from json import JSONDecodeError
from pathlib import Path

from kafka import KafkaConsumer, KafkaProducer

from feta_prefilter.Filters import filter_classes
from feta_prefilter.Filters.BaseFilter import FilterAction
from feta_prefilter.Outputs import output_classes
from feta_prefilter.Sources import source_classes
from feta_prefilter.utils import make_ssl_context, filter_credentials

logger = logging.getLogger(__name__)


def main():
    config = init_config()
    logging.basicConfig(level=os.environ.get("DOMAINRADAR_LOG_LEVEL", "INFO"))

    sources, filters, outputs = create_app(config)

    while True:
        if update_config(config):
            sources, filters, outputs = create_app(config)

        domains = set()
        for s in sources:
            domains.update(d.lower() for d in s.collect())

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
            max_domain_result = max(domain_results.values())
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


def init_config() -> dict:
    config = {
        "kafka_broker": os.environ.get("DOMAINRADAR_KAFKA_BROKER_URL", ""),
        "kafka_secrets_dir": os.environ.get("DOMAINRADAR_KAFKA_SECRETS_DIR", ""),
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
        ssl_context=make_ssl_context(Path(config["kafka_secrets_dir"])),
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
        ssl_context=make_ssl_context(Path(config["kafka_secrets_dir"])),
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
        ssl_context=make_ssl_context(Path(config["kafka_secrets_dir"])),
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
        for blk in blocks:
            cls_name = blk["type"]
            if cls_name not in registry:
                logger.error(f"Unknown {label} class type {cls_name}")
                continue

            try:
                cls = registry[cls_name]
                obj = cls(*blk["args"], **blk["kwargs"])
            except Exception as e:
                logger.exception(f"Failed {label} initialization", exc_info=e)
                continue

            name = getattr(obj, f"{label}_name", "unnamed")
            logger.info("%s initialized: %s (%s)", label, cls_name, name)

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("%s args: %s", label, filter_credentials(blk["args"]))
                logger.debug("%s kwargs: %s", label, filter_credentials(blk["kwargs"]))

            items.append(obj)
        return items

    sources = _init_block(
        config["dynamic_config"]["sources"],
        source_classes,
        "source"
    )

    filters = _init_block(
        config["dynamic_config"]["filters"],
        filter_classes,
        "filter"
    )

    outputs = _init_block(
        config["dynamic_config"]["outputs"],
        output_classes,
        "output"
    )

    return sources, filters, outputs


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
