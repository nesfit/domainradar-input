import os
import sys
import argparse
import logging
from pathlib import Path
from pprint import pprint
import json
from json import JSONDecodeError
import multiprocessing

from kafka import KafkaConsumer, KafkaProducer

from feta_prefilter.utils import make_ssl_context
from feta_prefilter.Sources import source_classes
from feta_prefilter.Filters import filter_classes
from feta_prefilter.Outputs import output_classes

from feta_prefilter.Filters.BaseFilter import FilterAction

logger = logging.getLogger(__name__)

MAX_FILTER_TIMEOUT = 5

def main():
    config = init_config()
    logging.basicConfig(level=os.environ.get("DOMAINRADAR_LOG_LEVEL", "INFO"))

    processes, source_outputs, filter_inputs, filter_outputs, output_inputs = create_app(config)
    for p in processes:
        logger.info(f"Starting process {p} of new app")
        p.start()

    while True:
        if update_config(config):
            logger.info("New config received, recreating app")
            new_processes, source_outputs, filter_inputs, filter_outputs, output_inputs = create_app(config)

            for p in processes:
                logger.debug("Killing old processes")
                p.kill()

            for p in new_processes:
                logger.info(f"Starting process {p} of new app")
                p.start()
            processes = new_processes

        domains = set()
        for conn in source_outputs:
            if conn.poll():
                domains.update(d.lower() for d in conn.recv())
        logger.debug(f"domains from inputs: {domains}")

        if not domains:
            continue

        for conn in filter_inputs:
            conn.send(domains)

        filter_results = {}
        for f_name, conn in filter_outputs:
            if conn.poll(MAX_FILTER_TIMEOUT):
                filter_results[f_name] = conn.recv()
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
                f_name: filter_results[f_name][i] for f_name in filter_results.keys()
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

        for conn in output_inputs:
            conn.send(filtered_domains)


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


def s_process(conn, source_cls_name, *args, **kwargs):
    try:
        source_cls = source_classes[source_cls_name]
        source_obj = source_cls(*args, **kwargs)
    except:
        logger.exception(f"Failed source initialization")

    while True:
        try:
            res = list(source_obj.collect())
            if res:
                conn.send(res)
        except:
            logger.exception("Source process problem")


def f_process(conn, filter_cls_name, *args, **kwargs):
    try:
        filter_cls = filter_classes[filter_cls_name]
        filter_obj = filter_cls(*args, **kwargs)
    except:
        logger.exception("Failed filter initialization")

    while True:
        domains = conn.recv()
        try:
            filter_results = list(filter_obj.filter(domains))
            if filter_results:
                conn.send(filter_results)
        except:
            logger.exception("Filter process problem")


def o_process(conn, output_cls_name, *args, **kwargs):
    try:
        output_cls = output_classes[output_cls_name]
        output_obj = output_cls(*args, **kwargs)
    except:
        logger.exception(f"Failed output initialization")

    while True:
        filtered_domains = conn.recv()
        try:
            output_obj.output(filtered_domains)
        except:
            logger.exception("Output process problem")


def create_app(config: dict):
    processes = []
    source_outputs = []
    filter_inputs = []
    filter_outputs = []
    output_inputs = []

    for source in config["dynamic_config"]["sources"]:
        source_cls_name = source["type"]
        if source_cls_name not in source_classes:
            logger.error(f"Unknown source class type {source_cls_name}")
            continue

        conn1, conn2 = multiprocessing.Pipe()
        logger.debug(f"Creating process for source {source}")
        process = multiprocessing.Process(
            target=s_process,
            args=[conn2, source_cls_name, *source["args"]],
            kwargs=source["kwargs"],
        )
        processes.append(process)
        source_outputs.append(conn1)

    filters = []
    for f in config["dynamic_config"]["filters"]:
        filter_cls_name = f["type"]
        if filter_cls_name not in filter_classes:
            logger.error(f"Unknown filter class type {filter_cls_name}")
            continue

        conn1, conn2 = multiprocessing.Pipe()
        logger.debug(f"Creating process for filter {f}")
        process = multiprocessing.Process(
            target=f_process,
            args=[conn2, filter_cls_name, *f["args"]],
            kwargs=f["kwargs"],
        )
        processes.append(process)
        filter_inputs.append(conn1)
        filter_outputs.append((f["kwargs"]["filter_name"], conn1))

    outputs = []
    for output in config["dynamic_config"]["outputs"]:
        output_cls_name = output["type"]
        if output_cls_name not in output_classes:
            logger.error(f"Unknown output class type {output_cls_name}")
            continue

        conn1, conn2 = multiprocessing.Pipe()
        logger.debug(f"Creating process for output {output}")
        process = multiprocessing.Process(
            target=o_process,
            args=[conn2, output_cls_name, *output["args"]],
            kwargs=output["kwargs"],
        )
        processes.append(process)
        output_inputs.append(conn1)

    return processes, source_outputs, filter_inputs, filter_outputs, output_inputs


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
