# Domain provenance in the loader

Every domain carries where it came from: the loader writes one row per *domain x source x
record of that source* into the `domain_origin` table (see `thor-infra-ansible`), and a
separate Kafka Connect pipeline carries it to MongoDB. The collector pipeline
(`domains_input` -> `to_process_zone` -> collectors -> `raw_*`) is not touched.

## Declaring the source identity

A source block can carry an optional `origin` object next to `type`/`args`/`kwargs`:

```json
{
  "type": "MISPSource",
  "args": [],
  "kwargs": { "misp_url": "https://misp.example/", "misp_key": "...", "misp_feed_eventids": [] },
  "origin": {
    "sourceType": "misp",
    "sourceId": "misp:liberouter-thor",
    "sourceUrl": "https://misp.example/",
    "feedEventIds": { "1": "phishtank", "3": "openphish", "65": "threatfox" },
    "feedThreatTypes": { "phishtank": "phishing", "openphish": "phishing" }
  }
}
```

- `sourceType` is one of `misp`, `file`, `elk`, `manual` (`unknown` when the block has none).
- `sourceId` is the declared, stable identity of the source; without it the record is
  dropped, because a row that cannot name its source is indistinguishable from any other.
  For MISP the per-record identity is `<sourceId>/<feed>`.
- `feedEventIds` maps a MISP event id to a feed name. MISP does not expose "which feed" on
  an event, so the mapping has to be declared; ThreatFox daily events are recognized by
  owner (`abuse.ch`) and title instead, without any configuration.
- `feedThreatTypes` declares the threat type for feeds that do not carry one themselves.
  Tags and the structured comment of an attribute always win over this.
- `feed` pins a single-feed source (then no event map is needed).

Blocks without an `origin` keep working unchanged - their domains are collected, they just
have no provenance. The `origin` key is also accepted when a configuration arrives through
`configuration_change_requests`.

## What is recorded

| field | meaning |
|---|---|
| `sourceType` | `misp` / `file` / `elk` / `manual` / `unknown` |
| `sourceId` | `<instance>/<feed>`, e.g. `misp:liberouter-thor/openphish` |
| `sourceUrl` | URL of the source instance/feed |
| `originUrl` | the indicator URL itself (only for `url` attributes) |
| `externalId` | identity of the record in the source (MISP attribute uuid) |
| `threatType` | closed vocabulary: `c2`, `phishing`, `malware`, `malware:<family>`, `ip-blocklist`, `spam` |
| `labelDerivedFrom` | `misp_tag`, `misp_comment` or `feed` |
| `context` | `eventId`, `eventUuid`, `eventInfo`, `eventOrg`, `eventDate`, `category`, `attributeType`, `toIds`, `sourceFirstSeen`, `sourceLastSeen`, `comment`, `tags` |

## Domains that never reach the pipeline

Domains dropped by a filter are not stored at all. STORE domains (Cloudflare top lists) are
written to `domains_input` and to `domain_origin` with `sent_to_pipeline = false`, so they
stay in Postgres but are never sent to Kafka or Mongo.

## Canonicalization

Domain names are canonicalized before they reach the filters and the outputs (lowercase,
no scheme/userinfo/port/path, no trailing dot, IDNA -> punycode) - the same rules the
dataset tool joins on (`thordata.domain_keys.canonical_domain`), so the registry keys match
the collector documents.
