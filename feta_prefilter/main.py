import sys
import argparse
import logging

from feta_prefilter.Sources import source_classes
from feta_prefilter.Filters import filter_classes
from feta_prefilter.Outputs import output_classes

from feta_prefilter.Filters.BaseFilter import FilterAction


def main():
    config = read_config()
    logging.basicConfig(level=logging.INFO)

    sources = []
    for source in config["sources"]:
        source_cls_name = source["type"]
        if source_cls_name not in source_classes:
            logging.error(f"Unknown source class type {source_cls_name}")
            continue

        try:
            source_cls = source_classes[source_cls_name]
            source_obj = source_cls(*source["args"], **source["kwargs"])
        except:
            logging.exception(f"Failed source initialization")
            continue

        sources.append(source_obj)

    filters = []
    for f in config["filters"]:
        filter_cls_name = f["type"]
        if filter_cls_name not in filter_classes:
            logging.error(f"Unknown filter class type {filter_cls_name}")
            continue

        try:
            filter_cls = filter_classes[filter_cls_name]
            filter_obj = filter_cls(*f["args"], **f["kwargs"])
        except:
            logging.exception(f"Failed filter initialization")
            continue

        filters.append(filter_obj)

    outputs = []
    for output in config["outputs"]:
        output_cls_name = output["type"]
        if output_cls_name not in output_classes:
            logging.error(f"Unknown output class type {output_cls_name}")
            continue

        try:
            output_cls = output_classes[output_cls_name]
            output_obj = output_cls(*output["args"], **output["kwargs"])
        except:
            logging.exception(f"Failed output initialization")
            continue

        outputs.append(output_obj)

    while True:
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
            domain_results = {f.__class__.__name__: filter_results[f][i] for f in filter_results.keys()}
            max_domain_result = max(domain_results.values())
            if max_domain_result == FilterAction.DROP:
                continue
            else:
                filtered_domains.append(
                    {
                        "domain": domain,
                        "f_results": domain_results
                    }
                )

        for o in outputs:
            o.output(filtered_domains)


def read_config() -> dict:
    return {
        "sources": [
            {
                "type": "FileSource",
                "args": [],
                "kwargs": {
                    "filename": "source.list",
                },
            },
        ],
        "filters": [
            {
                "type": "FileBlockListFilter",
                "args": [],
                "kwargs": {
                    "filter_result_action": FilterAction.STORE,
                    "filename": "block.list",
                },
            },
            {
                "type": "FileBlockListFilter",
                "args": [],
                "kwargs": {
                    "filter_result_action": FilterAction.DROP,
                    "filename": "block2.list",
                },
            },
        ],
        "outputs": [
            {
                "type": "StdOutput",
                "args": [],
                "kwargs": {},
            },
        ],
    }


if __name__ == "__main__":
    main()
