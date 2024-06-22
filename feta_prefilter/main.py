import os
import sys
import argparse
import logging
from pathlib import Path
from pprint import pprint
import json

from kafka import KafkaConsumer, KafkaProducer

from feta_prefilter.utils import make_ssl_context
from feta_prefilter.Sources import source_classes
from feta_prefilter.Filters import filter_classes
from feta_prefilter.Outputs import output_classes

from feta_prefilter.Filters.BaseFilter import FilterAction

logger = logging.getLogger(__name__)


def main():
    config = init_config()
    logging.basicConfig(level=logging.INFO)

    sources, filters, outputs = create_app(config)

    while True:
        if update_config(config):
            sources, filters, outputs = create_app(config)

        domains = set()
        for s in sources:
            domains.update(s.collect())

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
                f.__class__.__name__: filter_results[f][i]
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

    kafka_consumer = config["kafka_consumer"] = KafkaConsumer(
        "configuration_change_requests",
        client_id="loader-consumer",
        bootstrap_servers=config["kafka_broker"],
        security_protocol="SSL",
        ssl_context=make_ssl_context(Path(config["kafka_secrets_dir"])),
        auto_offset_reset="earliest",
        consumer_timeout_ms=500,
    )

    config["kafka_producer"] = KafkaProducer(
        client_id="loader-producer",
        bootstrap_servers=config["kafka_broker"],
        security_protocol="SSL",
        ssl_context=make_ssl_context(Path(config["kafka_secrets_dir"])),
    )

    if not update_config(config):
        # if we didn't get any config messages from kafka we send the empty default
        notify_config_change(True, config)
    return config


def update_config(config: dict) -> bool:
    changed = False
    consumer = config["kafka_consumer"]
    for msg in consumer:
        logger.debug(msg)
        if msg.key.decode() != "loader":
            continue
        change_request = json.loads(msg.value)
        logger.info(f"Change request received: {change_request}")
        if validate_dynamic_config(change_request):
            config["dynamic_config"] = change_request
            success = True
            changed = True
        else:
            success = False

        notify_config_change(success, config)

    return changed


def notify_config_change(success: bool, config: dict):
    producer = config["kafka_producer"]
    msg = {
        "success": success,
        "errors": None,
        "message": None,
        "currentConfig": config["dynamic_config"],
    }

    producer.send(
        "configuration_states", key="loader".encode(), value=json.dumps(msg).encode()
    )
    return


def create_app(config: dict):
    sources = []
    for source in config["dynamic_config"]["sources"]:
        source_cls_name = source["type"]
        if source_cls_name not in source_classes:
            logger.error(f"Unknown source class type {source_cls_name}")
            continue

        try:
            source_cls = source_classes[source_cls_name]
            source_obj = source_cls(*source["args"], **source["kwargs"])
        except:
            logger.exception(f"Failed source initialization")
            continue

        sources.append(source_obj)

    filters = []
    for f in config["dynamic_config"]["filters"]:
        filter_cls_name = f["type"]
        if filter_cls_name not in filter_classes:
            logger.error(f"Unknown filter class type {filter_cls_name}")
            continue

        try:
            filter_cls = filter_classes[filter_cls_name]
            filter_obj = filter_cls(*f["args"], **f["kwargs"])
        except:
            logger.exception(f"Failed filter initialization")
            continue

        filters.append(filter_obj)

    outputs = []
    for output in config["dynamic_config"]["outputs"]:
        output_cls_name = output["type"]
        if output_cls_name not in output_classes:
            logger.error(f"Unknown output class type {output_cls_name}")
            continue

        try:
            output_cls = output_classes[output_cls_name]
            output_obj = output_cls(*output["args"], **output["kwargs"])
        except:
            logger.exception(f"Failed output initialization")
            continue

        outputs.append(output_obj)
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
