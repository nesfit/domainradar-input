import logging
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse

from feta_prefilter.Sources.BaseSource import BaseSource
from feta_prefilter.utils import misp_client

logger = logging.getLogger(__name__)

# The main loop runs about twice per second. Querying MISP on every iteration is
# pointless (the feeds publish in bursts) and a restSearch is the heaviest thing this
# loader does to that instance.
DEFAULT_POLL_INTERVAL_S = 5.0

# A restSearch against a degraded instance ends in an nginx 504 after ~60 s; without a
# timeout one stalled query blocks the whole collect loop. A failing instance is also
# not retried on the next iteration - it gets a break before the next attempt.
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_ERROR_BACKOFF_S = 60.0


class MISPSource(BaseSource):
    def __init__(
        self,
        misp_url: str,
        misp_key: str,
        misp_feed_eventids: list[int],
        misp_ssl: bool | str = True,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        misp_timeout_s: float = DEFAULT_TIMEOUT_S,
        error_backoff_s: float = DEFAULT_ERROR_BACKOFF_S,
    ):
        self.misp = misp_client(misp_url, misp_key, misp_ssl, timeout=misp_timeout_s)
        self.misp_feed_eventids = misp_feed_eventids
        self.poll_interval_s = poll_interval_s
        self.error_backoff_s = error_backoff_s
        self.last_timestamp = datetime.now() - timedelta(days=1)
        self._next_poll = 0.0

    def collect(self) -> list[str]:
        if time.monotonic() < self._next_poll:
            return
        self._next_poll = time.monotonic() + self.poll_interval_s

        # Close the window before the request instead of after it: attributes published
        # while the search runs would otherwise get a timestamp older than
        # last_timestamp and never be fetched. The overlap is harmless, main() collects
        # the domains into a set anyway.
        window_start, self.last_timestamp = self.last_timestamp, datetime.now()
        try:
            attributes = self.misp.search(
                controller="attributes",
                to_ids=True,
                eventid=self.misp_feed_eventids,
                timestamp=window_start,
            )
        except Exception:
            # keep the window open so the next attempt covers what this one missed
            self.last_timestamp = window_start
            self._next_poll = time.monotonic() + self.error_backoff_s
            raise

        for attr in attributes["Attribute"]:
            if attr["type"] == "domain":
                yield attr['value'].strip()
            elif attr["type"] == "url":
                domain = urlparse(attr["value"]).netloc
                yield domain
            else:
                continue
