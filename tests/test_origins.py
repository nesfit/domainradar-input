from feta_prefilter.origins import (
    event_feed,
    normalize_origin,
    normalize_threat_type,
    origin_key,
    threat_type_from_attribute,
)


def test_threat_type_is_taken_from_a_c2_attribute_tag():
    assert threat_type_from_attribute([{"name": "c2"}], None) == ("c2", "misp_tag")


def test_threat_type_from_a_c2_comment():
    assert threat_type_from_attribute([], "Remcos botnet C2 server (confidence level: 100%)") == (
        "c2",
        "misp_comment",
    )


def test_malware_family_from_a_payload_delivery_comment():
    assert threat_type_from_attribute(
        [{"name": "type:OSINT"}], "ClearFake payload delivery domain (confidence level: 100%)"
    ) == ("malware:clearfake", "misp_comment")


def test_attribute_without_tags_or_comment_has_no_threat_type():
    assert threat_type_from_attribute([], "") == (None, None)


def test_threat_type_vocabulary_is_closed():
    assert normalize_threat_type("Phishing") == "phishing"
    assert normalize_threat_type("malware:Remcos") == "malware:remcos"
    assert normalize_threat_type("malware:not a family!") == "malware"
    assert normalize_threat_type("censys") is None


def test_origin_without_a_source_id_is_dropped():
    assert normalize_origin(None) is None
    assert normalize_origin({"sourceType": "misp"}) is None
    assert normalize_origin({"sourceId": "  "}) is None


def test_origin_is_normalized_and_keyed_by_source_and_record():
    origin = normalize_origin(
        {
            "sourceType": "MISP",
            "sourceId": "misp:thinfra/phishtank",
            "sourceUrl": " https://misp.example ",
            "threatType": "phishing",
            "labelDerivedFrom": "feed",
            "externalId": "abc",
            "context": {"eventId": 1},
            "unknownField": "dropped",
        }
    )
    assert origin is not None
    assert origin["sourceType"] == "misp"
    assert origin["sourceUrl"] == "https://misp.example"
    assert origin["externalId"] == "abc"
    assert "unknownField" not in origin
    assert origin_key(origin) == ("misp:thinfra/phishtank", "abc")


def test_origin_with_an_unknown_source_type_keeps_its_record():
    origin = normalize_origin({"sourceType": "carrier-pigeon", "sourceId": "x"})
    assert origin is not None
    assert origin["sourceType"] == "unknown"


def test_feed_from_the_declared_event_map():
    assert event_feed({"id": "3"}, {"3": "openphish"}) == "openphish"


def test_threatfox_daily_events_are_recognized_by_owner_and_title():
    event = {"id": "2009", "Orgc": {"name": "abuse.ch"}, "info": "ThreatFox IOCs for 2025-10-13"}
    assert event_feed(event, {}) == "threatfox"


def test_event_without_a_mapping_is_unknown():
    assert event_feed({"id": "42", "Orgc": {"name": "CESNET"}, "info": "x"}, {}) == "unknown"
    assert event_feed(None, {}) == "unknown"
