# GOFILE_API.md — GoFile public-API scout notes (LANE 4, order `qoder14_gofile`)

**Author:** qoder14 · **Date:** 2026-11-05 · **Status:** documentation only — no
resolver/unpacker code is authorised by this order, and none was written.

**Every claim below is labelled `[OBSERVED]` (request made from this box tonight,
response printed into this session) or `[DOCUMENTED]` (from published
transcriptions of GoFile's own docs; not verified against a live response here).
Anything I could not verify is said so plainly instead of being filled in from
memory.**

## Scope and boundaries kept

- One link we already hold in our own catalog, a handful of requests, 15 s
  timeouts, no loops, no sweeps, no enumeration. 429 was never hit; had it been,
  this file would say what the response was and stop.
- **No credential handling of any kind.** GoFile's guest-account token flow is
  documented in section 5; we did **not** call it, because minting a token —
  even a guest one — is "requesting a token" and this order forbids it.
- No browser-session mimicry to reach non-public content; a password/locked file
  would have been recorded, never solved.

## 1. Base host and version `[OBSERVED]`

- Base host: `https://api.gofile.io` — reachable from this box, `server: nginx`,
  JSON responses (`application/json; charset=utf-8`).
- Path version: **none visible** — paths are flat (`/servers`, `/contents/{id}`),
  no `/v1/`/`/v2/` segment. `[DOCUMENTED]` historically describes this same flat
  shape and flags the API as "BETA, endpoints may change".
- `GET /servers` → **HTTP 200** `[OBSERVED]` with `{"status":"ok","data":{"servers":
  [{"name":"store8","zone":"na"}, …store-eu-par-*, store-na-phx-*…]}}`.
  `[DOCUMENTED]` guidance: do not call it more than once per 10 s.

## 2. Content-metadata endpoint — the wall we hit `[OBSERVED]`

`GET https://api.gofile.io/contents/<fileId>` for a public share we already hold:

> **HTTP 401, body `{"status":"error-token","data":{}}`, no `WWW-Authenticate` header.**

So the metadata endpoint is **not anonymous**, even for a public file. The
`[DOCUMENTED]` request shape is:

- Method/path: `GET /contents/{contentId}`
- Auth: account token in `Authorization: Bearer <token>` (older transcriptions
  say `Basic`; current docs show Bearer) — `[DOCUMENTED]`, `[NOT VERIFIED]`
- Query params `[DOCUMENTED]`: `recursive` (folders), `websiteToken` (a public
  per-site token the web client obtains first), `cache` (bool), `password`
  (sha256 hash, only relevant for password-protected content).
- A bad/unknown id could not be distinguished from the missing-token case: the
  server answers **error-token before validating the id** `[OBSERVED]` — useful
  for us: id-guessing gets no signal, so there is nothing to enumerate anyway.

The share page itself `https://gofile.io/d/<fileId>` answers **HTTP 200**
`[OBSERVED]`, `text/html`, ~3.4 KB — a JS app shell (the "Gofile needs
JavaScript" page), i.e. HTML parsing yields nothing without executing their
client, which is exactly the fragility this order is trying to replace.

## 3. Response fields `[DOCUMENTED]` — and what our schema would do with them

**We never saw a live content payload** (section 2). The field list below is the
documented shape, each with our mapping; treat it as a spec-to-verify, not an
observation.

| GoFile field | our schema | why we care |
|---|---|---|
| `id` | `download_sources.resource_id` | the `<fileId>` in `gofile.io/d/<id>` |
| `name` | `release_title` / link label | filename incl. quality tags our scraper labels throw away |
| `size` | `file_size_bytes` | real byte count for the player + UI |
| `mimeType` | `mime_type` / container | drives `kind` (file vs playlist) in `resolved_cache._derive_kind` |
| `link` | `url` (the `play_url` we would 302 to) | the direct-file URL — the whole point |
| `type` | — | `file` vs `folder`; folders are never playable |
| `status` | `status` / `link_state` | see unbankable rules below |
| `password` (flag/presence) | **record only** | password-required must be stored as such; **never solved, never cached servable** |
| `create_time`/`updateTime` | provenance/age | not freshness — see §6 |

`status` values `[DOCUMENTED]`: `ok`, `not_found`, `locked`, `password` (plus
the transport-level `error-token` `[OBSERVED]`). Mapping to `resolved_cache`:

- `ok` → bankable row, subject to §6 freshness.
- `not_found` → `dead` (the honest terminal state; fail circuit may count it).
- `locked` / `password` → **unbankable, NOT dead**: a human with the password
  could serve it; we refuse both outcomes — never mark the link dead, never
  write a servable cache row. Today our pipeline lumps these into generic
  resolve-failures; when an unpacker is ever written it must keep them separate.

## 4. Direct-link download semantics — `[NOT OBSERVABLE WITHOUT AUTH]`

Whether `link` needs headers, whether the origin answers **206 with `Range`**
versus 200 — we could not test this, because obtaining `link` requires the
authenticated contents call (§2). Therefore: **`is_resumable` for gofile stays
NULL/untested**; nothing may be written to `resolved_cache` claiming resumable
until someone probes it honestly. Do not inherit any assumption from the older
`fastdl`/`pixeldrain` rows.

## 5. The guest-token flow exists — and we are deliberately not using it `[DOCUMENTED]`

GoFile's docs describe minting a throwaway guest account (`POST /accounts/guest`,
returns a token usable as the account token) — which is how their own web player
reads a public file. It is public, it is theirs, but **a token is a credential**:
this order's boundary ("do not use, **request**, harvest…") excludes it, and the
earlier "find latest active JWT" directive stays refused. **The consequence for
the implementor's decision:** a policy-compliant gofile resolver cannot get
`link` via the official JSON API from our box. Either (a) crown explicitly
authorises a per-request guest-token mint as a *bounded, own-credential* flow
(this is GoFile's intended public mechanism, not circumvention — but it is a
policy call above my order), or (b) gofile stays HTML/JS-redirect resolution
only. This is a successful outcome of the order, reported as such.

## 6. Category recommendation + the expiry answer crown asked for

- **One-line answer: NO — no `[OBSERVED]` or `[DOCUMENTED]` response field
  reports a lifetime for the direct `link` of a public file, so there is nothing
  today that can drive `expires_at` honestly; the only `expireTime` in the API
  is an optional *input* to the account-owned *Create Direct Link* endpoint
  (`POST /contents/{contentId}/directlinks`, with `sourceIpsAllowed`,
  `domainsAllowed`, `auth`) — a feature premium accounts use to *issue* expiring
  links, not a field the public metadata response returns.**
  Consequence: Category A's 24 h `HEURISTIC_CAP_PERMANENT_SECONDS` + 24 h
  `POOL_RECHECK_SECONDS` cap in `resolved_cache` remains the right ceiling for
  gofile; if a live payload ever *does* carry a TTL, honour
  `min(expireTime, 24h cap)`, which `_compute_reverify_after` already supports.
- **Classification row to look at:** `host_classifier._HOST_TABLE`
  `("gofile.io", CATEGORY_DIRECT_FILE, "gofile")` and `_SERVICE_TABLE["gofile"]`
  — letter **A**, and the coverage table (2026-11-05) measured **154,228 live
  links** behind it (3.8% of catalog). Recommendation **unchanged: Category A
  (permanent direct file)** for *shape* — gofile files are static objects —
  **but** with two honest caveats: (i) until §4 is probed, `is_resumable` must
  stay untested, and (ii) the AND-rule in `resolved_cache._derive_category`
  already requires the resolved URL host to be `gofile.io` before any horizon-A
  is banked, which is exactly the guard this box needs given §5's wall.

## 7. How I verified this — dated request log (2026-11-05 ~02:10 UTC box time)

| # | request | result |
|---|---|---|
| 1 | `GET https://api.gofile.io/servers` (UA'd, 15 s timeout, no auth, no cookies) | **200**, JSON server list (excerpt in §1) |
| 2 | `GET https://api.gofile.io/contents/<fileId>` — one share id taken from our own `download_sources WHERE service='gofile'` (id redacted here) | **401** `{"status":"error-token","data":{}}` |
| 3 | `HEAD https://gofile.io/d/<fileId>` (same link, liveness only, no body read) | **200**, `text/html`, `content-length 3358` |

Plus two documentation reads: GoFile's own docs page (JS-gated; unreadable
without executing their app — noted honestly) and a community transcription of
it (`github.com/sethbang/gofile-cl/GOFILE_API.md`, last updated 2024-06-12) —
every field attributed to that source is tagged `[DOCUMENTED]`, and none of the
API-behaviour claims above rest on it alone where §2 gave a direct observation.

No secrets in this file: no token, cookie, `Authorization` value, or working
credentialed URL appears; the two real share ids were replaced by `<fileId>` at
write time. Requests total: **3**. 429: **never encountered**.
