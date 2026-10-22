import json

from feta_prefilter.Filters.BaseFilter import BaseFilter, FilterAction
from feta_prefilter.Outputs.PostgresOutput import PostgresOutput
from feta_prefilter.Sources.BaseSource import BaseSource
from feta_prefilter.main import collect_origins, filter_domains


class FakeSource(BaseSource):
    def __init__(self, domains, origin=None):
        self.domains = domains
        self.origin = origin

    def collect(self):
        return self.domains


class StoreFilter(BaseFilter):
    """Stores (and does not analyse) one exact domain, passes everything else."""

    def __init__(self, stored):
        super().__init__("store_one", FilterAction.STORE)
        self.stored = stored

    def filter(self, domains):
        return [
            FilterAction.STORE if d == self.stored else FilterAction.PASS for d in domains
        ]


def test_domains_from_several_sources_keep_one_origin_each():
    a = FakeSource(
        ["example.com"], origin={"sourceType": "file", "sourceId": "file:urlhaus"}
    )
    b = FakeSource(
        ["example.com"], origin={"sourceType": "misp", "sourceId": "misp:thinfra/openphish"}
    )

    domains = collect_origins([a, b])

    assert list(domains) == ["example.com"]
    assert sorted(origin["sourceId"] for origin in domains["example.com"].values()) == [
        "file:urlhaus",
        "misp:thinfra/openphish",
    ]


def test_domains_are_canonicalized_before_they_are_keyed_and_filtered():
    source = FakeSource(
        ["Example.COM.", "http://user@evil.example:8080/x"], {"sourceId": "file:x"}
    )

    domains = collect_origins([source])
    entries = filter_domains(domains, [])

    assert sorted(domains) == ["evil.example", "example.com"]
    assert sorted(entry["domain"] for entry in entries) == ["evil.example", "example.com"]
    assert all(entry["origins"] for entry in entries)


def test_the_same_attribute_seen_twice_is_one_origin():
    origin = {"sourceId": "misp:thinfra/openphish", "externalId": "attr-1"}
    domains = collect_origins([FakeSource(["example.com"], origin), FakeSource(["example.com"], origin)])

    assert len(domains["example.com"]) == 1


def test_a_source_without_an_origin_still_yields_its_domains():
    domains = collect_origins([FakeSource(["example.com"])])

    assert list(domains) == ["example.com"]
    assert domains["example.com"] == {}


def test_store_domains_keep_their_filter_results_and_pass_domains_do_not():
    source = FakeSource(
        ["stored.example", "piped.example"],
        {"sourceId": "misp:thinfra/openphish", "externalId": "a"},
    )
    entries = {entry["domain"]: entry for entry in filter_domains(collect_origins([source]), [StoreFilter("stored.example")])}

    assert entries["stored.example"]["f_results"] == {"store_one": FilterAction.STORE}
    assert entries["piped.example"]["f_results"] == {}
    assert entries["piped.example"]["origins"] == [
        {
            "sourceType": "unknown",
            "sourceId": "misp:thinfra/openphish",
            "sourceUrl": None,
            "originUrl": None,
            "externalId": "a",
            "threatType": None,
            "labelDerivedFrom": None,
            "context": None,
        }
    ]


def test_registry_rows_follow_the_stored_filter_output():
    output = PostgresOutput("postgres", 5432, "loader", "pw", "domainradar")
    entries = [
        {
            "domain": "piped.example",
            "f_results": {},
            "origins": [{"sourceId": "misp:x/feed", "sourceType": "misp", "externalId": "a"}],
        },
        {
            "domain": "stored.example",
            "f_results": {"store_one": FilterAction.STORE},
            "origins": [{"sourceId": "misp:x/feed", "sourceType": "misp", "externalId": "b"}],
        },
        {"domain": "no-origin.example", "f_results": {}, "origins": []},
    ]

    ((command, params),) = output.build_origin_queries(
        entries, {"piped.example": True, "stored.example": False}
    )

    assert "domain_origin" in command
    assert "ON CONFLICT" in command and "updated_at" in command
    assert command.count("(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)") == 2
    assert params[0] == "piped.example" and params[9] is True
    assert params[10] == "stored.example" and params[19] is False


def test_registry_is_written_in_batches():
    output = PostgresOutput("postgres", 5432, "loader", "pw", "domainradar")
    entries = [
        {
            "domain": f"d{i}.example",
            "f_results": {},
            "origins": [{"sourceId": "file:x", "sourceType": "file", "externalId": str(i)}],
        }
        for i in range(1500)
    ]

    chunks = output.build_origin_queries(entries, {})

    assert [len(params) // 10 for _, params in chunks] == [1000, 500]


def test_context_travels_as_jsonb():
    output = PostgresOutput("postgres", 5432, "loader", "pw", "domainradar")
    entries = [
        {
            "domain": "piped.example",
            "f_results": {},
            "origins": [
                {
                    "sourceId": "misp:x/feed",
                    "sourceType": "misp",
                    "externalId": "a",
                    "context": {"eventId": 1},
                }
            ],
        }
    ]

    ((_command, params),) = output.build_origin_queries(entries, {"piped.example": True})

    assert params[8].adapted == {"eventId": 1}
