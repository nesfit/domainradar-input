import logging
from datetime import datetime, timedelta

from elasticsearch import Elasticsearch
from feta_prefilter.Sources.BaseSource import BaseSource

logger = logging.getLogger(__name__)


class ELKSource(BaseSource):
    def __init__(self, elk_url: str):
        self.es = Elasticsearch(elk_url)
        self._latest_sort = [0]

    def collect(self) -> list[str]:
        last_1_day = datetime.utcnow() - timedelta(days=1)
        logger.debug("START", datetime.utcnow())
        results = self.es.search(
            index="logstash-*",
            query={
                "bool": {
                    "must": [
                        {"match": {"event_type": "dns"}},
                        {"match": {"dns.type": "query"}},
                        {
                            "bool": {
                                "should": [
                                    {"match": {"dns.rrtype": "A"}},
                                    {"match": {"dns.rrtype": "AAAA"}},
                                ]
                            }
                        },
                    ],
                    "filter": [
                        {"range": {"timestamp": {"gt": last_1_day.isoformat()}}},
                    ],
                }
            },
            sort=[
                {"timestamp": "asc"},
            ],
            search_after=self._latest_sort,
            size=10000,
        )
        logger.debug("FINISH", datetime.utcnow())
        timestamp = None
        for hit in results.body["hits"]["hits"]:
            self._latest_sort = hit["sort"]
            timestamp = hit["_source"]["@timestamp"]
            yield hit["_source"]["dns"]["rrname"]
        logger.debug("Last record from elk from this call", timestamp)
