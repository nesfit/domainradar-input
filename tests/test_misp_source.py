import sys

import pytest

from feta_prefilter.Sources.MISPSource import MISPSource

# the package re-exports the class under the module's name, so reach the module itself
misp_module = sys.modules["feta_prefilter.Sources.MISPSource"]


class FakeMISP:
    """Stands in for PyMISP: returns the attribute records for one window."""

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        page = kwargs.get("page", 1)
        if page > len(self.pages):
            return {"response": []}
        return {"response": self.pages[page - 1]}


def build_source(monkeypatch, pages, origin=None):
    monkeypatch.setattr(misp_module, "misp_client", lambda *a, **kw: FakeMISP(pages))
    monkeypatch.setattr(misp_module, "PAGE_SIZE", 2)
    source = MISPSource(
        misp_url="https://misp.example",
        misp_key="key",
        misp_feed_eventids=[],
    )
    source.origin = origin
    return source


ATTRIBUTE = {
    "uuid": "attr-uuid",
    "type": "url",
    "value": "http://user@evil.example:8080/login",
    "category": "Payload delivery",
    "to_ids": True,
    "first_seen": "2025-10-13 08:00:00",
    "Tag": [{"name": "ClearFake"}],
    "comment": "ClearFake payload delivery domain (confidence level: 100%)",
}
EVENT = {"id": "2009", "uuid": "event-uuid", "info": "ThreatFox IOCs for 2025-10-13", "Orgc": {"name": "abuse.ch"}}


def test_collect_with_origin_maps_attribute_and_event(monkeypatch):
    source = build_source(
        monkeypatch,
        [[{"Attribute": ATTRIBUTE, "Event": EVENT}]],
        origin={"sourceType": "misp", "sourceId": "misp:thinfra"},
    )

    pairs = list(source.collect_with_origin())

    assert pairs == [
        (
            "evil.example",
            {
                "sourceType": "misp",
                "sourceId": "misp:thinfra/threatfox",
                "sourceUrl": "https://misp.example",
                "originUrl": "http://user@evil.example:8080/login",
                "externalId": "attr-uuid",
                "threatType": "malware:clearfake",
                "labelDerivedFrom": "misp_comment",
                "context": {
                    "eventId": "2009",
                    "eventUuid": "event-uuid",
                    "eventInfo": "ThreatFox IOCs for 2025-10-13",
                    "eventOrg": "abuse.ch",
                    "category": "Payload delivery",
                    "attributeType": "url",
                    "toIds": True,
                    "sourceFirstSeen": "2025-10-13 08:00:00",
                    "comment": "ClearFake payload delivery domain (confidence level: 100%)",
                    "tags": ["ClearFake"],
                },
            },
        )
    ]


def test_declared_feed_map_wins_over_the_derived_rule(monkeypatch):
    source = build_source(
        monkeypatch,
        [[{"Attribute": {**ATTRIBUTE, "Tag": [], "comment": ""}, "Event": {"id": "3", "Orgc": {"name": "CESNET"}}}]],
        origin={
            "sourceId": "misp:thinfra",
            "feedEventIds": {"3": "openphish"},
            "feedThreatTypes": {"openphish": "phishing"},
        },
    )

    (_domain, origin), = list(source.collect_with_origin())

    assert origin is not None
    assert origin["sourceId"] == "misp:thinfra/openphish"
    assert origin["threatType"] == "phishing"
    assert origin["labelDerivedFrom"] == "feed"


def test_misp_source_identity_defaults_to_the_instance_host(monkeypatch):
    source = build_source(monkeypatch, [[{"Attribute": {**ATTRIBUTE, "type": "domain", "value": "Bad.Example."}, "Event": {}}]])

    (domain, origin), = list(source.collect_with_origin())

    assert domain == "Bad.Example."
    assert origin is not None
    assert origin["sourceId"] == "misp:misp.example/unknown"
    assert origin["originUrl"] is None


def test_pages_are_followed_until_a_short_page(monkeypatch):
    pages = [
        [{"Attribute": {**ATTRIBUTE, "uuid": f"a{i}"}, "Event": EVENT} for i in range(2)],
        [{"Attribute": {**ATTRIBUTE, "uuid": "b0"}, "Event": EVENT}],
    ]
    source = build_source(monkeypatch, pages)

    assert len(list(source.collect_with_origin())) == 3
    assert len(source.misp.calls) == 2
    assert source.misp.calls[0]["includeContext"] == 1


def test_a_window_is_not_queried_twice(monkeypatch):
    source = build_source(monkeypatch, [[{"Attribute": ATTRIBUTE, "Event": EVENT}]])

    assert list(source.collect_with_origin())
    assert list(source.collect_with_origin()) == []
    assert len(source.misp.calls) == 1


def test_a_failed_query_keeps_the_window_open(monkeypatch):
    class FailingMISP:
        def search(self, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(misp_module, "misp_client", lambda *a, **kw: FailingMISP())
    source = MISPSource(misp_url="https://misp.example", misp_key="key", misp_feed_eventids=[])
    window_start = source.last_timestamp

    with pytest.raises(RuntimeError):
        list(source.collect_with_origin())

    assert source.last_timestamp == window_start
    assert source._next_poll > 0


def test_both_response_shapes_are_understood(monkeypatch):
    source = build_source(monkeypatch, [[{"Attribute": [ATTRIBUTE]}]])
    (domain, origin), = list(source.collect_with_origin())
    assert domain == "evil.example"
    assert origin is not None
    assert origin["externalId"] == "attr-uuid"
