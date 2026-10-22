import logging
import time
from collections.abc import Iterator
from datetime import datetime, timedelta

from feta_prefilter.domain import host_from_url
from feta_prefilter.origins import (
    event_feed,
    normalize_threat_type,
    threat_type_from_attribute,
)
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

# One page of attributes with their event context; a window usually fits in the first
# page, so pagination only costs requests when there is actually more data. Without it a
# busy window silently loses everything past the first page - domains and their origins.
PAGE_SIZE = 1000
MAX_PAGES = 50


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
        self.misp_url = misp_url
        self.misp = misp_client(misp_url, misp_key, misp_ssl, timeout=misp_timeout_s)
        self.misp_feed_eventids = misp_feed_eventids
        self.poll_interval_s = poll_interval_s
        self.error_backoff_s = error_backoff_s
        self.last_timestamp = datetime.now() - timedelta(days=1)
        self._next_poll = 0.0
        self._identity_cache: dict | None = None

    def collect(self) -> Iterator[str]:
        for domain, _origin in self.collect_with_origin():
            yield domain

    def collect_with_origin(self) -> Iterator[tuple[str, dict | None]]:
        """Yield ``(domain, origin)`` per attribute, with the event as context."""
        for record in self._fetch_attributes():
            attribute = record["Attribute"]
            domain, origin_url = _domain_from_attribute(attribute)
            if not domain:
                continue
            yield domain, self._build_origin(attribute, record.get("Event"), origin_url)

    # --- MISP access ---------------------------------------------------------------

    def _fetch_attributes(self) -> list[dict]:
        if time.monotonic() < self._next_poll:
            return []
        self._next_poll = time.monotonic() + self.poll_interval_s

        # Close the window before the request instead of after it: attributes published
        # while the search runs would otherwise get a timestamp older than
        # last_timestamp and never be fetched. The overlap is harmless, main() collects
        # the domains into a dict anyway.
        window_start, self.last_timestamp = self.last_timestamp, datetime.now()
        records: list[dict] = []
        try:
            for page in range(1, MAX_PAGES + 1):
                payload = self.misp.search(
                    controller="attributes",
                    to_ids=True,
                    eventid=self.misp_feed_eventids,
                    timestamp=window_start,
                    includeContext=1,
                    limit=PAGE_SIZE,
                    page=page,
                    pythonify=False,
                )
                batch = list(_attribute_records(payload))
                records.extend(batch)
                if len(batch) < PAGE_SIZE:
                    break
            else:
                logger.warning(
                    "MISP returned %d full pages of attributes; the rest of the window is"
                    " left for the next one",
                    MAX_PAGES,
                )
        except Exception:
            # keep the window open so the next attempt covers what this one missed
            self.last_timestamp = window_start
            self._next_poll = time.monotonic() + self.error_backoff_s
            raise

        return records

    # --- origin --------------------------------------------------------------------

    def _identity(self) -> dict:
        """Source identity from the ``origin`` config block, with defaults from the URL."""
        if self._identity_cache is not None:
            return self._identity_cache

        origin = self.origin if isinstance(self.origin, dict) else {}
        host = host_from_url(self.misp_url) or "unknown"
        instance = str(origin.get("sourceId") or f"misp:{host}").strip()
        declared_feeds = origin.get("feedEventIds")
        feed_event_ids = {}
        if isinstance(declared_feeds, dict):
            feed_event_ids = {str(k): str(v) for k, v in declared_feeds.items()}
        feed_threat_types = {}
        declared_types = origin.get("feedThreatTypes")
        if isinstance(declared_types, dict):
            feed_threat_types = {
                str(k): normalize_threat_type(v) for k, v in declared_types.items()
            }

        self._identity_cache = {
            "instance": instance,
            "sourceUrl": str(origin.get("sourceUrl") or self.misp_url),
            "feed": str(origin.get("feed")).strip() if origin.get("feed") else None,
            "feedEventIds": feed_event_ids,
            "feedThreatTypes": feed_threat_types,
            "threatType": normalize_threat_type(origin.get("threatType")),
        }
        return self._identity_cache

    def _build_origin(self, attribute: dict, event: object, origin_url: str | None) -> dict:
        identity = self._identity()
        feed = identity["feed"] or event_feed(event, identity["feedEventIds"])

        threat_type, derived_from = threat_type_from_attribute(
            attribute.get("Tag"), attribute.get("comment")
        )
        if threat_type is None:
            declared = identity["feedThreatTypes"].get(feed) or identity["threatType"]
            if declared:
                threat_type, derived_from = declared, "feed"

        context = _context(attribute, event)

        return {
            "sourceType": "misp",
            "sourceId": f"{identity['instance']}/{feed}",
            "sourceUrl": identity["sourceUrl"],
            "originUrl": origin_url,
            "externalId": str(attribute.get("uuid") or ""),
            "threatType": threat_type,
            "labelDerivedFrom": derived_from,
            "context": context or None,
        }


def _domain_from_attribute(attribute: dict) -> tuple[str | None, str | None]:
    """Domain carried by an attribute and, for URL attributes, the URL itself."""
    attr_type = str(attribute.get("type") or "").strip().lower()
    value = str(attribute.get("value") or "").strip()
    if not value:
        return None, None
    if attr_type == "domain":
        return value, None
    if attr_type == "url":
        return host_from_url(value), value
    return None, None


def _context(attribute: dict, event: object) -> dict:
    event = event if isinstance(event, dict) else {}
    org = event.get("Orgc") or event.get("Org") or {}
    tags = attribute.get("Tag")
    context = {
        "eventId": event.get("id"),
        "eventUuid": event.get("uuid"),
        "eventInfo": event.get("info"),
        "eventOrg": org.get("name") if isinstance(org, dict) else org,
        "eventDate": event.get("date"),
        "category": attribute.get("category"),
        "attributeType": attribute.get("type"),
        "toIds": attribute.get("to_ids"),
        "sourceFirstSeen": attribute.get("first_seen"),
        "sourceLastSeen": attribute.get("last_seen"),
        "comment": attribute.get("comment"),
        "tags": [
            (t.get("name") if isinstance(t, dict) else t)
            for t in (tags if isinstance(tags, list) else [])
        ]
        or None,
    }
    return {key: value for key, value in context.items() if value not in (None, "", [])}


def _attribute_records(payload: object):
    """Normalize every ``attributes/restSearch`` response shape into attribute records.

    Depending on the PyMISP version and on ``includeContext``, the body is
    ``{"Attribute": [...]}``, ``{"response": {"Attribute": [...]}}`` or
    ``{"response": [{"Attribute": {...}, "Event": {...}}]}``.
    """
    if isinstance(payload, dict) and len(payload) == 1 and "response" in payload:
        payload = payload["response"]
    records = payload if isinstance(payload, list) else [payload]

    for record in records:
        if not isinstance(record, dict):
            continue
        attribute = record.get("Attribute", record)
        event = record.get("Event")
        if isinstance(attribute, list):
            for item in attribute:
                yield {"Attribute": item, "Event": event}
        elif isinstance(attribute, dict):
            yield {"Attribute": attribute, "Event": event}
