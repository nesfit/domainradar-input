"""Domain provenance records -- where a domain was seen and by which feed.

A source hands the collector loop a ``(domain, origin)`` pair. ``origin`` is a plain dict
using the vocabulary that already exists elsewhere in the stack: ``sourceId`` corresponds
to the canonical ``meta.sourceId``, ``originUrl`` to ``meta.url``, and
``sourceType``/``sourceId`` to the engine's reserved ``origin`` base fact.
"""

from __future__ import annotations

import re

# Where the record came from. ``unknown`` covers sources that were not given an origin
# block yet; it is a real value, not an empty one, so a query can find them.
SOURCE_TYPES = ("misp", "file", "elk", "manual", "unknown")

# Closed vocabulary for the threat-type sublabel. A feed that only says "some malware"
# gets the bare ``malware``; the family is kept only when the source names one.
_FIXED_THREAT_TYPES = ("c2", "phishing", "malware", "ip-blocklist", "spam")
_FAMILY_RE = re.compile(r"^[a-z][a-z0-9._-]{1,31}$")

CONFIDENCE_SUFFIX_RE = re.compile(r"\s*\(confidence level:[^)]*\)\s*$", re.IGNORECASE)


def normalize_threat_type(value: object) -> str | None:
    """Map a raw threat type to the closed vocabulary, or ``None`` if it is not one."""
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s:
        return None
    if s in _FIXED_THREAT_TYPES:
        return s
    if s.startswith("malware:"):
        family = s.split(":", 1)[1].strip()
        if _FAMILY_RE.match(family):
            return f"malware:{family}"
        return "malware"
    return None


def normalize_origin(raw: object) -> dict | None:
    """Validate and normalize one origin record.

    Returns ``None`` when the record cannot identify a source, because a row without an
    identity would be indistinguishable from every other unknown source.
    """
    if not isinstance(raw, dict):
        return None

    source_id = str(raw.get("sourceId") or "").strip()
    if not source_id:
        return None

    source_type = str(raw.get("sourceType") or "").strip().lower()
    if source_type not in SOURCE_TYPES:
        source_type = "unknown"

    threat_type = normalize_threat_type(raw.get("threatType"))
    derived = raw.get("labelDerivedFrom")
    derived = str(derived).strip() if derived else None

    context = raw.get("context")
    if not isinstance(context, dict):
        context = None

    return {
        "sourceType": source_type,
        "sourceId": source_id,
        "sourceUrl": _clean(raw.get("sourceUrl")),
        "originUrl": _clean(raw.get("originUrl")),
        "externalId": _clean(raw.get("externalId")) or "",
        "threatType": threat_type,
        "labelDerivedFrom": derived,
        "context": context,
    }


def origin_key(origin: dict) -> tuple[str, str]:
    """Identity of an origin record -- the same key the registry is unique on."""
    return origin["sourceId"], origin["externalId"]


def threat_type_from_attribute(tags: object, comment: object) -> tuple[str | None, str | None]:
    """Threat type and its provenance from a MISP attribute's tags/comment.

    Tags win over the comment (measurably the only two places the type exists); a family
    is taken only from the comment's leading token, e.g.
    ``"Remcos botnet C2 server (confidence level: 100%)"`` -> ``c2`` and
    ``"ClearFake payload delivery domain (...)"`` -> ``malware:clearfake``.
    """
    names = set()
    tag_items = tags if isinstance(tags, (list, tuple, set)) else []
    for tag in tag_items:
        name = tag.get("name") if isinstance(tag, dict) else tag
        if name:
            names.add(str(name).strip().lower())
    if "c2" in names:
        return "c2", "misp_tag"

    text = CONFIDENCE_SUFFIX_RE.sub("", str(comment or "").strip())
    if not text:
        return None, None

    role = text.lower()
    if "c2" in role or "command and control" in role:
        return "c2", "misp_comment"
    if "payload delivery" in role or "botnet" in role or "malware" in role:
        family = text.split()[0] if text.split() else ""
        return normalize_threat_type(f"malware:{family}") or "malware", "misp_comment"
    return None, None


def event_feed(event: object, declared_event_ids: dict[str, str]) -> str:
    """Feed name for a MISP event, from the declared map or a derived rule.

    MISP does not expose "which feed" on an event; the mapping lives in ``feeds/index``
    and has to be declared. ThreatFox publishes daily events instead of one fixed event,
    so it is recognized by its owner and event title.
    """
    event = event if isinstance(event, dict) else {}
    event_id = str(event.get("id") or "")
    if event_id and event_id in declared_event_ids:
        return declared_event_ids[event_id]

    org = event.get("Orgc") or event.get("Org") or {}
    org_name = str(org.get("name") if isinstance(org, dict) else org).strip().lower()
    info = str(event.get("info") or "").strip().lower()
    if org_name == "abuse.ch" and info.startswith("threatfox"):
        return "threatfox"
    return "unknown"


def _clean(value: object) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None
