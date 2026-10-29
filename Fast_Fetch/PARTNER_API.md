# Radd-Stream Partner API — `\/api/partner/v1`

**Status:** specification + reference skeleton. No production route is registered.
**Owner of record:** qoder3. **Reviewed:** qoder4, 2026-10-29.
**Implements:** decision §D of `docs/MONETIZATION_AND_FLEET_PLAN.md`.

A commercial, metered catalog API for business customers, kept in its own namespace so it
can be priced, rate-limited, audited and cut off without touching the app's own traffic.

---

## 1. Read this before you sell or buy anything

Two things constrain this product, and neither is a footnote.

### 1.1 Tier B is the reason this document has a legal section

**Tier A** is metadata: titles, years, poster URLs, synopses, genres, ratings, season and
episode structure, and aggregate link-health counts. Selling it is a normal data-licensing
business, subject to §1.2.

**Tier B** is source-link resolution: `POST /api/partner/v1/resolve` returns watch and
download URLs that point into third-party file hosts and embed players. Our ledger for those
URLs is populated from sites that distribute films and television without the rights holders'
permission. Charging a customer for programmatic access to those endpoints — so the customer
can ship an app that plays them — is the single highest-exposure surface in this project. It is
contributory infringement in every market listed in §9, and unlike hosting, it cannot be
disclaimed by pointing at the third party: the *transaction* is ours.

**Consequences, enforced by code rather than goodwill:**

* `api_tenants.allow_tier_b` is `0` by `DEFAULT` and `NOT NULL`. There is no API, CLI flag or
  config file that sets it to `1`. A human with database access writes it, per tenant.
* A tenant with `allow_tier_b = 0` receives `403 tier_not_enabled`. Not `404`, not a masked
  error — the contract says plainly that the capability exists and this tenant does not have it.
* `/resolve` returns `503 tier_globally_disabled` if the global kill switch
  `PARTNER_TIER_B_ENABLED` is false, **regardless of any per-tenant flag** (§6.3). The per-tenant
  column gates the tenant; the global constant gates the world. Both must be true.
* Every `/resolve` call writes an audit row with the tenant, the work, and the number of URLs
  released, whether it succeeded or was refused. Billing a customer for Tier B without a
  readable audit trail is not something we will do.

Enabling Tier B for a paying customer is **the owner's written decision**, per §D. This document
does not authorize it, the skeleton does not enable it, and an operator flipping the DB column has
not made it happen while the global switch is off. Ship Tier A. If Tier B is ever sold, it is sold
knowingly, with an opinion from a copyright lawyer in the relevant jurisdiction attached to this
file, priced to carry the risk rather than to look attractive next to Tier A.

### 1.2 Tier A is not automatically ours to resell either

The metadata we would sell was largely *gathered*, not *created* by us:

| Field group | Provenance as measured today | Resale posture |
|---|---|---|
| Title, year, season/episode structure, page URL, `source_site` | ours, produced by the scrapers | sellable |
| Poster and backdrop images, synopsis, genres, `imdb_rating`, TMDB id | fetched from The Movie Database enrichment path (`imdb_id`, `tmdb_id` are ingested columns; see `Fast_Fetch/SITES.md`) | **not sellable as-is** without a TMDB license |
| Link-health scores, `is_resumable`, `speed_mbps`, `last_checked_at` | ours, produced by probing third-party endpoints | sellable as *our measurement*, subject to §1.1 when per-endpoint |

TMDB's terms do not grant onward commercial redistribution of their metadata or their image
CDN by default, and an attribution line in our docs does not convert a non-commercial license
into a resellable dataset. Before Tier A is invoiced, one of these is true:

1. a written agreement (TMDB paid tier, or TMDb-adjacent commercial supplier) covering
   redistribution to third parties, and we pass its terms into §8; **or**
2. Tier A ships as a **rights-clean subset**: the fields we produced ourselves (title, year,
   structure, our own link-health measurements, our own poster when we have one), with
   third-party art and synopsis omitted, and `attribution_required` set accordingly in the
   tenant row.

Until then, §3 responses mark every third-party-derived field with `prov` (see §4) and §8 tells
the partner which fields they may not redistribute onward. **Do not quote Tier A revenue in a
forecast while §1.2 is unresolved** — it is the same category of error as the $8–22 CPM figure
corrected in §B.

---

## 2. Namespace and isolation

| Concern | Decision |
|---|---|
| Namespace | `/api/partner/v1/**`. Never `/api/v1`, never `/api/v2`. |
| The app | Keeps `/api/v1/*` and `/api/v2/account*` exactly as they are. No partner code runs in those paths. |
| Versioning | `/v1/` in the path. Breaking change ⇒ `/v2/` alongside it; nothing is ever silently redefined. |
| Deprecation | `Sunset` and `Deprecation` headers, plus a dated entry in §10, minimum 90 days. |
| Data | Reads the same SQLite catalog through `catalog_api`; **writes only** to `api_tenants`, `api_usage`, `api_audit`. A partner request can never mutate catalog rows. |
| Adult content | Every Tier A read passes through `redact`/`catalog_api._adult_clause`, so an `is_18_plus = 1` row is never listed. **See the caveat in §2.1 — this is currently true for rows and not yet true for works.** |
| Provenance | Every response goes through `catalog_api.public_edge` → `redact.scrub`. Internal fields (`source_site`, page URLs, bridge service names) are denied by default and are not obtainable by any request parameter. |

### 2.1 The adult-filtering caveat that belongs in a sales document

`AGENTS.md` records a measured gap: adult flagging is applied per *row* while media identity is
per *canonical key*, and 442 keys contain both a flagged and an unflagged twin — so a hidden film
can still answer a public search under its unflagged entry, e.g. `4 Play` id 23519.

A partner integrating against `/api/partner/v1/search` inherits that gap on day one, and a
customer who is sold "18+ never appears" will find a counterexample and be right. So the contract
states it: filtering is **row-level today, work-level after the `MAX(is_18_plus)` reconciliation
across shared `canonical_key` lands with a test**. Partners building a store listing or a
brand-safe product need to know that before they build, not after. We do not get to be surprised
by this in a support ticket.

---

## 3. Authentication

* A tenant is issued one or more keys: `rk_live_` + 32 URL-safe random bytes, 256 bits of entropy.
* **Stored as `sha256(key)` hex, never plaintext.** The plaintext exists once, in the issuance
  response, and is unrecoverable afterwards. Reset means issue-new-and-revoke-old.
* **Transport: `X-Partner-Key` request header only.** A key in a query string lands in nginx
  access logs, in browser history, in `Referer` headers and in every proxy between. Endpoints
  that accept `?key=` do not exist here, and `partner_api.py` refuses a request whose credential
  arrived in the query string (`401 credential_in_query`).
* TLS is mandatory in production (§7). A key sent over the plain HTTP host we run today is a key
  already disclosed; §7 says so rather than implying it.
* Keys are scoped to one tenant, one plan, one tier set. Rotation: two live keys per tenant
  supported during a cutover window, `revoked_at` timestamp on the old one.
* Hashing caveat: SHA-256 of a 256-bit random token is adequate here. Do not reuse this table for
  user passwords, where it would be the wrong choice.

---

## 4. Response conventions

Success: `application/json; charset=utf-8`. Errors are RFC 7807-ish, matching the shape
`api_v2.py` already emits (`type: /api/v2/problems/<code>`), namespaced to
`/api/partner/v1/problems/<code>`.

Every Tier A payload field that we did not ourselves produce carries a provenance tag rather than
a silent caveat — a partner can see which strings are licensed third-party art and which are ours:

```json
{
  "id": 10492,
  "title": "Example Film",
  "year": 2024,
  "poster_url": "https://…/poster.jpg",
  "synopsis": "…",
  "prov": {
    "title": "ours",
    "poster_url": "tmdb",
    "synopsis": "tmdb"
  }
}
```

`prov` is stable, additive and documented; a partner may key behavior off it and off nothing else.

---

## 5. Rate limiting and quota

Two independent ceilings, because they answer different questions:

* **Per-minute cap** (`rpm_cap`) protects the box. One vCPU, stdlib single-process server,
  shared with crawlers and agents — measured 2026-10-29 (`nproc=1`, `loadavg 5.99`). This is the
  one that keeps a customer from taking us down.
* **Daily quota** (`daily_quota`) protects the business. It is what we bill against and what we
  cut off at plan boundaries.

Fixed-window token bucket, in-process, keyed per tenant per minute. SQLite is the source of truth
for the day counter; the per-minute window is deliberately cheap and allowed to drift by one
window across a restart — a request is not lost or double-billed by a restart, but the minute
bucket resets. State that in §8 so nobody mistakes it for a security boundary.

**Every response carries:**

```
X-Partner-Tenant:        p_8f2c…        (tenant public id, never the key)
X-RateLimit-Limit:       120
X-RateLimit-Remaining:   117
X-RateLimit-Reset:       1761721200      (unix seconds when the window rolls)
X-Quota-Daily-Limit:     50000
X-Quota-Daily-Remaining: 43120
```

Over the minute cap ⇒ `429`, with `Retry-After: <seconds>`. Over the daily quota ⇒ `429` with
`retry_at` set to the next UTC midnight and `X-Quota-Exhausted: 1`. A `429` is metered and
counted — refused requests are still load.

---

## 6. Endpoints

### 6.1 Tier A — open by default

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/partner/v1/catalog` | Paged catalog list. `?work_type&genre&language&quality&updated_since&limit&cursor&sort&order` |
| `GET` | `/api/partner/v1/works/{work_id}` | One work: metadata, seasons, aggregate counts |
| `GET` | `/api/partner/v1/search` | Title/keyword search. `?q&work_type&limit&cursor` |
| `GET` | `/api/partner/v1/works/{work_id}/seasons/{n}/episodes` | Episode structure |
| `GET` | `/api/partner/v1/updates` | Change feed by projection revision — the cheap way to stay in sync |
| `GET` | `/api/partner/v1/health/aggregate` | Our link-availability measurements, **aggregate only** |
| `GET` | `/api/partner/v1/me` | Tenant identity, plan, tier flags, key prefix, `revoked_at` |
| `GET` | `/api/partner/v1/me/usage` | Own metering: today, trailing 7 and 30 days, peak rpm |

Request:

```
GET /api/partner/v1/search?q=dune&work_type=movie&limit=2 HTTP/1.1
Host: api.example.net
X-Partner-Key: rk_live_…
```

Response:

```
HTTP/1.1 200 OK
Content-Type: application/json
X-Partner-Tenant: p_8f2c1d
X-RateLimit-Limit: 120
X-RateLimit-Remaining: 118
X-RateLimit-Reset: 1761721200
X-Quota-Daily-Limit: 50000
X-Quota-Daily-Remaining: 49998
```

```json
{
  "normalized": "dune",
  "total": 34,
  "next_cursor": "eyJzdi…",
  "items": [
    {
      "id": 10492,
      "title": "Dune",
      "year": 2021,
      "work_type": "movie",
      "genres": ["Sci-Fi", "Adventure"],
      "languages": ["English", "Hindi"],
      "synopsis": "…",
      "poster_url": "https://…",
      "rating": 8.0,
      "season_count": null,
      "links_total": 12,
      "links_live_checked": 4,
      "prov": {"title": "ours", "poster_url": "tmdb", "synopsis": "tmdb", "links_live_checked": "ours"}
    }
  ]
}
```

Note `links_total` versus `links_live_checked`: `unchecked` is a first-class value and is
**never** presented as live. A scraper wrote `active` into every ledger row at ingest
(`catalog_v2._link_state_of`), and a partner who is sold a number that conflates "nobody looked"
with "it works" will build a UI on it and blame us when it is wrong. `links_by_state` breakdowns
use the closed projection vocabulary `unchecked|active|dead|expired|unknown` and nothing else —
the fold and the audit that enforces it are what milestone A of this session landed.

`/health/aggregate` is deliberately aggregate: counts per work and per `source_site`, no endpoint
URLs, no service names. Per-endpoint liveness is Tier B wearing a lab coat — it tells a customer
which infringing copies are currently up without making them ask.

### 6.2 Tier B — fenced, off by default

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/partner/v1/resolve` | `{ "work_id": 10492, "season": 2, "episode": 3, "quality": "1080p" }` → watch/download URLs |

Gated by §1.1: `api_tenants.allow_tier_b = 1` **and** global `PARTNER_TIER_B_ENABLED = True`.
Refusal shapes:

```json
{ "type": "/api/partner/v1/problems/tier_not_enabled",
  "code": "tier_not_enabled",
  "title": "This capability is not enabled for your tenant",
  "detail": "Source-link resolution requires explicit per-tenant enablement by the data owner. Tier A metadata is unaffected.",
  "status": 403 }
```

```json
{ "type": "/api/partner/v1/problems/tier_globally_disabled",
  "code": "tier_globally_disabled", "title": "Capability disabled",
  "detail": "Source-link resolution is disabled service-wide.", "status": 503 }
```

Both refusals are audited (§6.3) — a tenant hammering `/resolve` against a fence is information.

### 6.3 Audit rows

```sql
CREATE TABLE IF NOT EXISTS api_audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  tenant_id TEXT NOT NULL,
  kind TEXT NOT NULL,             -- tier_b_refused | tier_b_released | cutoff | key_issued | key_revoked
  work_id INTEGER,
  detail TEXT                      -- JSON; never a key, never a URL from a request body
);
CREATE INDEX IF NOT EXISTS idx_audit_tenant_ts ON api_audit(tenant_id, ts);
```

`tier_b_released` stores the **count** of URLs released, not the URLs. Enough to bill and to
reconstruct a decision, without turning an audit table into a second copy of the ledger.

---

## 7. Edge (nginx) — **documented here, not applied**

`^~ /api/` currently `403`s everything not allow-listed, which is the right default and why a
partner route needs an explicit entry. The block to hand to the owner:

```nginx
# Partner API — Tier A. Additive to the existing ^~ /api/ 403 default.
location ^~ /api/partner/ {
    limit_req zone=partner_api burst=20 nodelay;
    limit_req_status 429;
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header X-Forwarded-For   $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Host              $host;
    proxy_read_timeout 15s;
    client_max_body_size 8k;
}
# Tier B stays unreachable at the edge while the capability is disabled.
location = /api/partner/v1/resolve {
    deny all;          # remove deliberately, per tenant enablement + owner sign-off
}
```

with, in `http {}`:

```nginx
limit_req_zone $http_x_partner_key zone=partner_api:16m rate=60r/m;
```

**Nobody on this lane edits the live nginx config.** The owner applies it. Two notes they should
apply with it:

1. `limit_req_zone` keyed on `$http_x_partner_key` is a *shared* secret in the sense that it is a
   name in a header, and an empty header collapses all anonymous traffic into one bucket — which
   is the desired fail-closed behavior, but say so before someone is surprised their unauthenticated
   probe was throttled by another customer's key. A `map` to a per-IP zone is the alternative.
2. Rate limiting at the edge and in the app are not redundant. Edge protects the single vCPU from
   cheap traffic; the app's per-tenant bucket is the one that knows who is being billed.
3. The edge zone rate should stay at or below the smallest plan's `rpm_cap`, otherwise a tenant
   gets `429` with a `Retry-After` that contradicts our own `X-RateLimit-Reset`. If the two
   disagree, the app wins and the edge is only a blast shield.

### 7.1 Transport

There is no TLS on this host today: `92.4.95.252` is plain HTTP, and `location /` proxies
code-server. **Partner traffic over plain HTTP is not offered.** Before a tenant key is issued:
a certificate on a real hostname, `listen 443 ssl`, HTTP→HTTPS redirect, HSTS, and a key
revocation runbook that works in minutes. Until then this document is a specification, and the
only honest price list is zero.

---

## 8. What you may build with this

Permitted, on Tier A:

* A browsing/discovery UI: search, grids, detail pages, season/episode structure, artwork where
  `prov` says the field is licensed for your use (§1.2).
* Editorial features keyed on our own measurements — "currently 4 verified-live copies", sorted by
  `links_live_checked`. Our probe history is the differentiated product; nobody has to buy it from
  us to get it, which is why it is the part worth pricing.
* A local cache for up to 30 days, with attribution and the `prov` map preserved, and a
  `updated_since`/`/updates` refresh policy. No permanent mirror.
* Building your own playback on your own content. This API tells you what exists where; it is not
  a content supplier and does not claim to be one.

Not permitted:

* **Redistributing the dataset.** No reselling, no sub-licensing, no bulk export, no "API for our
  API". `GET /catalog` with `limit` maxed in a loop is a bulk export and is treated as one.
* Republishing third-party-derived fields (§1.2) as your own licensed content, or removing `prov`.
* Any use implying our catalog is licensed, authorized, or complete.
* Scraping or storing artwork we do not have rights to redistribute.
* Presenting `unchecked` link counts as live availability (see §6.1), or presenting a work as
  adult-free while §2.1's row-level gap stands — the `is_18_plus` reconciliation is the honest
  dependency for that claim.
* Circumventing metering: rotating keys to reset a bucket, sharing one key across products, or
  proxying us for another party. `X-Partner-Tenant` is in every response so you can see which of
  your own integrations is spending.

`api_tenants.attribution_required` is `1 DEFAULT`: the display string is stored per tenant and
rendered by the partner, and a plan that does not want attribution is a different conversation with
a different price and a written answer about the fields in §1.2.

---

## 9. Enforcement, cutoff, and geography

* Hard cutoff on daily quota, plan expiry, or a manual `status = 'suspended'`. Suspension is
  instant (`403 tenant_suspended`), audited, and reversible.
* Abuse signals we meter: request amplification against `limit`, sustained `/resolve` attempts
  while fenced (§6.3), key sharing across distinct `X-Forwarded-For` origins.
* **§9 markets.** Tier A licensing and Tier B enablement are separate decisions in each of: United
  States (DMCA, §512 posture, state AG consumer authority), European Union (DSA, copyright
  Directive Art. 17), India, Pakistan (Punjab Consumer Protection Act 2009 and the federal 2024
  framework, PECA for electronic distribution), and any storefront under Google Play's
  deceptive-behavior policy. §1.1 is why the second one is the hard one, and it is why §1.2 exists:
  being a rights-infringer's *supplier* is a distinct exposure from being a rights-infringer.
* Termination for cause deletes `api_usage` rollups that identify the tenant's traffic beyond what
  billing law requires, and revokes keys immediately. We keep the audit table.

---

## 10. Skeleton and how it is verified

`Fast_Fetch/partner_api.py` — stdlib only, no new dependency, **not registered on any live
server**. It contains the schema in §3/§5/§6.3, the auth and gate logic (`authorize()`,
`check_rate()`, `release_allowed()`), the route table, and the refusal shapes. It is deliberately
inert: `viewer.py` does not import it, `fast_fetch.py serve` does not route to it, and enabling it
is a deliberate, reviewable change — which is the same fence §1.1 asks for, applied to the code
rather than the data.

Self-check:

```bash
python3 -S Fast_Fetch/partner_api.py --self-test     # schema, gate, limiter, query-string refusal
```

The self-test asserts the four things that must not regress: a tenant row defaults
`allow_tier_b = 0`; `release_allowed()` is false when the global switch is false even with the
per-tenant flag set; a key arriving in the query string is refused; and the minute bucket rolls.

Rollout, in order, with no step skipped: ① resolve §1.2 licensing or scope Tier A to the
rights-clean subset → ② TLS on a real hostname → ③ register the read-only Tier A routes with a
single internal tenant → ④ meter for two weeks and publish our own request/second number (§G of
the fleet plan carries an estimate, not a measurement) → ⑤ invoice the first customer → ⑥ decide
Tier B, in writing, with counsel.

---

## 11. Error codes

| HTTP | `code` | Meaning |
|---|---|---|
| 400 | `invalid_input` | Malformed or out-of-range parameter; `errors[]` names each one |
| 401 | `missing_key` | No `X-Partner-Key` header |
| 401 | `unknown_key` | Hash matched no tenant |
| 401 | `revoked_key` | Tenant exists, this key does not |
| 401 | `credential_in_query` | Key supplied as a query parameter; see §3 |
| 403 | `tenant_suspended` | Manual cutoff, §9 |
| 403 | `plan_expired` | Term ended; usage retained for billing |
| 403 | `endpoint_not_in_plan` | Route exists, plan does not include it |
| 403 | `tier_not_enabled` | Tier B requested, tenant flag is `0`, §6.2 |
| 503 | `tier_globally_disabled` | Tier B requested, global switch is off, §1.1 |
| 404 | `not_found` | No such work, or it is `is_18_plus = 1` (indistinguishable, deliberately) |
| 409 | `stale_cursor` | Catalog revision moved under a paged walk; restart the walk |
| 413 | `body_too_large` | `client_max_body_size`, §7 |
| 429 | `rate_limited` | Per-minute cap; `Retry-After` is authoritative |
| 429 | `quota_exhausted` | Daily quota; `retry_at` is next UTC midnight |
| 500 | `internal` | Unexpected. `request_id` in body, matching server log; no stack, no SQL |
