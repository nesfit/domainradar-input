import sys
import argparse
import logging

from feta_prefilter.Sources import source_classes
from feta_prefilter.Filters import filter_classes
from feta_prefilter.Outputs import output_classes


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
        domains = []
        for s in sources:
            domains.extend(s.collect())

        filter_results = []
        for f in filters:
            filter_results.append(f.filter(domains))

        filtered_domains = [
            domain
            for domain, *f_results in zip(domains, *filter_results)
            if all(f_results)
        ]

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
                    "filename": "block.list",
                },
            },
            {
                "type": "FileBlockListFilter",
                "args": [],
                "kwargs": {
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
