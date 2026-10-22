"""Domain-key canonicalization.

The loader stores domains in Postgres and the collectors key their results by the same
string, so a domain has to be normalized in one place, before anything is written: a URL
attribute can carry userinfo and a port, MISP values can keep a trailing dot, and IDN
names have to match their punycode form. The rules are the ones the dataset tool already
joins on (``thordata.domain_keys.canonical_domain``); keep them in sync.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")
_PORT_RE = re.compile(r":\d+$")


def canonical_domain(value: object) -> str | None:
    """Normalize an arbitrary domain-ish string to a bare lowercase hostname.

    Returns ``None`` for empty input. Never raises on malformed input.
    """
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s:
        return None

    if _SCHEME_RE.match(s):
        s = urlsplit(s).hostname or ""
    elif "://" in s or s.startswith("//"):
        s = urlsplit("http:" + s if s.startswith("//") else s).hostname or ""

    # Strip userinfo, path, query, fragment, port.
    s = s.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if "@" in s:
        s = s.rsplit("@", 1)[1]
    if s.startswith("[") and "]" in s:  # bracketed IPv6 literal
        s = s[1:s.index("]")]
    elif s.count(":") == 1:
        s = _PORT_RE.sub("", s)
    s = s.rstrip(".").strip()
    if not s:
        return None

    try:  # IDN -> punycode, matching how domains are stored on the wire
        s = s.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        pass
    return s or None


def host_from_url(value: object) -> str | None:
    """Host part of a URL-ish value, without userinfo and port."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if "://" not in s and not s.startswith("//"):
        s = "//" + s
    elif s.startswith("//"):
        pass
    try:
        return urlsplit(s).hostname or None
    except ValueError:
        return None
