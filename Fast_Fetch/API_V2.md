# Radd Stream — Catalog API v2: contract, data model, and playback guide

**Contract version:** `2.1.0` · **Layer-1 schema:** `SCHEMA_VERSION = 1` (`Fast_Fetch/catalog_v2.py`)
**Verified against code on 2026-10-22:** `catalog_v2.py`, `release_descriptor.py`,
`link_health.py`, `fast_fetch.py` (ledger DDL + `resolve_live_source`), `viewer.py` (v1 only),
`test_catalog_v2.py`, `ORACLE_DEPLOYMENT.md`.
**Consumers:** the Kotlin/Media3 Android app today; a website later. This document must be
sufficient to implement the client without asking questions.

---

## 1. How to read this document — implementation status is part of the contract

| Marker | Meaning |
|---|---|
| ✅ **Implemented** | The code produces this today, with a passing test in `test_catalog_v2.py` / `test_release_descriptor.py` / `test_link_health.py` / `test_database.py`. |
| 🛠 **In schema, not populated** | The `cat_*` column exists but the projector or health writer does not fill it yet. A v2 server may return it only if it computes the value itself. |
| 📝 **Planned** | Part of this v2 contract but **no code produces it yet**. Every planned item is also in §17 as a checkbox. Never write a client against a 📝 field as if it exists. |

**Hard truth, stated once:** Layer 0 (ledger) and Layer 1 (`cat_*` projection) are ✅
implemented. **Layer 2 — every `/api/v2` endpoint described here — is not implemented in
`viewer.py` at all today.** The live app runs on frozen v1 endpoints (`/api/v1/posts`,
`/api/v1/posts/{id}`, `/api/v1/stream`, `/api/v1/stats`). Nothing in this document may be
described elsewhere as "live"; `/api/v2/manifest` (§8) is the machine-readable status source
once built, and a client must check it, not this prose, before shipping a feature.

External models borrowed (short notes inline, sources at the end): TMDB's separation of
release events from capture medium and its external-id/multi-id identity
([TMDB release dates talk](https://www.themoviedb.org/talk/6401b9b3699fb7007d8f91c6),
[API v4 release-date types](https://github.com/leocabeza/the-movie-db/blob/master/docs/v4-api.md)),
Trakt's `season`/`episode`/`absolute_number` numbering, IMDb/Gracenote delivery-channel
categories (`flatrate`/`free`/`ads`/`purchase`) as in
[IMDb data services](https://data.imdb.com/) and Gracenote FAST metadata, HLS master-playlist
rendition semantics and Media3 track selection
([Android supported formats](https://developer.android.com/media/media3/exoplayer/supported-formats)),
RFC 9457 problem details ([rfc-editor.org/rfc/rfc9457](https://www.rfc-editor.org/rfc/rfc9457)),
the IETF RateLimit headers
([draft-ietf-httpapi-ratelimit-headers](https://datatracker.ietf.org/doc/draft-ietf-httpapi-ratelimit-headers/)),
and RFC 9110 cache validators (ETag / `Last-Modified` / `Retry-After`).

---

## 2. Why v2 exists — the v1 defects this design removes

Verified in `viewer.py` / `fast_fetch.py`:

| # | v1 behaviour | Consequence | v2 answer |
|---|---|---|---|
| 1 | `season`/`episode` are free text (`S01` vs `1` vs `Batch`) | client cannot know which episodes exist or which file covers them | structured `cat_episodes` + `cat_releases.coverage_type` ✅ |
| 2 | `?type=anime` documented but `content_type` never stores `anime` | documented filter returns nothing | `work_type` + `is_animated` facet ✅ (Layer 1), 📝 at the API |
| 3 | releases `ORDER BY id ASC`; quality is only a `CASE` over `service` inside a release | first-scraped row looks "first" to the UI | computed `quality_score`, a two-axis order (§8) |
| 4 | `resolve_live_source()` falls through to `success: true` even when no fresh URL was found | dead links look alive forever | `playability`/`state`/`rank_score` are measured properties (§7) |
| 5 | `status` written `active` at scrape and never re-checked | ranking cannot use reality | `cat_link_evidence` + `link_health.probe()` ✅ (probe), 📝 (write-back into `cat_links`) |
| 6 | no auth, no rate limit, `Access-Control-Allow-Origin: *`, binds `0.0.0.0` | anyone can hammer the resolver | §16 error/rate-limit/security contracts |
| 7 | `/api/heal` never writes a response → clients hang | unusable | removed; `POST /api/v2/links/{id}/report` replaces it 📝 |
| 8 | `is_18_plus` filtering implemented but undocumented | an app could accidentally surface it | single adult rule, §13, tested |

---

## 3. Layered architecture

```
 Layer 0  INGEST LEDGER (✅ existing, unchanged, append-only spirit)
          per-site staging DBs → merge_catalogs.py → posts / releases /
          download_sources / post_sources / sitemap_cache
          · what each site said, verbatim, zero loss
          · never read directly by clients

 Layer 1  CANONICAL CATALOG (✅ catalog_v2.py: cat_* projection)
          cat_works / cat_seasons / cat_episodes / cat_parts / cat_releases /
          cat_release_episodes / cat_links / cat_link_evidence / cat_entitlements /
          cat_review_queue / cat_work_aliases / cat_work_sites / cat_offsets /
          cat_projection_meta
          · rebuilt any time from Layer 0; the projector is idempotent within one
            ledger state (test_projection_is_idempotent_and_rebuildable ✅)

 Layer 2  API (📝 this contract; nothing implemented yet)
          browse → detail → play, with entitlements and telemetry
```

Rules:

- **The ledger is never "fixed" by hand.** Corrections happen by re-scraping or by a
  projector rule; Layer 1 is disposable and regenerated (`_reset` + full rebuild).
- **Layer 1 never loses a link.** A dead link is kept with `state='dead'|'expired'` and its
  last evidence (`test_dead_status_is_preserved` ✅).
- **Clients only see Layer 1 + 2.** No client may depend on Layer 0 column names.
- **IDs are not stable across rebuilds.** `_reset()` clears `cat_*` and the
  `sqlite_sequence`, so `cat_works.id`, `cat_releases.id`, `cat_links.id` are re-allocated on
  every projection. They are stable only while nobody re-projects. Anything a client persists
  (offline cache, favorites, WorkManager downloads) must key on `work_key` (stable string) and
  re-resolve numeric ids after a projection change (detected via `meta.versions`, §16.2).
  A stable-id projector or an id-mapping table is 📝 (§17) — this is a real gap, not a
  theoretical one (TRAKT/TMDB clients likewise key on immutable ids, not autoincrement rows).

---

## 4. Identity — how works are deduplicated

### 4.1 The implemented algorithm ✅ (`catalog_v2.work_key_for`)

For every ledger `posts` row the projector computes one `work_key` and buckets rows that
share it. The key is chosen by the first rule that applies:

1. `imdb_id` present → `imdb:tt1234567`
2. else `tmdb_id` present (non-zero) → `tmdb:123456`
3. else → `family:normalised_title:year`, where `family` is `movie` or `series`
   (`work_family()`: series-family = `series|complete_season|ongoing_season|anime|miniseries`,
   everything else movie-family) and `normalised_title` is casefolded, brackets and
   punctuation stripped (`normalize_title()`); missing year becomes the literal `ny`.

Consequences the client must know:

- **Movie and series never merge** — the family prefix forbids it (`test_movie_and_series_never_collapse_together` ✅). The 2019 movie *X* and the 2019 series *X* are two works, both keyed, both browsable with `?type=` separated.
- **Year disagreement never merges**: with no external id, year is part of the key, so one
  site saying 2019 and another 2020 produces two works. **No review row is raised today** —
  the only `cat_review_queue.kind` the projector ever writes is `season_unresolved`
  (series release with no parsable season). "year-conflict review" and
  "external-id collision blocks promotion" are 📝 (§17). The earlier claim of a
  `cat_work_external_id` provenance table is **false — no such table exists.**
- **External-id merges are silent**: if two sites tag the same wrong `tmdb_id`, the
  projector merges them. Detection rules (id used by rows with mismatched titles) are 📝.
- Aliases: every distinct scraped page title is stored in `cat_work_aliases`
  (`kind='aka'`, `source_site` set, `locale` NULL today). `original|localized|transliteration|romanized`
  kinds are 📝 — nothing writes them yet.
- Identity resolution is per-page: there is **no search for near-duplicates**; two spellings
  without an external id and with a different normalised title are two works until a human or
  an alias rule joins them.

### 4.2 Hierarchy ✅

```
work (cat_works) ──< season (cat_seasons) ──< episode (cat_episodes)
  ├──< part (cat_parts)                      📝 table exists; projector never writes it
  └──< release = print (cat_releases) ──< link (cat_links) ──< evidence (cat_link_evidence)
```

- `work_type ∈ {movie, series, anime, documentary, sport_event, music_video, unknown}` ✅.
  `tv_special` and `miniseries` are **not** produced: `_WORK_TYPE_BY_CONTENT` maps
  `complete_season|ongoing_season → series`, and `anime` is assigned when `is_animated=1` and
  the base type is `series|unknown` (`work_type_for` ✅). Clients must tolerate unknown enum
  values (§16.6).
- `is_animated` is a separate boolean on `cat_works` — the `animated=true` facet works for
  any `work_type`.
- `season.number` is an integer ✅. `season_type` exists; only `'regular'` is ever written ✅.
  `special`/`extra` seasons are 📝.
- `episode.number` (within season) and `absolute_number` (show-wide, computed by
  `ROW_NUMBER() OVER (PARTITION BY work ORDER BY season, number)` in `_finalize` ✅, Trakt-style).
  `episode.title`, `air_date`, `runtime_minutes`: 🛠 columns exist, never populated.

### 4.3 Coverage — the pack problem ✅

Every `cat_releases` row declares `coverage_type ∈ {whole_work, season_pack, episode_range,
single_episode}` — **there is no `parts` coverage value** (the old table claimed one; the
projector's `_release_coverage()` never emits it). Materialised facts:

- `single_episode` / `episode_range` create `cat_episodes` rows + `cat_release_episodes`
  mapping rows ✅, capped at `MAX_ENUMERATED_EPISODES = 120` per range — a 1000-episode batch
  label stays described (`coverage_type` + `episode_range` text) without fabricating rows
  (`test_giant_batch_range_does_not_fabricate_thousands_of_episodes` ✅).
- `season_pack` and `whole_work` **enumerate zero episodes** (`_covered_episodes` returns
  `[]`). So a season that exists *only* as one packed file currently has **no episode rows at
  all** — see the worked example S2 and gap G-2 (§18). This is the single most important
  limitation of Layer 1 for the app.
- `cat_episodes.best_release_id` is set only from releases with
  `coverage_type IN ('single_episode','episode_range')` **and** `streamable_count > 0`,
  ordered `quality_score DESC, id ASC` ✅ (`test_best_release_is_chosen_from_streamable_prints_only`).
  It is never a season-pack release. For pack-only coverage the client must use the season
  listing (§14 `/seasons/{n}`) and pick the pack release explicitly.
- Pack offsets: `cat_release_episodes.offset_seconds` and `chapter_title` are re-applied from
  the durable `cat_offsets` ledger on every rebuild ✅ (`record_offset`,
  keyed by `(work_key, season_number, episode_number, release_label)` — stable identity, not
  numeric ids, precisely because ids churn). `confirmed_by` is a monotonic counter; **the last
  write wins** — there is no majority vote yet 📝.

---

## 5. Prints — the print axis (what the picture *is*)

A `cat_releases` row is one print. Produced by `release_descriptor.describe()` ✅. These are
the **exact enums the code can emit** — anything else never appears:

| Column | Complete value set (code truth) | Notes |
|---|---|---|
| `resolution` | `2160p, 1080p, 720p, 480p, 480p_or_lower, unknown` | `480p_or_lower` (360p/240p/144p) and `unknown` are real values the old table omitted. Default in DB: `unknown`. |
| `source_tag` | `uhd_bluray, bluray, web_dl, webrip, hdtv, dvdrip, telesync, telecine, ppv, cam, unknown` | `uhd_bluray` only when a `bluray` match meets 2160p. **`hdtc` is not a tag yet**: an HDTC label today lands on `unknown` (weight 60) and even counts as `official_print` (known resolution + unknown source) — documented inaccuracy, planned fix (§17). |
| `codec` | `h265, h264, av1, xvid, mpeg2, unknown` | |
| `hdr` | JSON array, any of `dolby_vision, hdr10_plus, hdr10, hlg` (empty = SDR) | order = best first |
| `bit_depth` | int `0|8|10|12` (0 = unstated) | |
| `container` | `mkv, mp4, avi, mov, ts, m4a, unknown` | |
| `edition` | `director_cut, extended, imax, unrated, remastered, restored, uncut, fan_edit, theatrical, unknown` | |
| `print_version` | int `0..999` | REPACK/`v2` capture: `version` from the label ✅ (`test_repack_version_is_per_print_not_per_work`) |
| `release_group` | string, **always `''`** 🛠 | the descriptor does not extract group names; stop describing `group` as a feature |
| `size_bytes` / `size_per_episode_bytes` | ints, `0` = unknown | `2.24 GB/E` → per-episode, total stays 0 (Decimal-exact) ✅ |
| `audio_languages` / `audio_channels` / `audio_codecs` | JSON arrays + single layout string `5.1|2.0|unknown` ✅ | layout is per *release*, not per track — see gap G-1 (§18); `7.1` is folded into `5.1` deliberately |
| `dual_audio` | 0/1 ✅ | true when ≥2 languages or label says dual/multi audio |
| `subtitle_mode` | `hardcoded | external | none` ✅ | `ESubs` → external; `Hsubs`/burned → hardcoded. **No subtitle URLs** exist anywhere — gap G-1 |
| `watermarked`, `official_print` | 0/1 ✅ | watermark markers list incl. `i60x, etlb, etleb, psa, hdhub4u wm`; `official_print` false when watermarked or `fan_edit` |
| `flags` | JSON array `watermarked|unofficial|pack|alternate_edition` ✅ | |
| `quality_score` | int 0..1000, formula below ✅ | |
| `descriptor_json` | the full `describe()` dict ✅ | the API may expose parsed fields without reparsing |

### 5.1 The exact print-quality formula ✅ (`combined_quality_score`, clamped 0..1000)

```
score =  W_res(resolution)        2160p=400  1080p=300  720p=200  480p=120  480p_or_lower=100  unknown=50
       + W_src(source_tag)        uhd_bluray=300 bluray=280 web_dl=240 webrip=220 hdtv=180
                                   dvdrip=150 telesync=80 telecine=70 ppv=20 cam=20 unknown=60
       + 60  if hdr ∩ {dolby_vision,hdr10,hdr10_plus} and resolution ∈ {1080p,2160p}
       + 30  if bit_depth==12   |   + 20 if bit_depth==10
       + 30  if codec ∈ {h265, av1}
       + 40  if official_print
       + 20  if subtitles.external | + 5 if hardcoded only
       + 25  if dual_audio   + 15 if channel_layout == 5.1
       + 15  if edition ∈ {director_cut, extended, remastered, restored}
       − 60  if watermarked
cam family (cam/telesync/telecine) totals are capped at 250; final clamp 0..1000.
```

The `unknown` resolution weight (50) sits **below** every known rung on purpose: a known 480p
is safer than an unknowable print. The theoretical best print (2160p UHD BluRay DV 12-bit AV1
official ESubs dual 5.1 Director's Cut) scores **935**; 1000 is defensive headroom only.
Worked comparisons the app can rely on:

| Label | Structured outcome | Score |
|---|---|---|
| `2160p UHD BluRay x265 DDP5.1 DV` | 2160p/uhd_bluray/h265/dolby_vision/official | 400+300+60+30+40 = **830** (+audio bonuses) |
| `1080p WEB-DL x265 Hindi English ESubs` | 1080p/web_dl/h265/official/dual/ext | 300+240+30+40+20+25 = **655** |
| `1080p HDTC x265` | 1080p/**unknown**/h265/official(!) | 300+60+30+40 = **430** — too generous today, see `hdtc` gap G-4 |
| `720p WEBRip` | 720p/webrip/official | 200+220+40 = **460** |
| `1080p CAM` | 1080p/cam → capped | min(1080p+cam+official, 250) = **250** |
| `480p` no other info | 480p/unknown/official | 120+60+40 = **220** |

### 5.2 Ordering the UI shows (print axis)

Implemented today (`_finalize`, `idx_cat_releases_work`): `quality_score DESC, id ASC` —
note `id ASC` means the **earlier-projected** row wins ties, i.e. "fresher repack wins" is
**not** what runs; repack v1/v2 with identical descriptors tie on score and v1 (lower id)
sorts first ✅-documented-as-is. The previously claimed tiebreak chain
(`official_print desc → link health → site trust → first_seen_at desc`) is 📝; only the
first element is achievable with data that exists. Ordering rules that *do* hold structurally:

- A CAM can never outrank a distribution print (250 cap vs 460 floor for a bare 720p WEBRip).
- Editions are separate prints, never "qualities" of one another: the API exposes `prints[]`
  keyed by print, each with its own links; `alternate_edition` flag labels them.
- Watermarked/fan prints are kept and flagged, never silently dropped (Zero Data Loss rule).

---

## 6. Links — the link axis (how well *this access path* works)

```
cat_links(id, release_id, work_id, source_site, service, source_name, kind, url, final_url,
          resource_id, playability, state, resumable, accepts_ranges, cors_open, ephemeral,
          expires_at, protocol, content_type, size_bytes, latency_ms, speed_mbps, http_status,
          last_evidence_at, rank_score, tier)
cat_link_evidence(id, link_id, probed_at, ok, protocol, http_status, content_type, size_bytes,
          latency_ms, speed_mbps, accepts_ranges, error)
```
`source_site`, `service`, `source_name`, `url`, `final_url`, `resource_id` are **ledger-side
columns** — Layer 1 keeps them in full (zero data loss, §16.9) and no public response is
allowed to repeat them. Everything a client is handed about a link is in §8.1.

### 6.1 `kind` and `playability` — exact outputs of `classify_link()` ✅

`kind` is *what the URL is*; `playability` is *what a client can do with it right now, from
static structure*. The old table's enum was wrong in three places: `resolve_required` is a
real playability, `dead_end` is a real kind, and `torrent` is **not** a kind (magnet/torrent
URLs classify as `download_only`).

| kind | playability | when | example family |
|---|---|---|---|
| `hls_manifest` | `stream` | URL has `.m3u8/.mpd/mpegurl/playlist/hls` marker | toonworld hubcloud video, fzcdn |
| `cdn_direct` | `stream` (`both` if ledger `playback_type='download'`) | file extension or file-host marker (`.mp4/.mkv/…`, `cloudflarestorage`, `r2.dev`, `…/direct/`, …) and not an embed service | google_cdn, fsl_r2, hubcloud_10g, pixeldrain |
| `download_only` | `download` | archive markers (`.zip/.rar/…`) or service in the download-only file-host list (mega, 1fichier, mediafire, …) **or `magnet:`/`torrent:`** | mega, 1fichier, torrent files |
| `bridge` | `none` | service in bridge list (linkrit, gpdl, linkvertise, …) or URL has `/redirect`, `/get/`, `/token/`, `?id=` | linkrit, tw4all redirect |
| `embed` | `webview` | embed service list or `embed*.host` / `/e/` URL shape | dropgalaxy-style iframes, vidsrc |
| `cloud_page` | `resolve_required` (if `is_temporary`) else `download` | drive/page URL shape (`.html`, `.php`, `/drive/`, contains "drive") or fallback for unknown URL types | gdtot, pixeldrain page, hubcloud page |
| `dead_end` | `none` | empty target URL — recorded, counted as `unattributed`, never dropped (`test_empty_target_is_recorded_not_dropped` ✅) | — |

An `embed`-service URL that *looks like a file* stays `embed/webview` — the service list wins
over the shape. `protocol` column ✅: `hls` | `progressive` | `html` (embed/cloud_page/bridge) |
`unknown`.

### 6.2 `state`, `tier`, and the unpopulated columns

- `state` ✅ is copied from the ledger `download_sources.status`, whose only written values are
  **`active`, `dead`, `expired`** (`expired` = 401/403 token rot, `dead` = 4xx/5xx/timeout;
  see `fast_fetch.py:4367,4381`). `unknown`/`unchecked` appear in the rank formula as future
  values but nothing writes them yet. Default column value: `active`.
- `tier` ✅ `1` for the trusted fast direct hosts (pixeldrain, vegadrive, hubcloud_10g,
  fsl_r2, google_cdn, fastdl, hubcdn), else `2`. (`score_link` accepts tier `3`; the
  projector never assigns it.)
- 🛠 **Never populated by the projector:** `resumable`, `accepts_ranges`, `cors_open`,
  `latency_ms`, `speed_mbps`, `content_type`, `last_evidence_at`, `expires_at`. `size_bytes`
  and `http_status` are copied from the ledger when the scraper recorded them.
  **No code today writes probe results back into `cat_links`** — probing
  (`link_health.probe` ✅) updates the *ledger* (`download_sources`) via
  `fast_fetch.run_health_check`, and `cat_links` is refreshed only when the whole projection
  re-runs. A v2 server must therefore treat `rank_score` as a *structural prior*, not fresh
  measurement (see §8.3 and HANDOFF item).

### 6.3 The exact link-score formulas ✅

**Projection-time `cat_links.rank_score`** (static prior, range 0..900):

```
rank_score = base(playability)      stream|both = 500 | download = 250 | resolve_required = 120
                                     webview = 80    | none|other = 0
             + 150 if tier == 1
             + 100 if ephemeral == 0                 (structural only — is_temporary is copied ✅;
                                                      actual TTL/expiry is NOT computed here)
             + 50  if accepts_ranges == 1            (column always 0 at projection → never fires)
             + 100 if state == 'active' | 0 if 'unknown'/'unchecked' | −450 if 'dead'/'expired'
```

**Post-probe `link_health.score_link`** (0..1000, practical ceiling 930) — applies only when a
`ProbeResult` exists (`ok=False` ⇒ score 0, i.e. a measured-dead link can never outrank a
live one):

```
if not ok: 0
+ 300 streamable          (protocol ∈ {hls, dash, progressive} and evidence of bytes)
+ 150 downloadable
+ 100 accepts_ranges      + 80 cors_open
+ 100 × min(speed_mbps, 20) / 20        (20 Mbps saturates any handset)
+ 100 × clamp((3000 − latency_ms) / 2850) (full ≤150 ms, zero ≥3000 ms)
+ 100 × tier_weight       (tier1 1.0, tier2 0.7, tier3 0.4)
− 150 if is_temporary     − 100 if protocol == 'embed'
```

Rolling history uses `merge_health_history` (EWMA, newest sample weight 0.4; latency/speed
blended only when actually measured) ✅ — one failed check decays `success_ema` to 0.6, two to
0.36. Probe error codes are stable strings safe to GROUP BY: `timeout, dns, tls, conn_reset,
conn_error, http_404…, empty_body, not_media, redirect_loop, redirect_limit, blocked_target,
invalid_url, head_unsupported, blocklisted`.

---

## 7. The two-axis quality model — the core of `/manifest`

**Print quality and link quality are orthogonal axes and conflating them is a bug.**

| | PRINT axis | LINK axis |
|---|---|---|
| Question | *What is the picture?* (resolution × capture source × HDR/codec/edition) | *How well does this access path work?* (playability, measured throughput, latency, freshness, state) |
| Producer | `release_descriptor.quality_score` (§5.1) | `cat_links.rank_score` (§6.3) and `score_link` once probes land |
| Scale | 0..1000 (cam ≤ 250; best describable print 935) | static prior 0..900; post-probe 0..1000 (ceiling 930) |
| Lives on | `cat_releases.quality_score` (one value per print) | `cat_links` (one value per link; links of one print can span the whole scale) |
| Mutable by | re-scrape of the label only | probing, time (token expiry), health history — *without* touching print quality |

Why separation matters, in one failure each:

- **Conflation bug A (link masquerading as print):** a 1080p BluRay print whose every link
  404s is still a 1080p BluRay print. Sorting by a single "quality" number would either hide
  the work's best print forever or, worse, promise the user "4K" for what is actually a
  working 480p file from another print.
- **Conflation bug B (print masquerading as link):** the worst-case real example in this
  corpus — a 2160p WEB-DL on a bridge (`rank_score` structural ≈ 0–120) versus a 480p CDN
  direct (≈ 750). "Best first" must be interpretable: *best print* or *best playable path*.

### 7.1 The API contract for both axes ✅-derivable from Layer 1

1. Every print object carries `print.quality_score` (axis 1). Every candidate link carries
   `link.score` (axis 2) and the evidence it is based on (`speed_mbps`, `latency_ms`,
   `state`, `last_evidence_at`; `null` where unmeasured — never fake a measurement).
2. `POST /play` accepts `prefer ∈ {quality, speed, data_saver}` (see §9) and orders the
   failover ladder accordingly.
3. `GET /browse` accepts `min_quality` filtering on **axis 1** (work's `best_quality_score`,
   i.e. print axis — availability on axis 2 is the separate `available` facet from
   `available_stream`/`available_download` rollups ✅).
4. `/api/v2/manifest` must return both formulas **as data**, not prose:

```json
{"contract_version": "2.1.0",
 "scoring": {
   "print": {"field": "print.quality_score", "range": [0, 1000], "cam_ceiling": 250,
             "weights": {"resolution": {"2160p": 400, "1080p": 300, "720p": 200, "480p": 120,
                                          "480p_or_lower": 100, "unknown": 50},
                          "source_tag": {"uhd_bluray": 300, "bluray": 280, "web_dl": 240,
                                          "webrip": 220, "hdtv": 180, "dvdrip": 150,
                                          "telesync": 80, "telecine": 70, "ppv": 20, "cam": 20,
                                          "unknown": 60},
                          "bonuses": {"hdr_at_1080p_plus": 60, "bit_depth_12": 30, "bit_depth_10": 20,
                                       "codec_h265_av1": 30, "official_print": 40,
                                       "subs_external": 20, "subs_hardcoded": 5, "dual_audio": 25,
                                       "layout_5_1": 15, "edition_bonus": 15, "watermarked": -60}},
   "link":  {"field": "renditions[].playback.score", "scales":
              {"projection_prior": {"range": [0, 900], "formula": "see §6.3 rank_score"},
               "measured": {"range": [0, 1000], "formula": "see §6.3 score_link",
                             "requires": "cat_link_evidence present"}},
             "which_one_is_served": "measured when last_evidence_at is newer than the projection, else prior"}},
 "enums": { "…complete value sets from §4–§6, versioned with the contract…": "…" },
 "implemented": {"layer1": true, "layer2": false, "schema_version": 1}}
```

A client that caches the catalog offline can then re-rank locally on either axis and get
exactly what the server would (TMDB exposes analogous per-certification/genre dictionaries so
clients render without re-deriving; RFC 9457 + manifest-driven enums also mean the app needs
no code release to learn a new enum).

---

## 8. Playback contract — what the Android app does

`POST /api/v2/play` returns a **PlayBundle** (§8.1). Every field below is tagged:
*(cat: column)* = readable from Layer 1 today; *(resolve)* = computed by the JIT resolver at
bundle time; *(derived)* = computable from the request/URL; *(planned)* = §17.

### 8.1 PlayBundle shape (annotated)

```jsonc
{
  "meta": {"contract_version": "2.1.0",
           "versions": {"catalog": 148, "health": 9213},        // planned (§16.2)
           "request_id": "req_…"},                               // derived
  "session": {"id": "pb_…", "issued_at": 1730000000, "expires_in": 900,
              "strategy": "failover", "rotate_on": "next_playback_session"}, // planned
  "target": {"kind": "episode", "work_id": 1234, "work_key": "imdb:tt0987654", // cat: works
             "season": 7, "episode": 3, "episode_id": 98765},    // cat: episodes
  "renditions": [
    { "rank": 1,
      "release_id": 555,                                          // cat: releases
      "print": { "label": "1080p WEB-DL · H.265 · Hindi 5.1 + English · ESubs",
                 "resolution": "1080p", "source_tag": "web_dl", "codec": "h265",
                 "hdr": [], "edition": "theatrical", "print_version": 0,
                 "quality_score": 670,                             // PRINT axis, cat: releases ✅
                 "size_bytes": 2405181686, "watermarked": false, "official_print": true,
                 "flags": [] },
      "playback": {
        "stream_id": "kQ3qTz…",                                    // opaque handle (§16.9) — the client never learns the host
        "label": "Fast direct",                                     // derived: the only server word a user is ever shown
        "scheme": "http",                                          // derived from url
        "requires_https": false,                                   // planned (§8.3)
        "protocol": "hls", "container": "m3u8",                    // cat: links.protocol ✅
        "mime_type": "application/vnd.apple.mpegurl",               // cat_evidence or derived
        "kind": "hls_manifest", "playability": "stream",            // cat: links ✅
        "requires_resolve": false,                                  // derived: playability=='resolve_required'
        "http_headers": {},                                          // planned: resolver presets (Referer/UA)
        "seekable": true, "accepts_ranges": true,                    // evidence-based; null until probed 🛠
        "resumable": false,                                          // 🛠 (only ledger writes it today)
        "cors_open": false,                                          // 🛠 — only matters for webview/web, see §8.4
        "ephemeral": true, "expires_at": 1730000900,                 // ephemeral ✅ cat: links; expires_at planned (§8.3)
        "score": 830, "score_scale": "measured",                     // LINK axis (§6.3) — planned write-back
        "drm": null },                                               // always null today (§19)
      "tracks": { "audio": [{"lang": "hi", "default": true, "channels": "5.1", "codec": "eac3"}],
                  "subtitles": [] },                                 // PLANNED — gap G-1: no per-track rows exist
      "coverage": {"type": "single_episode", "ordinal": 3, "offset_seconds": null,
                   "needs_offset_calibration": false}                 // cat: release_episodes ✅
    },
    { "rank": 2,
      "print": {"resolution": "480p", "quality_score": 220, "…": "…"},
      "playback": {"protocol": "progressive", "container": "mp4", "requires_resolve": true,
                   "stream_id": "b7Tz…", "resolve_url": "/api/v2/resolve/b7Tz…", // planned (§8.2) — a handle, never a row id (§16.9)
                   "playability": "resolve_required", "score": 120, "…": "…"},
      "coverage": {"type": "season_pack", "ordinal": 3, "offset_seconds": 4920,
                   "pack_warning": "This file contains all of Season 7"} // cat: offsets ✅ when learned
    }
  ],
  "download_options": [ { "release_id": 555, "stream_id": "kQ3q…", "kind": "download_only",
      "resumable": true, "size_bytes": 2405181686, "score": 250, "expires_at": null } ],
  "entitlement": {"model": "free", "display_priority": 10},          // §11; model free always today ✅
  "failure_policy": {"retry_same": 1, "then_next_rank": true, "max_ranks": 3,
                     "report_url": "/api/v2/links/555/report", "backoff_ms": 800 } // planned
}
```

### 8.2 Links that need a resolver round-trip

`playability: resolve_required` (kind `cloud_page`, temporary) means: **the bundle URL is not
the media URL.** The client must:

1. `GET` the `resolve_url` (`/api/v2/resolve/{link_id}`, no-store) **at the moment playback
   starts**, never at list time.
2. Receive `{url, http_headers, expires_at, scheme}` — the JIT unwrap (the v1 engine already
   does the unwraps: hubcloud, direct-cloud, greenmotors, vcloud, fastdl, pixeldrain,
   vegadrive in `resolve_live_source` ✅).
3. Hand `url` + headers to Media3 (`DataSource.Factory` with the Referer/UA headers).
4. If the resolver reports failure, treat the *rank* as dead: report via
   `POST /links/{id}/report` and fail over. **v2 must not copy v1's
   `success: true` fall-through** (defect #4): no fresh URL ⇒ problem `no_playable_source`
   (409) or per-rank `failed` status, never a 302 to a rotting token.

### 8.3 HTTPS handling and the HTTP-only host — normative

The Oracle host serves **plain HTTP only** (`http://92.4.95.252/`, nginx :80 → 127.0.0.1:8080;
no TLS anywhere — `ORACLE_DEPLOYMENT.md`, and `viewer.py` has no TLS support). Rules:

- `playback.scheme` states the media URL's scheme. `playback.requires_https: true` (planned
  field, derived by the server from link presets/redirect observation) means *this link breaks
  over cleartext* (e.g. the CDN 302s http→https and strips tokens on the way). Clients must
  then **skip the candidate when they cannot do https and must never try to downgrade it**.
- Conversely, `scheme:"http"` + `requires_https:false` = the link *only* works cleartext.
  A **release** Android build cannot legally use it: Media3/OkHttp on release builds blocks
  cleartext unless a *per-domain* `network_security_config` exception exists. Global
  `cleartextTrafficPermitted=true` is forbidden (App/AGENTS.md §11). On today's HTTP-only host
  that leaves exactly two honest options for a release build: point at a TLS-terminated host
  (deployment gap), or ship debug builds only. The app must surface this as a distinct state
  (`insecure_host` banner), not silently fail playback.
- Because transport is cleartext: **no Authorization header, no device token, no account
  concept may be sent to this host** (root AGENTS.md + §16.7). All admin/keyed surfaces stay
  internal until TLS exists. Entitlement gating (§11) is therefore *honor-system* on HTTP —
  documented, not hidden: paid models must not go live on this host.
- Session/token hygiene on ephemeral links: bundle URLs must never be logged by the client
  (they carry CDN tokens in query strings) and never persisted past `expires_at`.

### 8.4 Ephemeral links expiring between listing and playback

`is_temporary`/`ephemeral` is structural and accurate ✅, but **Layer 1 has no real
`expires_at`**: TTLs are unknown until resolution time (the v1 engine only knows "older than
6 h ⇒ re-heal", `heal_expiring_sources`). Client recovery algorithm (normative):

1. Never cache a PlayBundle or a resolved media URL beyond `session.expires_in` (design: 900 s;
   conservative because token TTL is unmeasured).
2. On a media error where `playback.ephemeral == true` (403/404/410 from the CDN, ExoPlayer
   `IOException` on `hls_manifest` load), do not blind-retry the same URL more than
   `failure_policy.retry_same` times.
3. Call `POST /play` again with the same target — the server re-resolves; it answers
   `bundle_expired` (410, see §16.4) only when the client presents an expired `session.id`
   for a resumable continuation. A fresh bundle is **not** an error condition for the user;
   the app re-binds the MediaSource transparently.
4. If re-resolution fails on every rank ⇒ surface `no_playable_source` with the per-rank
   reasons and offer downloads/webview candidates if any.

### 8.5 Media3 mapping (what the player must actually do)

- `protocol:"hls"` → `MediaItem.fromUri(url)` (ExoPlayer's HLS support handles master/media
  playlists, `EXT-X-MEDIA` audio/subtitle renditions, WebVTT/caption formats — see Android
  "Supported formats"). The app **must not** pre-parse `.m3u8` itself; rendition selection
  happens in `DefaultTrackSelector` with the user's preferred audio language, and `data_saver`
  sets `maxVideoHeight`/`maxVideoBitrate` constraints.
- `protocol:"progressive"` → single `MediaItem`; `accepts_ranges:false` ⇒ disable seeking in
  the UI rather than let ExoPlayer stall (this is the honest use of that evidence flag).
- `playability:"webview"` → Android `WebView` activity with the `embed` URL; never
  hand these to ExoPlayer. This is a *separate presentation mode*, never a silent fallback
  (§2 defect #14).
- `cors_open` is a **browser/WebView-only** property. Native OkHttp/ExoPlayer is not subject
  to CORS; the previous text implying Media3 fetches get "blocked by CORS" was false. The
  flag matters for the future website and for WebView-loaded embeds only.
- Offline: only `download_options[]` with `resumable == true` are offered to
  DownloadManager/WorkManager with Range resume.
- Failover: try rank 1, one retry, then rank 2, rank 3, stop at `max_ranks`; report each
  outcome to `POST /links/{id}/report` (`event ∈ played|stalled|failed|resolved`).

---

## 9. `/play` ordering per `prefer` — the two axes in action

```
prefer=quality    : order prints by print.quality_score DESC (§5.1 — "best print"),
                    inside a print order links by link score DESC.
                    Ladder = best picture that is currently reachable, picture-first.
prefer=speed      : rank candidates across ALL prints by link score DESC
                    (streamable ≫ measured speed ≫ latency ≫ freshness — §6.3).
                    The first rank may be a 480p stream: the user asked for *fastest working*,
                    and print quality is displayed but not used for ordering.
prefer=data_saver : filter prints by device.max_height (e.g. ≤480p), then behave like
                    speed; when nothing matches the cap, offer the smallest
                    size_per_episode_bytes print marked "exceeds data saver limit".
device={hdr,hevc,max_height,network} : hard filters — a device that cannot decode h265 never
                    gets an h265 rank even under prefer=quality.
```

The PlayBundle must always include both numbers on every rank (`print.quality_score` and
`playback.score`) so the UI can say *"720p WEBRip — fastest"* vs *"4K BluRay — best picture"*.
That label choice **is** the two-axis contract visible to the user.

---

## 10. Scenarios — worked request/response examples

The old 20-row scenario matrix is retired from this document: its assertions now live where
they are provable — `test_catalog_v2.py` ✅ for Layer 1 and the planned
`test_api_v2_scenarios.py` 📝 for Layer 2. Two matrix rows were factually wrong and are
corrected here once: adult targets answer **404** (never 403 — §13), and an exhausted
failover ladder answers 409 `no_playable_source` while **download-only is a 200 with an empty
ladder** (S11). Below, the twelve scenarios the owner demanded, each with what Layer 1 really
contains and what Layer 2 must return. Example bodies are trimmed to the teaching fields.

### S1 — Season delivered as one file per episode
Ledger: releases `S07 E01 … E08`, one per page line.
Layer 1 ✅: 8 `cat_releases` rows `coverage_type='single_episode'` (season 7), 8
`cat_episodes`, each `best_release_id` from a streamable print.
```jsonc
// GET /api/v2/works/1234/seasons/7
{"season": {"number": 7, "episode_count": 8, "coverage": "per_episode"},
 "episodes": [{"number": 1, "absolute_number": 50, "best_release_id": 551,
               "quality_options": ["1080p", "720p", "480p"]}, ...]}
```

### S2 — One file for the whole season (pack only)
Ledger: one release `S07 Complete [Batch] 720p`.
Layer 1 **today** ✅ (and this is a limitation, not a feature): one `cat_releases` row
`coverage_type='season_pack'`, **zero `cat_episodes` rows** (`_covered_episodes` returns `[]`
for packs — gap G-2). `best_release_id` on episodes cannot exist.
The API must therefore answer per-episode requests *through the season*:
```jsonc
// GET /api/v2/works/1234/seasons/7
{"season": {"number": 7, "episode_count": 0, "coverage": "season_pack_only",
            "known_episode_span": null},
 "pack_releases": [{"release_id": 560, "label": "S07 Complete [Batch] 720p",
   "quality_score": 460, "offsets_learned": 3}]}
// POST /api/v2/play {"work_id":1234,"season":7,"episode":3,"prefer":"quality"}
→ the server resolves episode 3 against release 560: if a cat_offsets row exists for
  (work_key, 7, 3) → one rank with offset_seconds from cat_offsets ✅;
  if not → the rank carries needs_offset_calibration:true and the pack_warning; playback
  starts at file position 0 (or the client's remembered position) and the app offers the
  "set episode start" UI whose submit goes to POST /api/v2/episodes/{id}/offset.
```
Client rule: a season with `coverage='season_pack_only'` shows a file-per-season card, never
a fake episode grid. (TMDB models each episode as its own release event with `air_date`;
Trakt likewise needs `absolute_number`. Since neither exists here, the honest card is the
pack. Synthesising episode rows from `episode_count` hints is 📝 §17.)

### S3 — Episodes split across batches on one page (`EP(01-06)` + `EP(07-12)`)
Two `cat_releases` rows, `coverage_type='episode_range'`, `episode_range='1-6'` and `'7-12'`;
12 episode rows, each appearing in exactly one range per print
(`test_episode_range_expands_within_the_cap` ✅). `/play` for ep 9: candidate ladder built from
the range-2 print only, offset from `cat_offsets` when learned.

### S4 — Movie released in Part 1 / Part 2
Schema intent: `cat_parts` + `coverage_type` referencing parts. **Code today:** `cat_parts`
is never written (gap G-3); two-part releases land as two `whole_work` releases of the same
work, distinguished only by `label`/`title_stub` ("Part 1"/"Part 2"). A naive `/play` would
offer *either* as covering the whole work — wrong for parts.
Interim contract (what v2 must do with today's data): if a work has >1 `whole_work` release
whose labels carry a part pattern, the API marks each `{"coverage":{"type":"whole_work","part_stub":"Part 1"}}`
(📝 `part_stub` is an API-computed extension field, not a DB column) and the UI lists them as
ordered cards; `/play` for "the movie" must return the *requested part* only. Full `cat_parts`
population + a real `parts` coverage scope are 📝.
```jsonc
// GET /api/v2/works/777  (Baahubali-style, two ledger releases today)
{"id":777,"title":"Two Crowns","work_type":"movie",
 "parts":[{"ordinal":1,"label":"Part 1","release_ids":[901]},{"ordinal":2,"label":"Part 2","release_ids":[902]}]}
// "parts" here is Layer-2 heuristic output, not cat_parts data (cat_parts is empty today).
```

### S5 — Multiple seasons, only some complete
Per-season `episode_count` from `cat_seasons` ✅ (rollup `test_multi_season_series_keeps_seasons_apart`).
"S12 complete" cannot be verified without an expected-episode source (no TMDB episode-count
ingestion exists) — the client must show *known* episodes, not completeness. `complete:
null` (unknown) is the honest field; a real completion signal is 📝.

### S6 — Many prints of one title (HDTC, WEB-DL, BluRay, 4K HDR, REPACK v1/v2, cleaned)
```jsonc
// GET /api/v2/works/1234 prints[] — ordered by quality_score DESC (print axis)
[{"release_id":70,"label":"2160p BluRay x265 DV","resolution":"2160p","source_tag":"uhd_bluray",
  "hdr":["dolby_vision"],"print_version":0,"official_print":true,"quality_score":830},
 {"release_id":71,"label":"1080p WEB-DL x265 ESubs","resolution":"1080p","source_tag":"web_dl",
  "codec":"h265","print_version":0,"quality_score":655},
 {"release_id":72,"label":"1080p WEB-DL x265 ESubs REPACK v2","print_version":2,
  "quality_score":655},   // ties with 71; current order = id ASC ⇒ v1 listed first (§5.2)
 {"release_id":73,"label":"1080p HDTC x265","resolution":"1080p","source_tag":"unknown",
  "official_print":true,"quality_score":430},  // flags is [] here — the mislabel is in source_tag itself, not a flag (G-4)
 {"release_id":74,"label":"720p WEBRip","quality_score":460},
 {"release_id":75,"label":"480p","quality_score":220},
 {"release_id":76,"label":"1080p CAM i60x","source_tag":"cam","watermarked":true,
  "quality_score":250,"flags":["watermarked","unofficial"]}] // 320−60=260 → cam cap 250
```
The "cleaned official copy" case: an otherwise-identical print without watermark scores +60
relative to the watermarked one and drops the `watermarked` flag ✅ — they remain two prints;
dedup never merges them (different labels ⇒ different `pkey`).

### S7 — One episode reachable from several sites
Provenance is first-class **in the ledger and on the operator port** ✅: `cat_work_sites`
(which page/site contributed), `cat_releases.source_site`, `cat_links.source_site/service`.
Two sites publishing the *same print* (identical `pkey` incl. site+origin_url ⇒ different rows
because `rel_site` is part of the key; identical text from the *same* site/URL collapses —
`release_dups` counter ✅). `/play` mixes sites freely in the ladder because ordering is by
scores, not by site — and the client cannot tell that it did, because the ladder it receives
names nobody (§16.9):
```jsonc
// what the operator port sees            // what every public client sees
{"rank":1,"release_id":555,               {"rank":1,"release_id":555,
 "playback":{"score":830,                  "playback":{"score":830,"label":"Fast direct",
   "source_site":"multimovies",              "stream_id":"kQ3q…","kind":"cdn_direct",
   "service":"fsl_r2"}},                     "protocol":"hls","latency_ms":140}},
{"rank":2,"release_id":611,               {"rank":2,"release_id":611,
 "playback":{"score":760,                  "playback":{"score":760,"label":"Standard",
   "source_site":"hdhub4u",                  "stream_id":"b7Tz…","ephemeral":true}}}
   "service":"hubcloud_10g"}}              // detail payload has no "sites" member at all
// "sites":[{"site":"multimovies","page_url":"…"},…]  ← operator port only
```

### S8 — Link that needs a resolver round-trip — see §8.2 (worked flow there).

### S9 — Ephemeral link expired between listing and playback — see §8.4 (recovery there).
Matrix row 15 corrected: the client never distinguishes "expired" from "unreachable" by
status games; it re-calls `/play`, which is idempotent within its validity window (identical
target within a valid session must reuse the bundle — a design invariant, 📝 tested) and
re-resolves outside it.

### S10 — Slow-internet client / low-bitrate fallback
```jsonc
// POST /api/v2/play
{"episode_id":98765,"prefer":"data_saver",
 "device":{"max_height":480,"hevc":true,"hdr":false,"network":"cellular"}}
→ ranks: 480p cdn_direct with measured speed_mbps ≥ 3 first;
  a 480p hls_manifest whose *media* bitrate is unmeasured ranks below it
  (no evidence ⇒ projection prior only);
  nothing ≤480p streamable ⇒ smallest non-conforming print offered with
  "exceeds_data_saver_cap": true + download_options as the offline path.
```
`/play` must never demote to webview silently to save bandwidth — webview is a presentation
mode, not a bitrate.

### S11 — Download-only title
All links `kind=download_only`/`playability=download` ✅ (file hosts, torrents/magnets
included — §6.1). `available_stream=false, available_download=true` rollups ✅.
`/play` ⇒ `renditions: []` + populated `download_options`; a *download* is not a 409 — the
distinction stands (assertion in the planned `test_api_v2_scenarios.py`): **409 `no_playable_source` only when neither stream nor
download is possible**; download-only is a success response with an empty ladder. The app
renders a "Save offline" card.

### S12 — Adult content — see §13 (single rule, 404 identical payload).

### S13 — Title whose identity is under review
`cat_works.identity_suspect` ✅ (set when an open `cat_review_queue` row exists — `_finalize`).
This is **not** an error: browse/search/detail serve the work with
`"flags":["identity_suspect"]` (it's a data-confidence marker, not an adult marker; no count
skew rule applies). **Code truth:** there is no per-release suspect flag — `cat_releases` has
no `identity_suspect` column and `_finalize` does *not* exclude suspect prints from
`episodes[].best_release_id`; the queue is informational only today. Per-release flagging and
best-print exclusion are 📝 (§17). `/play` still works — links are real regardless of label
hygiene. Admin resolution (mark `cat_review_queue.resolved_at`) is 📝 (nothing writes it).

---

## 11. Entitlements — free / ads / flatrate / rental / purchase (the paid-or-free requirement)

### 11.1 What exists ✅ and what is designed 📝

`cat_entitlements(id, work_id|null, release_id|null, model, price_minor, currency, region,
geo_allow, geo_deny, valid_from, valid_until, rental_hours, ownership, requires_account,
requires_age_gate, updated_at)` — all columns exist, the projector inserts exactly one row
per work with `model='free', ownership='permanent'` ✅, and
`cat_works.entitlement_model` defaults `'free'`. **No server enforces anything else today**;
writing paid rows (admin CLI) is 📝.

### 11.2 The vocabulary (borrowed from IMDb/Gracenote delivery-channel categories)

| `model` | Meaning (category) | Monetization tier | Server gate |
|---|---|---|---|
| `free` | free, no strings | — | none |
| `ads` | free **with ads** (AVOD, IMDb `ads` / Gracenote FAST) | ad_supported | none (the flag tells the app an ad break UI may land here later; today it is informational only — no ad server exists, and claiming otherwise is forbidden) |
| `flatrate` | included in a subscription (SVOD, IMDb `flatrate`) | subscription | account + active-plan check 📝 |
| `rental` | transactional, time-boxed (IMDb `purchase` w/ `monetization_type=rent`) | tvod | licence + `rental_hours` window 📝 |
| `purchase` | transactional, owned | tvod | licence 📝 |

`display_priority` (INTEGER, lower shown first — the Gracenote/JustWatch ordering that makes
"Free with ads" beat "Rent HD" on the same card) **does not exist as a column yet** — 📝
(§17). Until then the server must synthesize it: `free=10, ads=20, flatrate=30, rental=40,
purchase=50`, tie-broken by `price_minor` and `resolution` rank of the linked prints.

### 11.3 The complete state machine (normative for the app)

```
                     ┌────────────────────────────────────────────────────────┐
                     │ state = (user entitlement) × (offer model per work/print) │
                     └────────────────────────────────────────────────────────┘
offer model   user state                     app shows                       /play returns
-----------   ----------------------------   ------------------------------   ----------------------
free          (none needed)                  [Play] enabled                   200 PlayBundle
ads           (none needed)                  [Play] + "contains ads" chip    200 PlayBundle +
                                                                            entitlement.model="ads"
flatrate      no account                     [Subscribe] on card, greyed     402 licence_required +
              (HTTP host: state unavailable — gated features must not be     entitlement payload
               shipped on the cleartext host, §8.3)
flatrate      account w/o plan               [Subscription required]         402 licence_required
flatrate      active plan                    [Play]                          200
rental        unlicensed                     price chip (₹xx from             402 + price_minor/
                                             price_minor+currency, minor     currency/rental_hours
                                             units, never floats)
rental        licensed, inside window        [Play] + expiry countdown       200; offline copy MUST
                                             (valid_from+rental_hours)      honour until_expiry:
rental        licensed, window passed        [Rent again]                   410 licence_expired 📝
purchase      unlicensed                     price chip                      402
purchase      licensed                       [Play], permanent offline keep  200, ownership='permanent'
```

Rules that never bend:

1. **The server is the gate.** `/play` checks entitlements before issuing any media URL;
   the app's UI state is a mirror of the last `/play`/detail response, never its own
   decision. A `402` response carries the full entitlement object so the price UI needs no
   second call.
2. Entitlements attach to a **work or a release** (`release_id NOT NULL` rows) — "4K costs
   more than 720p" is expressible today in the schema ✅; the ladder builder must honour the
   most specific row (release > work) — 📝.
3. `geo_allow`/`geo_deny`/`region` are stored ✅; enforcement (GeoIP) is 📝 and must stay off
   on the current host (no reliable client-IP chain behind nginx without config).
4. `requires_account`/`requires_age_gate` are stored ✅; **no accounts exist** (§19) and the
   age-gate flag is *only* for mature-but-not-adult content — it must never be used for
   `is_18_plus` works, which follow §13 instead.
5. Flipping one title between paid and free is exactly: update/insert the
   `cat_entitlements` row; `updated_at` bumps the `entitlements` version group (§16.2);
   clients refresh via `scope=entitlements` sync or the next detail fetch's ETag miss.

---

## 12. Endpoint surface (all Layer 2 — 📝 until built; status column is the contract)

Base: `/api/v2`. JSON everywhere (`application/json; charset=utf-8`) except problem
responses (§16.4). `v1` stays frozen and untouched — the current APK keeps working.

| Method & path | Purpose | Key params | Blocking deps (§17) |
|---|---|---|---|
| `GET /manifest` | machine-readable contract: enums, **both scoring formulas (§7.1)**, limits, versions | — | hand-build from code |
| `GET /browse` | faceted browse | `type`, `animated`, `genre`, `language`, `country`, `year_from/to`, `min_quality` (print axis), `available` (link axis), `sort=newest\|rating\|title\|score`, `cursor`, `limit≤100` | indexes exist ✅ |
| `GET /search` | title search incl. aliases | `q`, facets, `fields` | alias-table join (✅ data) |
| `GET /suggest` | type-ahead | `q`≥2, `limit≤10` | — |
| `GET /works/{id}` | detail | `fields`, `lang` | images struct 📝 (G-1) |
| `GET /works/{id}/seasons/{n}` | season + episodes + coverage mode | `fields` | pack enumeration G-2 |
| `GET /episodes/{id}` | one episode: prints, coverage, links | — | — |
| `GET /releases/{id}` | one print: descriptor + ranked links | — | — |
| `POST /play` | PlayBundle | body: one of `work_id/release_id/episode_id` (+season/episode for packs), `prefer`, `device` | resolver wrapper, versions, tracks 📝 |
| `GET /resolve/{link_id}` | JIT unwrap for `resolve_required` links | — | wraps `resolve_live_source` without its fall-through bug |
| `POST /links/{id}/report` | client telemetry `played\|stalled\|failed\|resolved` | `event, ms, error` | ingest table 📝 (feeds axis 2) |
| `POST /episodes/{id}/offset` | learned pack offset | `offset_seconds, chapter_title` | `record_offset` ✅ |
| `GET /sync?since=` | delta rows (`scope=catalog\|health\|entitlements`) | key on **work_key**, not ids (§3 caveat) | per-group revs 📝 |
| `GET /collections/{id}` | franchise/pick-list | — | **no table exists** 📝 |
| `GET /feed.m3u` | IPTV playlist: adult-filtered, **only non-ephemeral streamable links** (`ephemeral=0 AND playability IN ('stream','both') AND state='active'`), `#EXTINF` duration from runtime, group-title = work title | `work_id` optional | trivial query ✅ data |
| `GET /stats` | totals by site/type/quality + link-health mix + `projected_at` | — | must exclude adult ✅ (§13; note v1 stats leaks adult counts — do not copy) |
| `GET /health` | liveness/readiness for ops | — | — |

Removed from v2: `/api/heal` (never responded), `/api/fetch` (unauthenticated remote ingest
— becomes CLI-only behind TLS when accounts exist).

---

## 13. Adult content — the single rule (resolves the old 403-vs-404 contradiction)

Storage keeps 100% of what we scrape, including 18+ titles, flagged at projection time
(`cat_works.is_18_plus=1` when **any** contributing post is flagged ✅ — one-way ratchet, a
work containing adult material is adult).

**The one rule, applied identically on every route with no exceptions:**

> To an unprivileged caller, an adult-flagged work is **indistinguishable from a work that
> does not exist**: same status (`404`), same problem body (§16.4, `code: not_found`), same
> latency profile, and the same count treatment (excluded before any `total_estimate` is
> computed — no count skew).

Concretely:

- `browse`, `search`, `suggest`, `collections`, `stats`, `feed.m3u`, `sync`: excluded in the
  SQL `WHERE` (the same predicate shape v1 uses: `is_18_plus IS NULL OR is_18_plus = 0`).
- `works/{id}`, `seasons/{n}`, `episodes/{id}`, `releases/{id}`, `resolve`, `play`, offset
  and report endpoints: `404 not_found`, **exactly** the response for a genuinely unknown id.
  There is no `403 adult_restricted` on any public route, and the code `adult_restricted`
  does not exist in §16.4's enumeration. (The retired matrix's `403` row and the old §11 "explicit
  internal reason" sentence are deleted as contradictions.)
- **The flag itself is never in a public payload.** No `is_18_plus`, no `adult` field, no
  "restricted" word — not even as `false`, to prevent inference ("this one has the field ⇒
  fields are withheld only for adult"). The payload scrubber strips the column by name.
- `include_adult=true` is honoured **only** with admin credentials **over TLS** — since the
  host is HTTP-only (§8.3), this path is currently unreachable and every caller is
  unprivileged; the rule is written so the code has one behaviour and one test.
- Enforcement lives in **one place**: the Layer-2 query builder's base scope (a single
  `adult_scope()` predicate + the response scrubber), not per-endpoint checks — that is the
  only structure that survives someone adding endpoint #20. Regression tests:
  `test_database.py::AdultContentFilterTests` (v1) + the Layer-1 flagging test ✅ + a v2
  parity test (admin-less `404` byte-identical to unknown-id `404`) 📝.
- Known v1 wart to never copy: `resolve_live_source` answers
  `"Source restricted (18+ content)"` on a flagged source, and `/api/v1/stats` counts adult
  posts (App/AGENTS.md §5). v1 is frozen; document and route around it (HANDOFF).

---

## 14. Resource shapes

`GET /browse` item (every key backed by a `cat_works` column or rollup ✅):

```json
{"id": 1234, "work_key": "imdb:tt0987654", "title": "Campus Beats", "year": 2026,
 "work_type": "series", "animated": false,
 "poster": {"url": "https://…", "locale": "en"},
 "rating": 6.1, "genres": ["Crime", "Drama"], "languages": ["hi"],
 "season_count": 7, "episode_count": 84, "quality_max": "1080p",
 "available": {"stream": true, "download": true},
 "updated_at": 1730000000, "entitlement": {"model": "free"}}
```

`GET /works/{id}` adds: `aliases[]` ✅ (`cat_work_aliases`), `synopsis`, `credits[]`
**planned — no credits table exists**, `images[]` **planned as a structured object** — today
only `poster_url` + `backdrop_urls` (CSV of URLs) exist ✅, with no width/kind metadata (a
TMDB-style `image` variants table is the design target); `provenance[]` ✅ (`cat_work_sites`),
`seasons[].episodes[].best_release_id` / `quality_options[]` ✅, `prints[]` (§5),
`availability` ✅ (`available_stream/download` rollups), `flags[]` (incl.
`identity_suspect` §13 — adult flag never). `sites[]`.

`?fields=id,title,poster,available` returns exactly those keys plus `meta` (sparse fieldsets,
supported everywhere 📝 until handlers exist). Posters keep `locale` from where the scraper
recorded it; `width`/`kind ∈ {poster|backdrop|still|logo}` are 📝.

---

## 15. What the client model classes must decode (Android note)

- Every enum (§4–§6) arrives as a **string**; model them as sealed classes with an
  `UNKNOWN` fallback branch (the enum-tolerance rule, §16.6, asserted by a decode test).
- Numbers: `quality_score` 0..1000, `rank/score` 0..900 or 0..1000 depending on
  `score_scale` (§7.1) — never compare a prior against a measured without checking the scale.
- Nullable-everywhere for 🛠 columns: `accepts_ranges`, `speed_mbps`, `latency_ms`,
  `expires_at`, `size_bytes`, `offset_seconds`. The app must have a "no evidence yet" render
  path (v1's `is_temporary: Int?` vs boolean bug must not repeat).
- Timestamps are Unix **seconds** (REAL in sqlite, emitted as numbers; floats rounded to int
  by the server).

---

## 16. Cross-cutting API rules

### 16.1 Pagination
Cursor-based: opaque base64 of `(sort_value, id)`; `offset` accepted on `/browse` but
documented unstable (re-sorts with every ingest). Responses carry `next_cursor`,
`total_estimate` (nullable, never exact on 20k+ rows, **computed inside the adult scope**),
`limit ≤ 100`. Invalid cursor ⇒ `400 cursor_invalid` (§16.4), and the client restarts page 1.

### 16.2 Versions, conditional requests, caching — per-link-group, not one global stamp
Every GET carries `ETag` + `Cache-Control` + `Last-Modified` (RFC 9110 hygiene).
Instead of a single global version, each **version group** carries its own rev, surfaced in
`meta.versions` and joined into the ETag so a health sweep does not invalidate the catalog
cache and vice versa:

| Group | Bumped by | Backing today | Status |
|---|---|---|---|
| `catalog` | projection run | `cat_projection_meta.projected_at` + `source_rev` stamped on works | 🛠 one value, needs `catalog_rev` key |
| `health` | link probe write-back | nothing records it | 📝 |
| `offsets` | `record_offset` | nothing records it | 📝 |
| `entitlements` | entitlement edits | `cat_entitlements.updated_at` MAX is derivable | 📝 trivial |

`GET /browse|search`: `public, max-age=60`; detail: `public, max-age=300,
stale-while-revalidate=3600`; `/play`, `/resolve`: `no-store`; `/manifest`: `public,
max-age=3600`. Conditional `If-None-Match` ⇒ `304` (mandatory — the app polls on mobile data).
Weak ETags (`W/"cat-148-health-9213"`) are the correct form since byte-equivalence isn't
promised (RFC 9110 §9.3.4 weak validators for heuristic-cacheable JSON).

### 16.3 Delta sync
`GET /sync?scope=catalog&since=<cursor>` returns row-level upserts keyed by **`work_key`**
(§3 id-stability) with the group `rev`, plus tombstones for removed works;
`scope=health` returns link-state deltas (`link_url/state/score/score_scale/last_evidence_at`)
— that is how an offline cache stays honest without re-downloading the world.

### 16.4 Errors — RFC 9457 `application/problem+json`
Adopted verbatim (RFC 9457 supersedes 7807): standard members `type`, `title`, `status`,
`detail`, `instance`, plus our extension members `code` (the stable machine code — clients
switch on `code`, never on `title`/`detail`), `request_id`, and optional `details` object.

```jsonc
// HTTP/1.1 409 Conflict · Content-Type: application/problem+json
{"type": "http://92.4.95.252/api/v2/problems/no_playable_source",
 "title": "No source for this target can currently play",
 "status": 409,
 "detail": "3 ranks tried; every candidate returned a transport or HTTP failure.",
 "instance": "/api/v2/play",
 "code": "no_playable_source",
 "request_id": "req_7f3c…",
 "details": {"tried": [{"link_id": 9, "reason": "http_404"},
                        {"link_id": 12, "reason": "timeout"}]}}
```

Complete, closed code enumeration (adding a code = additive; renaming = `v3`):

| `code` | HTTP | When |
|---|---|---|
| `invalid_params` | 400 | bad body/facet values |
| `cursor_invalid` | 400 | §16.1 |
| `unauthorised` | 401 | admin path without creds (unreachable on HTTP host — §8.3) |
| `forbidden` | 403 | privilege present but action disallowed (never adult — §13) |
| `not_found` | 404 | unknown id **and** adult-flagged id, identically (§13) |
| `licence_required` | 402 | §11.3 gate |
| `no_playable_source` | 409 | `/play`/`/resolve` ladder exhausted (never a fake 200/302) |
| `gone` | 410 | work withdrawn from catalog |
| `bundle_expired` | 410 | `session.id` presented after `expires_in` (§8.4 step 3) |
| `licence_expired` | 410 | rental window passed (§11.3) |
| `rate_limited` | 429 | §16.5 |
| `target_unresolvable` | 422 | target triple (work/season/episode) cannot be assembled — e.g. episode of a pack-only season with no offset path (G-2) |
| `internal` | 500 | bug; `instance` + `request_id` are the debug handles; never a stack trace in the body |
| `unavailable` | 503 | projection in progress / dependency down, with `Retry-After` |

### 16.5 Rate limiting — the header contract
Per `draft-ietf-httpapi-ratelimit-headers` (draft-06 three-header form chosen for gateway
compatibility; the newer structured-field single-header variant is noted but not adopted):

```
RateLimit-Limit: 30        // bucket size per window
RateLimit-Remaining: 29    // left in this window (on EVERY response, not just 429)
RateLimit-Reset: 47        // seconds until the window reopens
```
A `429` **must** also carry `Retry-After` (RFC 9110; delta-seconds). The app treats
`Remaining=0` as "schedule after `Reset`" and backs off `/play` proactively. Buckets:
`/play|/resolve` 30/min per device-IP, reports 10/min, browse/search/suggest 60/min, `/sync`
120/min; token-bucket per IP behind nginx (`limit_req`), because `viewer.py` has none of this
today (§2 defect #6) — implemented at the proxy first, in-app second 📝.

### 16.6 Versioning and compatibility
Path versioning (`/api/v2`), `meta.contract_version` + `/manifest` as the machine-readable
source. Additive changes are non-breaking and announced in `/manifest`; removing/renaming a
field or enum value requires `/api/v3`. Enum values are **never renamed**; new values are
added and clients must decode unknown ones to `UNKNOWN` (asserted by an app-side test that
decodes a payload containing a never-seen enum — carry this from the old contract unchanged).

### 16.7 Security (blocking before any real exposure)
- Today: no auth, wildcard CORS, `0.0.0.0` bind, plain HTTP (verified in `viewer.py`; App/AGENTS.md
  §5). Under §8.3, that means **all admin/auth features are unreachable by design** until TLS
  exists — the contract's adult-exception and entitlement gates are code-complete rules with
  no shipped privileged caller.
- `Access-Control-Allow-Origin`: explicit allow-list, never `*` (nginx already hides the
  upstream ACAO header — extend that pattern, `ORACLE_DEPLOYMENT.md` proxy config).
- SSRF: the resolver/proxy never fetches user-supplied URLs; outbound probe targets pass
  `link_health`'s `blocked_target` guard (private/loopback/link-local/metadata ranges,
  embedded creds, non-http schemes) — that guard is ✅ and must wrap every server-side fetch.
- Rate limits per §16.5; `X-Radd-Admin` honoured only over TLS.

### 16.8 Observability
`X-Request-Id` on every response (echoed into problem payloads); `/play` decisions logged
with the chosen rank, the rejected ranks and their axis scores (§7) so ranking is tunable on
evidence; `/stats` exposes the link-health mix (`link_health.summarize()` ✅ shape:
`{total, ok, failed, streamable, downloadable, resumable, cors_open, by_protocol, by_error,
avg_latency_ms, avg_speed_mbps, ok_ratio}`).

---

### 16.9 Provenance is operator-only — the public edge is deny-by-default
The product promise: an ordinary user of the app, the PWA or the dashboard never learns
**which site** a title came from, **which server** carries it, or **what URL** to copy.
The business reason is harder than the aesthetics: an API that names its sources is a
catalog other people can rebuild inside their own app, so this is an exposure rule, not
a style rule.

Enforced in `Fast_Fetch/redact.py`, at serialization only:

| Rule | Mechanism |
|---|---|
| A response contains only the keys its *view* allows — a new column is invisible until deliberately published | `VIEWS[view]` + `project(row, view)` |
| Anything provenance-shaped is removed even from a nested payload | `PROVENANCE` deny-list + `scrub()` |
| A display string may not name a site or a hoster | `scrub_text()` over the registry-derived needle vocabulary |
| A genre/language/country list may not smuggle a scraped domain | `LIST_KEYS` + `_category_token()` (a category has no digits, no dots) |
| Playables and artwork are addressed by **our** signed handle, never by a row id or an upstream URL | `mint_token()`/`parse_token(signed_only=True)` |
| A hidden (18+) title answers exactly as a nonexistent one, on every surface including its links | `adult_clause()`, `art_is_adult()`, `link_is_adult()` |
| Whole-catalog dumps and the hoster bridge table are not served to the public at all | `OPERATOR_ONLY_ROUTES` on the public port; provenance lives on a second loopback port |

**This is metadata suppression, not access control.** The SQLite ledger keeps every site
name, service name, page URL and final URL — healing, back-fill and diagnostics depend on
them — and the server log does too. Anyone willing to decompile the client or read the
server can still learn what a title is played from; nobody looking at the app can. Say it
that way in release notes and in any answer about "is this hidden".

---

## 17. Planned, not implemented (single honest checklist)

Everything 📝/🛠 above, in one place. Nothing here may be described as live anywhere else.

- [ ] **All of Layer 2**: every `/api/v2` endpoint; `/manifest` content per §7.1.
- [ ] Link-health write-back: `link_health.probe_many` results into `cat_links`
      (state/speed/latency/accepts_ranges/cors_open/resumable/last_evidence_at) + `health` rev bump.
- [ ] `measured` score (`score_link`) replacing the projection prior in `playback.score`, with `score_scale`.
- [ ] Per-group versions in `cat_projection_meta` (§16.2) and id-stable projection or id-mapping
      table for persisted client caches (§3).
- [ ] Episode enumeration for `season_pack` releases (synthesize from known span/hints) (G-2).
- [ ] `cat_parts` population + real `parts` coverage (G-3).
- [ ] Tracks: `cat_tracks` table (per-audio-language codec/channels/default flag, subtitle
      external URLs/formats) or HLS-`EXT-X-MEDIA` parsing at resolve time (G-1).
- [ ] `display_priority` column/derivation (§11.2); paid `model` rows + admin CLI; `/play`
      entitlement check; `licence_expired` path.
- [ ] Resolver without `success:true` fall-through (wrap `resolve_live_source`, fix §2 #4) +
      `expires_at` on ephemeral resolved URLs + `requires_https` derivation (§8.3).
- [ ] `hdtc`/`bdmux`/`dvd` source tags (HDTC currently mis-scored `official_print=true`) (G-4).
- [ ] `release_group` extraction from labels (column always `''` today).
- [ ] Review-queue kinds beyond `season_unresolved`: year conflicts, external-id conflicts,
      resolution tooling (`resolved_at`).
- [ ] Per-release `identity_suspect` flag + exclusion of unresolved prints from
      `episodes[].best_release_id` (S13 — queue exists but is informational only today).
- [ ] `collections` table + endpoint; `credits` table; structured `images[]` with width/kind.
- [ ] `season_type='special'/'extra'`, `episode.title/air_date/runtime_minutes` population.
- [ ] Alias `kind ∈ {original, localized, transliteration, romanized}` population.
- [ ] Rate limiting (nginx `limit_req` then in-app) + `RateLimit-*` headers (§16.5).
- [ ] RFC 9457 problem handler + `X-Request-Id` (§16.4, §16.8).
- [ ] Majority-vote pack offsets (today: last write wins, §4.3).
- [ ] Repack-freshness tiebreak (today: `id ASC`, §5.2).
- [ ] Adult v2 parity test: admin-less 404 byte-identical to unknown-id 404 (§13).

---

## 18. Known schema gaps — what Layer 1 cannot answer today (client-visible consequences)

| ID | Gap | Scenario blocked / degraded | Workaround the API must implement now |
|---|---|---|---|
| G-1 | No per-track rows; audio is one aggregate per print; no subtitle URLs with formats | S1/S6 "pick Hindi 5.1 track, English SDH subs" from the API alone | HLS `EXT-X-MEDIA` parsed **at resolve time** by Media3 itself (free for hls links); progressive links show only the aggregate (`dual_audio`, `subtitle_mode`) — no track UI |
| G-2 | `season_pack` enumerates no episodes | S2 per-episode grid/play targeting | season-level `pack_releases[]` + offsets (§S2); `target_unresolvable` only when even the season can't be inferred |
| G-3 | `cat_parts` never written | S4 multi-part movies addressed as parts | label-based `part_stub` heuristic (§S4) |
| G-4 | No `hdtc` capture-source rung; HDTC scores as `unknown` + official | S6 ordering slightly wrong for cam-adjacent prints | document weight honestly in `/manifest`; UI chip shows label text |
| G-5 | No expected-episode-count source | S5 "season incomplete" badge | show known counts, never claim completeness |
| G-6 | `expires_at` not computed anywhere | §8.4 | conservative 900 s bundle TTL + re-`/play` recovery |
| G-7 | Probe results live on the ledger until full re-projection | §9 `prefer=speed` staleness | serve prior with `score_scale='projection_prior'`; never fake `measured` |

---

## 19. Deliberate non-goals (v2, for now)
DRM licence serving (`playback.drm` stays `null`; Widevine/FairPlay systems require licensed
content and a TLS host we don't have), torrent *playback* (torrent files are `download_only`
links, honestly classified), server-side transcoding, accounts/profiles (nothing to auth over,
§8.3), recommendation ML, subtitle authoring, ad insertion (the `ads` model is a labelling
tier only until an ad decision path exists — §11.2).

---

## 20. Projection and rollout plan

1. ✅ `catalog_v2.py` `project(all)`: ledger → `cat_*`, idempotent, counters + `identity_suspect`,
   `test_catalog_v2.py` covering §4/§5/§6/§7 claims.
2. ✅ `release_descriptor.describe()` for prints; ✅ `link_health` for probing; 📝 write-back (G-7).
3. 📝 `viewer.py` v2 handlers reading only `cat_*` (+ `cat_projection_meta` revs) implementing
   §12–§16, in this order: `/manifest`, `/browse|search|suggest|works`, `/play|/resolve`,
   problem+errors + rate headers, `/sync`, `/feed.m3u`.
4. v1 stays frozen; nothing deleted, the current APK keeps working.
5. Test order: unit (descriptor/health/projector) → contract (`/manifest` ↔ documented enums,
   §16.6 decode-tolerance test) → scenario assertions (§10) → **real-corpus assertions against the
   merged catalog**: every ledger link exists in `cat_links`; no episode has two
   `best_release_id`s; every `quality_score` within the documented formula range; every
   public payload scrubbed of `is_18_plus` (§13).
6. Deployment gate (§8.3): entitlement/account/admin features stay dark until the host serves
   TLS; the HTTP-only posture is a documented constraint of this contract, not a bug to hide.

---

## Sources consulted for §1–§16 refinements

- [RFC 9457 — Problem Details for HTTP APIs](https://www.rfc-editor.org/rfc/rfc9457) (error envelope, `type/title/status/detail/instance` + extension members).
- [IETF draft-ietf-httpapi-ratelimit-headers](https://datatracker.ietf.org/doc/draft-ietf-httpapi-ratelimit-headers/) / [draft-11 text](https://datatracker.ietf.org/doc/html/draft-ietf-httpapi-ratelimit-headers-11) and [http.dev RateLimit-Limit guide](https://http.dev/ratelimit-limit) (Limit/Remaining/Reset triple + `Retry-After` on 429).
- [TMDB talk — release dates model](https://www.themoviedb.org/talk/6401b9b3699fb7007d8f91c6) and [TMDB v4 release-date types](https://github.com/leocabeza/the-movie-db/blob/master/docs/v4-api.md) (release event vs medium; Premiere/Theatrical/Digital/Physical/TV taxonomy informing print-vs-release separation).
- [IMDb data services](https://data.imdb.com/) and [IMDb non-commercial datasets](https://www.kaggle.com/datasets/nhondangcode/imdb-non-commercial-datasets) (streaming availability categories: flatrate/free/ads/purchase) + [Gracenote FAST metadata product](https://shop.gracenote.com/products/fast) (delivery-channel/monetization tier vocabulary for §11).
- [Android Media3 supported formats](https://developer.android.com/media/media3/exoplayer/supported-formats) (HLS rendition/track-selection expectations driving §8.5: `EXT-X-MEDIA` renditions, WebVTT/captions, `DefaultTrackSelector` behaviour).
