import logging
from datetime import datetime, timedelta

from elasticsearch import Elasticsearch
from feta_prefilter.Sources.BaseSource import BaseSource

logger = logging.getLogger(__name__)


class CesnetELKSource(BaseSource):
    def __init__(self, elk_url: str):
        self.es = Elasticsearch(elk_url)
        self._latest_sort = [0]

    def collect(self) -> list[str]:
        last_10_minutes = datetime.utcnow() - timedelta(minutes=10)
        logger.debug("START %s", datetime.utcnow())
        results = self.es.search(
            index="logstash-dns-*",
            query={
                "bool": {
                    "must": [
                        {"match": {"type": "dnsdata"}},
                        {
                            "bool": {
                                "should": [
                                    {"match": {"FME_DNS_RR_TYPE": 1}},   # A
                                    {"match": {"FME_DNS_RR_TYPE": 28}},  # AAAA
                                ]
                            }
                        },
                    ],
                    "filter": [
                        {"range": {"@timestamp": {"gt": last_10_minutes.isoformat()}}},
                    ],
                }
            },
            sort=[
                {"@timestamp": "asc"},
            ],
            search_after=self._latest_sort,
            size=10000, # 10k is max size as per ELK spec
        )
        logger.debug("FINISH %s", datetime.utcnow())
        timestamp = None
        for hit in results.body["hits"]["hits"]:
            self._latest_sort = hit["sort"]
            timestamp = hit["_source"]["@timestamp"]
            yield hit["_source"]["DNS_Q_NAME"]
        logger.debug("Last record from elk from this call %s", timestamp)
