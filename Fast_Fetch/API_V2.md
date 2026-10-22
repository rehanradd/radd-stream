# Radd Stream — Catalog API v2 contract and data model

Status: design approved for implementation · Owner: Fast_Fetch · Verified against `viewer.py`/`fast_fetch.py` on 2026-10-21

This document is the single source of truth for what the app (and any future website)
may rely on. v1 stays running and unchanged; v2 is built beside it.

---

## 0. Why v2 exists — the v1 defects this design removes

Every one of these was verified in `Fast_Fetch/viewer.py` / `Fast_Fetch/fast_fetch.py`:

| # | v1 behaviour | Consequence | v2 answer |
|---|---|---|---|
| 1 | `releases` are keyed by `(post_id, source_site, origin_url)` only as of the `origin_url` fix; `season`/`episode` are free text (`S01` vs `1`, `E01` vs `1` vs `Batch`) | A client cannot know which episodes exist, which file covers them, or which print is best | structured `cat_episodes` + `cat_releases.coverage` |
| 2 | `content_type` filter is exact-match; `?type=anime` is documented but no row ever stores `anime` | documented filter returns nothing | explicit `work_type` + `animated` facet |
| 3 | `/api/v1/posts/{id}` returns releases `ORDER BY id ASC`; quality ordering exists only as a `CASE` over `service` inside a release | the first release a scraper happened to write is "first" for the UI | every release carries a computed `quality_score`; ordering is by score, not insertion |
| 4 | `resolve_live_source()` falls through to `success: true` and 302s even when no fresh URL was found | a dead link looks alive to the player forever | `streamable`/`ok` are measured properties; an unplayable link is never offered as playable |
| 5 | no measurement of links: `status` is written `active` at scrape time and never re-checked | ranking cannot use reality | `cat_link_evidence` from `link_health.probe()` |
| 6 | no auth, no rate limit, `Access-Control-Allow-Origin: *`, binds `0.0.0.0` | anyone can hammer the resolver and burn egress | §11 hardening requirements |
| 7 | `/api/heal` builds a payload and never writes a response → client hangs | unusable | removed from v2; replaced by `POST /api/v2/links/{id}/report` |
| 8 | `is_18_plus` filtering is implemented but undocumented; nothing proves it in a contract | an app could accidentally surface it | §10 gating rules, tested |

---

## 1. Layered architecture

```
 Layer 0  INGEST LEDGER (existing, unchanged, append-only spirit)
          per-site staging DBs → merge_catalogs.py → posts / releases /
          download_sources / post_sources / sitemap_cache
          · the scrape ledger: stores what the site said, verbatim, zero loss
          · never read directly by clients

 Layer 1  CANONICAL CATALOG (new: cat_* tables, projection)
          works / seasons / episodes / releases / links / tracks / evidence
          · structured, deduplicated, ranked, auditable
          · rebuilt any time from Layer 0 (projector is idempotent)

 Layer 2  API (this contract)
          browse → detail → play, with entitlements and telemetry
```

Rules:

- **The ledger is never "fixed" by hand.** Corrections happen by re-scraping or by a
  projector rule; Layer 1 is disposable and regenerated.
- **Layer 1 never loses a link.** A link that is dead is kept with `state='dead'` and its
  last evidence, so healing later is possible and link health is auditable.
- **Clients only see Layer 1 + 2.** No client may depend on Layer 0 column names.

---

## 2. Identity — how we guarantee "no movie or season got wrong"

### 2.1 Work identity ladder

A `work` is one abstract title. Identity resolution tries, in this order, and **stops at
the first level that matches exactly one candidate**:

1. external id we trust most: `imdb_id` (`tt…`) → then `tmdb_id` → then `tvdb_id`
2. `(normalized_title, year, work_type)` exact triple
3. `canonical_key` + year + **work_type family** (movie vs series never cross-merge)
4. no match → create a new work

Hard rules:

- A **movie and a series with the same title and year are two works.** (v1 aborts with
  `ValueError: … different media type`; v2 files them separately and links them as
  `remake_of`/`based_on` when evidence exists.)
- Year disagreement between sources never merges. If one site says 2019 and another 2020
  and both lack external ids, they stay separate works and a `cat_review_queue` row is
  raised — a human/agent decides, and the decision is stored as `cat_work_external_id`
  provenance so it survives rebuilds.
- An external id that matches two existing works is a **conflict**, never a merge
  (v1 raises; v2 keeps the rows and blocks promotion to the public catalog).
- Title normalisation is locale-aware and alias-aware: `cat_work_alias(title, locale,
  source_site, kind ∈ {original, aka, localized, transliteration, romanized})`. Two sites
  calling the same film differently are merged only through an id or an alias row that
  records which site said what.

### 2.2 Hierarchy

```
work ──< season ──< episode
  │                  (anime/TV/anime-special)
  ├──< part          (movie released in Part 1/2, disc 1/2, or a 3-hour special)
  └──< release ──< link
          │        └──< track (audio / subtitle)
          └── coverage: which episodes or parts a release contains
```

- `work_type ∈ {movie, series, anime, tv_special, miniseries, documentary, sport_event,
  music_video, unknown}` plus the boolean `is_animated` (kept from v1) so `animated=true`
  works as a facet even for `series`.
- `season.number` is an integer; `season.type ∈ {regular, special, extra}`.
- `episode.number` is integer within a season, `absolute_number` is the show-wide index,
  and `episode.air_date` is optional.
- A **special/unaired episode** never renumbers regular episodes — `season.type` carries it.

### 2.3 Coverage — the pack problem, solved

Some releases are one file per episode; some are "S07 complete in one video"; some are
`EP(01-06)` batches. A release therefore declares coverage instead of pretending to be an
episode:

```
cat_releases.coverage_type   ∈ {whole_work, season_pack, episode_range, single_episode, parts}
cat_release_episodes(release_id, episode_id, ordinal, offset_seconds, chapter_title)
```

- `single_episode` / `episode_range`: rows are materialised for every episode the release
  contains — the API can answer "is episode 3 available?" without parsing text.
- `season_pack` with no known chapter offsets: rows exist with `offset_seconds = NULL`.
  The player shows a single file with a warning (`coverage.needs_offset_calibration`)
  and the app records user-entered offsets via `POST /api/v2/episodes/{id}/offset`,
  which is what turns a "guess" into calibrated chapter data over time.
- `whole_work` covers multi-part films; each `part` gets its own link set.
- **An episode must never be attributed to the wrong season.** The projector derives
  season from the structured release descriptor (`S07`, `Season 7`) and only falls back to
  the page's declared season when the descriptor is silent; when the two disagree the
  release is flagged `identity_suspect` and excluded from `episodes[].best_release_id`.

---

## 3. Prints — one title, many versions, ordered

A `cat_releases` row is **one print** of one coverage scope, assembled from the messy
ledger text by `release_descriptor.describe()`:

```
resolution (2160p|1080p|720p|480p) · source_tag (bluray|uhd_bluray|web_dl|webrip|hdtv|
dvdrip|telesync|telecine|cam) · codec (h264|h265|av1) · bit_depth · hdr
(dolby_vision|hdr10_plus|hdr10|hlg) · container · edition (theatrical|director_cut|
extended|unrated|remastered|restored|uncut|imax) · version (v1,v2,…) · group
(size_bytes · size_per_episode_bytes · audio {languages, channels, codecs} ·
subtitles {hardcoded, external, langs} · watermarked · official_print · quality_score)
```

Ordering rules shown to the user (this is the product contract, not a suggestion):

1. **Best first**, by `quality_score` — 4K HDR BluRay → 4K WEB-DL → 1080p BluRay →
   1080p WEB-DL → 1080p WEBRip → 720p → 480p → CAM. A CAM can never outrank a
   distribution print, and a 720p CAM is sorted below a 1080p WEBRip regardless of which
   site scraped it first.
2. Ties broken by: `official_print` desc → link health score desc → source-site trust
   tier → release `first_seen_at` desc (fresher repack wins).
3. Editions are grouped, not interleaved: the UI gets `prints[]` where each print lists
   its own links, so "Director's Cut" never looks like a worse quality of "Theatrical".
4. Watermarked and fan-edited prints are kept and labelled (`flags: ["watermarked"]`) —
   the user decides; we do not silently drop data (Zero Data Loss rule).

---

## 4. Links — what kind of link it is, and what it can do

```
cat_links(id, release_id, site, service, kind, url, final_url, resource_id,
          playability, resumable, cors_open, ephemeral, expires_at,
          state, tier, rank_score, last_evidence_id, ...)
cat_link_evidence(link_id, probed_at, protocol, http_status, content_type, size_bytes,
                  latency_ms, speed_mbps, accepts_ranges, ok, error)
```

`kind` (what the URL *is*):

| kind | meaning | example family |
|---|---|---|
| `cdn_direct` | a file on a CDN, directly fetchable | google_cdn / fsl_r2 / hubcloud_10g / hubcdn |
| `hls_manifest` | `.m3u8` master playlist | toonworld hubcloud video, fzcdn |
| `cloud_page` | an HTML page that requires a resolve step | gdtot, pixeldrain page, filepress |
| `bridge` | an interstitial/redirect page we cannot unwrap yet | linkrit, tw4all redirect |
| `embed` | iframe player, playable only in a webview | dropgalaxy, razorshell |
| `download_only` | file host link for offline save, not for streaming | mega, 1fichier, megaup |
| `torrent` | reserved, not implemented | — |

`playability` (what a client can do with it) is **measured, not declared**:
`stream | download | both | webview | none`, produced by `link_health.probe()` and
refreshed by `link_health.merge_health_history()`. A `bridge`/`cloud_page` is `none`
until it resolves to a `cdn_direct`/`hls_manifest`; `is_temporary` links carry
`expires_at` so the client knows to re-request instead of caching a rotting URL.

Ranking inside a release uses `rank_score` = `quality_score`-independent link score
(playability ≫ speed ≫ freshness, per `link_health.score_link`), so the worst-quality
print that actually plays beats the best-quality print that 404s.

---

## 5. Playback contract — what the Android app does

`POST /api/v2/play` returns a **PlayBundle**: an ordered, self-describing failover plan.

```json
{
  "session": {"id": "pb_…", "issued_at": 1730000000, "expires_in": 900,
              "strategy": "failover", "rotate_on": "next_playback_session"},
  "target": {"kind": "work", "id": 1234, "work_type": "series",
             "season": 7, "episode": 3, "episode_id": 98765},
  "renditions": [
    {
      "rank": 1,
      "release_id": 555,
      "print": {"label": "1080p WEB-DL · H.265 · Hindi 5.1 + English · ESubs",
                "resolution": "1080p", "source_tag": "web_dl", "codec": "h265",
                "hdr": [], "edition": "theatrical", "quality_score": 712,
                "size_bytes": 2405181686, "watermarked": false, "official_print": true},
      "playback": {
        "url": "https://cdn…/1080p.m3u8?e=…",
        "protocol": "hls",              "container": "m3u8",
        "mime_type": "application/vnd.apple.mpegurl",
        "requires_resolve": false, "http_headers": {},
        "seekable": true, "accepts_ranges": true, "resumable": false,
        "cors_open": true, "expires_at": 1730000900,
        "score": 830, "ephemeral": true,
        "drm": null                     // or {"system": "widevine", "license_url": …}
      },
      "tracks": {
        "audio": [{"lang": "hi", "name": "Hindi", "default": true,  "channels": "5.1",
                    "codec": "eac3"},
                   {"lang": "en", "name": "English", "default": false, "channels": "2.0"}],
        "subtitles": [{"lang": "en", "kind": "subtitles", "url": "…", "format": "vtt",
                        "default": false, "forced": false}]
      },
      "coverage": {"type": "single_episode", "ordinal": 1, "offset_seconds": null,
                    "needs_offset_calibration": false}
    },
    {
      "rank": 2,
      "playback": {"protocol": "progressive", "container": "mp4", "resumable": true, "…": "…"},
      "coverage": {"type": "season_pack", "ordinal": 3, "offset_seconds": 4920,
                    "needs_offset_calibration": false,
                    "pack_warning": "This file contains all of Season 7"}
    }
  ],
  "download_options": [
    {"release_id": 555, "url": "…", "kind": "cdn_direct", "resumable": true,
      "size_bytes": 2405181686, "score": 640, "expires_at": null}
  ],
  "failure_policy": {
    "retry_same": 1, "then_next_rank": true, "max_ranks": 3,
    "report_url": "/api/v2/links/555/report", "backoff_ms": 800
  }
}
```

App behaviour the contract mandates:

- **Try rank 1; on error, retry once, then move to rank 2, then rank 3 — never beyond
  `max_ranks`** (each failover is reported back).
- HLS → `MediaItem.fromUri` with `defaultTrackSelector` set to prefer the user's audio
  language; progressive with `accepts_ranges: true` → seekable; `accepts_ranges: false`
  → disable seeking in the UI rather than letting ExoPlayer stall.
- `cors_open: false` + our HTTP-only host means a WebView/`Media3` direct fetch may be
  blocked by the site — that is why `webview` playability is a separate kind, never a
  silent fallback.
- `expires_at` in the past ⇒ re-call `/api/v2/play`; never persist a PlayBundle URL
  beyond its lifetime. `download_options` with `resumable: true` are the only ones the
  app may offer for offline save (Android DownloadManager / WorkManager + Range resume).
- A `season_pack` rendition for an episode request must show `pack_warning` and seek to
  `offset_seconds` when known.

---

## 6. Scenarios the contract must handle (test matrix)

Each row is a real corpus shape; each is an assertion in
`Fast_Fetch/test_api_v2_scenarios.py`, and the projector must satisfy them against the
merged catalog with **real data**, not fixtures only.

| # | Scenario | Required outcome |
|---|---|---|
| 1 | Movie, 1 print, 1 direct CDN link | play returns 1 rendition, `protocol: progressive`, download offered |
| 2 | Movie, 5 prints (4K DV BluRay, 1080p WEB-DL, 720p WEBRip, 480p, CAM) | ranks strictly by `quality_score`; CAM last |
| 3 | Same movie, prints from 3 different sites | one `work_id`; each print keeps `sites[]` provenance; no duplicate print rows |
| 4 | Series, per-episode files, 2 seasons | `episodes[]` per season, each with its own best release |
| 5 | Series, season-pack file only | each episode resolvable; `coverage.type: season_pack`; `pack_warning` present |
| 6 | Series, mixed: some episodes individual, rest in a batch | batch + individual both listed for the covered episodes; individual ranks first when equal quality (smaller file, precise seek) |
| 7 | Season split `EP(01-06)` + `EP(07-12)` on one page | two releases, two coverage ranges, no episode attributed twice to the same print |
| 8 | Movie with parts (Part 1 / Part 2) | two `parts`, each playable; work detail shows part order; never merged into one 5-hour episode |
| 9 | Anime with dub + sub prints, and one file containing 12 episodes | `audio.tracks` lists both languages; sub-only print is not offered as "Hindi"; pack warning as #5 |
| 10 | Movie where one site's print is watermarked | kept, flagged `watermarked`, ranked below the clean print of same resolution |
| 11 | Same film listed by two sites with different years | not merged; both works exist; review queue raised |
| 12 | Title with a 2019 movie and a 2019 series of the same name | two works, `type` facet keeps them separate; v1's `?type=` bug cannot recur |
| 13 | Every link of a release is dead | detail shows the work (`state: unavailable`), `/play` returns 409 `no_playable_source` with the reason per rank; browse still lists it (we do not hide data) but `available: false` |
| 14 | Links that are bridges/embeds only | `playability: webview`/`none`, never presented as `stream` |
| 15 | Ephemeral link (`is_temporary=1`) past `expires_at` | `/play` re-resolves; a cached bundle for it is rejected with 410 `bundle_expired` |
| 16 | Two prints, one HLS + one progressive | `protocol` reported per rendition so the app picks the right `MediaSource` |
| 17 | 18+ title | invisible in browse/search/suggest/stats/M3U; `/play` refuses `403 adult_restricted`; `?include_adult=true` has no effect without `X-Radd-Admin` |
| 18 | Paid title (future) | `entitlement` block present with `model: paid`; free renditions absent; app shows price, cannot play without licence |
| 19 | Title with only a download mirror (no stream) | `renditions: []`, `download_options` non-empty, `available_download: true` |
| 20 | Concurrent identical `/play` calls for the same episode | same bundle within its validity window (idempotent, no fresh CDN token storm) |

---

## 7. Entitlements — the future paid/free model (reserved now, so we never migrate twice)

```
cat_entitlements(id, work_id|null, release_id|null, model,          -- free | ad_supported
                                                          | subscription | rental | purchase
                 price_minor, currency, region, geo_allow[], geo_deny[],
                 valid_from, valid_until, rental_hours, ownership,   -- never | until_expiry | permanent
                 requires_account, requires_age_gate, updated_at)
```

- Default row: `model='free'`, `requires_account=false`. Everything behaves as today.
- **Rental vs purchase differ only in `rental_hours` + `ownership`**, so a client can cache
  honestly: `ownership=until_expiry` ⇒ the app must expire its offline copy.
- Price is stored in **minor units + ISO currency** (`price_minor=14900, currency='INR'`)
  — never floats.
- Entitlements attach to a work *or* a release, so "4K costs more than 720p" is expressible.
- `/api/v2/play` checks entitlements server-side and returns `402 licence_required` with the
  entitlement payload; the app must never be the only gate.

---

## 8. Endpoint surface

Base: `/api/v2`. All responses `application/json; charset=utf-8`. Errors use the envelope
in §10.4. Reads are cacheable; `POST /play` is not.

| Method & path | Purpose | Key params |
|---|---|---|
| `GET /api/v2/manifest` | machine-readable contract: field dictionaries, enum values, scoring formula, limits, version | — |
| `GET /api/v2/browse` | faceted catalog browse | `type`, `animated`, `genre`, `language`, `country`, `year_from/to`, `min_quality`, `available`, `sort=newest\|rating\|title\|score`, `cursor`, `limit≤100` |
| `GET /api/v2/search` | title search | `q`, same facets, `fields=` sparse |
| `GET /api/v2/suggest` | cheap type-ahead | `q` (2+ chars), `limit≤10` |
| `GET /api/v2/works/{id}` | full detail: seasons, episodes, prints, availability, entitlement, aliases, images, credits, provenance | `fields`, `lang` |
| `GET /api/v2/works/{id}/seasons/{n}` | one season + its episodes with per-episode best print | `fields` |
| `GET /api/v2/episodes/{id}` | one episode: prints, coverage, links | — |
| `GET /api/v2/releases/{id}` | one print: descriptor + ranked links + tracks | — |
| `POST /api/v2/play` | PlayBundle (§5) | body: `work_id` \| `release_id` \| `episode_id`, `prefer` (`quality\|speed\|data_saver`), `device` (`hdr`, `hevc`, `max_height`, `network`) |
| `POST /api/v2/links/{id}/report` | client telemetry (`played\|stalled\|failed\|resolved`) | body: `event`, `ms`, `error` |
| `POST /api/v2/episodes/{id}/offset` | submit learned pack offset for a season-pack file | body: `offset_seconds` |
| `GET /api/v2/sync?since=` | delta rows for offline catalog cache (§10.3) | `since` (cursor), `scope=catalog\|health`, `limit` |
| `GET /api/v2/collections/{id}` | franchise/pick-list grouping | — |
| `GET /api/v2/feed.m3u` | M3U for external players — **adult filtered, non-ephemeral only** | `work_id` |
| `GET /api/v2/stats` | totals by site/type/quality, link-health mix, last projection | — |
| `GET /api/v2/health` | liveness/readiness for ops | — |

Removed from v2: `/api/v1/heal` (never responded), `/api/fetch` (unauthenticated remote
ingestion — moves behind admin auth or becomes a CLI-only operation).

---

## 9. Resource shapes (canonical examples)

`GET /api/v2/browse` item — deliberately small, everything a grid needs:

```json
{"id": 1234, "title": "Campus Beats", "year": 2026, "work_type": "series",
 "animated": false, "poster": {"url": "…", "width": 1000, "locale": "en"},
 "rating": 6.1, "genres": ["Crime", "Drama"], "languages": ["hi"],
 "seasons": 7, "episodes": 84, "quality_max": "1080p",
 "available": {"stream": true, "download": true}, "updated_at": 1730000000,
 "entitlement": {"model": "free"}}
```

`GET /api/v2/works/{id}` — adds `aliases[]`, `images[]`, `synopsis`, `credits[]`,
`collections[]`, `provenance[]` (which sites contributed), `seasons[].episodes[]`
(each with `best_release_id`, `quality_options[]`), `prints[]` (§3),
`availability` and `flags[]`.

Field selection is supported everywhere: `?fields=id,title,poster,available` returns
exactly those keys plus `meta`. Posters/backdrops become structured `images[]` with
`width`/`locale`/`kind` (`poster|backdrop|still|logo`) so the app picks a size instead of
guessing from a URL.

---

## 10. Cross-cutting API rules

### 10.1 Pagination
Cursor-based (`cursor` is an opaque base64 of `(sort_value, id)`), because the catalog is
constantly re-sorted by ingestion; `offset` is accepted on `/browse` for compatibility but
documented as unstable. Responses carry `next_cursor`, `total_estimate` (nullable — exact
counts on 20k+ rows are expensive), and `limit≤100`.

### 10.2 Caching
Every GET emits `ETag` + `Cache-Control`. Browse/search: `public, max-age=60`. Detail:
`private, max-age=300, stale-while-revalidate=3600`. `/play`: `no-store`. Conditional
requests must return 304 — the app polls the catalog from mobile data and must not refetch
500 KB to learn nothing changed.

### 10.3 Delta sync
`GET /api/v2/sync?scope=catalog&since=<cursor>` returns row-level upserts with a monotonic
`rev` per table, plus `deleted` ids for rows that lost their work. `scope=health` returns
only link-state changes — that is how a client keeps a usable offline cache without
re-downloading the world.

### 10.4 Errors
```json
{"error": {"code": "no_playable_source", "message": "No source for this episode can play.",
           "details": {"release_id": 555, "tried": [{"link_id": 9, "reason": "http_404"}]},
           "request_id": "req_…", "docs": "https://…/api/v2#no_playable_source"}}
```
Stable machine codes only (`adult_restricted`, `licence_required`, `bundle_expired`,
`no_playable_source`, `cursor_invalid`, `rate_limited`, `identity_suspect`, `not_found`).
Never an HTML stack trace.

### 10.5 Versioning and compatibility
Path versioning (`/api/v2`) — a client can pin; additive changes are non-breaking and
announced in `/manifest`; removing a field requires `/api/v3`. Enum values are **never
renamed**; new values are added, and clients must tolerate unknown ones (documented in
`/manifest`, and asserted by a test that the app-side model decodes a response containing
an enum value it has never seen).

### 10.6 Security (blocking before public exposure)
- API key or JWT in `Authorization` for admin/ingest/`include_adult`; anonymous read of
  browse/detail only.
- Per-IP token bucket on `/play` and `/links/*/report`; `Retry-After` + 429.
- `Access-Control-Allow-Origin` must be an explicit allow-list, not `*`.
- The resolver is a redirector: never fetch user-supplied URLs (SSRF), and reject private
  / link-local targets exactly as `link_health`'s `blocked_target` guard does.
- TLS is required before any key is issued; today's host is plain HTTP, so keys stay
  internal and the app must treat HTTP as a dev-only transport.

### 10.7 Observability
`X-Request-Id` echoed on every response; `/play` decisions logged (which rank chosen, why,
what failed) so ranking can be tuned on evidence, and `/stats` exposes the link-health mix.

---

## 11. Adult content contract (unchanged policy, now written down)

Storage keeps 100% of what we scrape, including 18+ titles, flagged `is_18_plus=1`.
Presentation must never surface it:

- `browse`, `search`, `suggest`, `collections`, `stats`, `feed.m3u` filter it out at the SQL
  level (`is_18_plus IS NULL OR is_18_plus = 0`).
- `works/{id}`, `episodes/{id}`, `releases/{id}`, `play` return `404 not_found` for a
  flagged row (404, not 403-with-body, so we never confirm an adult title exists by id).
  `play` keeps its explicit `adult_restricted` internal reason for admin/telemetry paths.
- `include_adult=true` is honoured only with admin credentials.
- Enforced by `test_database.py::AdultContentFilterTests` and `test_api_v2_scenarios.py`
  row 17; a regression here is a release blocker.

---

## 12. Projection and rollout plan

1. `catalog_v2.py` — DDL + `project(all)` : ledger → `cat_*`, idempotent (re-running with
   the same input yields byte-identical table contents), reports counters + `identity_suspect`.
2. Reuse `release_descriptor.describe()` for prints, `link_health` for evidence.
3. `viewer.py` v2 handlers read only `cat_*` (plus `cat_projection_meta.rev` for caching).
4. v1 endpoints stay frozen and untouched; nothing in v1 is deleted, so the current APK
   keeps working through the transition.
5. M3U/dashboard move onto v2 queries once v2 is green.
6. Tests, in this order: unit (descriptor/health) → contract (`/manifest` matches the
   documented enums) → scenario matrix (§6 fixtures) → **real corpus assertions against the
   merged catalog** (counts must balance: every ledger link exists in `cat_links`; no
   episode has two `best_release_id`s; every `quality_score` within the documented range).

## 13. Deliberate non-goals (v2, for now)
DRM licence serving, torrent playback, server-side transcode, accounts/profiles,
recommendation ML, subtitles authoring. The model leaves a place for each (see
`playback.drm`, `links.kind='torrent'`, `entitlements`, `cat_episode_offset`) so adding one
later is a feature, not a migration.
