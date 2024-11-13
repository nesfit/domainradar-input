import logging
from datetime import datetime, timedelta
from urllib.parse import urlparse

from pymisp import PyMISP

from feta_prefilter.Sources.BaseSource import BaseSource

logger = logging.getLogger(__name__)


class MISPSource(BaseSource):
    def __init__(
        self,
        misp_url: str,
        misp_key: str,
        misp_feed_eventids: list[int],
    ):
        self.misp = PyMISP(misp_url, misp_key, ssl=False)
        self.misp_feed_eventids = misp_feed_eventids
        self.last_timestamp = datetime.now() - timedelta(days=1)

    def collect(self) -> list[str]:
        attributes = self.misp.search(
            controller="attributes", to_ids=True, eventid=self.misp_feed_eventids, timestamp=self.last_timestamp
        )
        self.last_timestamp = datetime.now()

        for attr in attributes["Attribute"]:
            if attr["type"] == "domain":
                yield attr['value'].strip()
            elif attr["type"] == "url":
                domain = urlparse(attr["value"]).netloc
                yield domain
            else:
                continue
