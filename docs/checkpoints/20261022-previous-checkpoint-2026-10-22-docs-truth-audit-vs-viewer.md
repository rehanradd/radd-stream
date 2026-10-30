# Previous checkpoint — 2026-10-22 (Docs truth-audit vs viewer.py)

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## Previous checkpoint — 2026-10-22 (Docs truth-audit vs viewer.py)

- **Goal:** Remove documentation that asserted API behaviour the code does not
  implement, so future agents and app developers stop building against endpoints
  and filters that cannot work.
- **Method:** every claim re-read against `Fast_Fetch/viewer.py`
  (`do_GET()` 2039-2190, `api_v1_get_posts()` 1886, `api_v1_get_post_detail()`
  1930, `api_v1_rules()` 1968, `generate_m3u_playlist()` 185, stats 2156-2174)
  and `Fast_Fetch/fast_fetch.py` (`classify_media()` 1613-1622,
  `resolve_live_source()` ~4540-4600), plus `PRAGMA table_info` on a staging
  database and one live `api_v1_get_posts()` call. No `.py` or `.kt` file was
  modified; nothing was committed or pushed; no crawler was run.
- **Verified defects corrected in docs:**
  1. **`?type=anime` never matched.** `viewer.py:1898` filters with
     `p.content_type = ?` (exact equality); `classify_media()` only ever writes
     `movie` / `series` / `complete_season` / `ongoing_season`. A live call with
     `content_type='anime'` returned `total: 0` while unfiltered returned
     `10512`. Corrected in `Fast_Fetch/ANDROID_INTEGRATION.md`, `App/AGENTS.md`,
     `App/README.md`, `App/docs/PLAN.md`, `App/design/SCREENS.md`, `README.md`,
     `docs/PROJECT_MAP.md`. **The Kotlin is still broken** —
     `HomeScreen.kt:48` and `SearchScreen.kt:49` still send `type=anime`; fixing
     it needs either a removed chip or a new backend `animated` filter parameter.
  2. **`/api/v1/posts/{id}` does not order releases by tier or group by
     season/episode.** `viewer.py:1942` is `ORDER BY id ASC`. The tier `CASE`
     (viewer.py:1946-1961) applies only to `sources` inside a release:
     `status='active'` first, `is_temporary ASC`, then `pixeldrain`,
     `vegadrive`, `hubcloud_10g`, `fsl_r2`, `fastdl`, `google_cdn`, everything
     else `99`. Documented that the `CASE` matches only those literal strings,
     while real rows commonly carry host-derived names (`fastdl-beer`,
     `vcloud-beer`, `hubcloud-ist`) that all fall through to `99`.
  3. **`/api/v1/sync` does not exist** (no such route, no `do_POST` at all).
     `App/docs/PLAN.md` §3.4 now marks it explicitly as a proposal.
  4. **`api_v1_get_posts()` example omitted real keys.** Corrected to the exact
     `SELECT` list (viewer.py:1905-1909): `id, clean_title, title, year,
     content_type, seasons, poster_url, imdb_rating, imdb_id, tmdb_id, genres,
     source_site, industry, country, language, release_count, source_count`.
     Note `slug` is **not** returned by the list route (contrary to the audit
     brief) — it only appears on the detail response.
  5. **`App/AGENTS.md` self-contradiction resolved.** It claimed the app calls
     only `/api/v1/stats` and `/api/v1/posts` and that Detail/Player/MyList/
     Settings are "not navigable". `RaddStreamApi.kt` declares four endpoints and
     `CatalogRepository.kt:38,46` + `DetailViewModel.kt:69,130` + `NavGraph.kt:139-165`
     actually use detail and stream resolution. §5/§6/§8/§0/§4/§11 rewritten to
     the verified state, with historical Phase 1 lists labelled as plan.
  6. **`/api/heal` hangs.** viewer.py:2100-2108 builds `resp_payload` and never
     calls `send_json()`; `protocol_version = "HTTP/1.1"`, so clients wait for a
     response that never arrives, and a missing/non-numeric `id` raises before any
     response. Documented as broken/unusable in `ANDROID_INTEGRATION.md`,
     `App/docs/PLAN.md`, `README.md`, `docs/PROJECT_MAP.md`. **The Python was not
     changed**, per task scope.
  7. **No auth, no keys, no rate limiting, no HTTPS.** Verified by grepping
     `viewer.py` for `Authorization` / `api_key` / `rate_limit` / `Bearer` — zero
     hits. `send_json()` emits `Access-Control-Allow-Origin: *` (viewer.py:2037)
     and `start_server()` defaults to `0.0.0.0` (viewer.py:2211). Removed the
     "auth token injection" bullet from `App/docs/TECH_STACK.md`, the `token`
     profile field from `App/docs/PLAN.md` §3.3, and added explicit public-surface
     warnings wherever docs implied privacy.
  8. **Stale numbers relabelled.** The `131 / 1031 / 2017` figures were a
     2026-10-13 snapshot; `/api/v1/stats` field *names* kept exactly as the code
     returns them and values labelled illustrative. `docs/PROJECT_MAP.md` no
     longer implies the suite is only `test_database.py` + `test_vidout.py` — 26
     `Fast_Fetch/test_*.py` modules exist today.
- **NEW contradictions found beyond the eight briefed:**
  - `Models.kt:68-84` `ReleaseDetail` maps `season_number`, `episode_number`,
    `episode_title`, `resolution`, `audio` — **none of those keys exist** in the
    `releases` payload (`PRAGMA table_info`: `release_title, season, episode,
    quality, codec, size, languages, intermediate_url, origin_url, ...`).
    `DetailScreen.kt:206-220,426-428` builds its entire season/episode grouping on
    those always-null fields, so series grouping silently does nothing.
  - `StreamResponse.isTemporary: Int?` cannot receive the JSON **boolean**
    `resolve_live_source()` returns (`is_temporary` is wrapped in `bool(...)`), so
    Gson rejects that field on `redirect=0` responses.
  - `AndroidManifest.xml:43-48` registers a `radd://` intent filter but
    `NavGraph.kt` declares no `navDeepLink` entries — deep links cold-start to the
    default destination and route nowhere.
  - `/api/v1/stats` has **no** `is_18_plus` filter (viewer.py:2157-2162), so its
    `posts` count exceeds what `/api/v1/posts` can ever show. Docs now say so.
  - `App/design/SCREENS.md` Screen 2 draws a hero banner and per-type `LazyRow`
    sections; `HomeScreen.kt` implements a single `LazyVerticalGrid` only.
  - `PLAN.md` §2.3/§2.2 (downloads, continue-watching) genuinely unbuilt, but
    §3.1 external-player hand-off **is** built (`DetailScreen.kt:529-539`) — the
    roadmap has now been split accordingly.
- **Checks run:** read-only `api_v1_get_posts()` / `api_v1_get_post_detail()`
  calls against `Fast_Fetch/multimovies.db` via `RADD_DB_PATH` (no writes);
  `PRAGMA table_info` on `posts` / `releases` / `download_sources`; content_type
  distribution query (`movie` 7753, `series` 2759, `anime` 0); grep sweeps for
  `anime` / `auth` / `sync` / `heal` across all twelve permitted docs. No test
  suite was executed in this session and no server was started.
- **Files changed (Markdown only, nothing committed or pushed):** `README.md`,
  `Fast_Fetch/ANDROID_INTEGRATION.md`, `Fast_Fetch/DATABASE_SCHEMA.md`,
  `App/AGENTS.md`, `App/README.md`, `App/docs/PLAN.md`, `App/docs/TECH_STACK.md`,
  `App/design/SCREENS.md`, `docs/PROJECT_MAP.md`, `docs/SESSION_CHECKPOINT.md`.
  `Fast_Fetch/DATABASE_SCHEMA.md` already documented `content_type` correctly
  (lines 50 and 148 list the four real values), so the only edit there is the new
  warning that its canonical `download_sources.service` vocabulary is not the tier
  ranking and does not match the host-derived values real rows carry. `Fast_Fetch/SITES.md` was checked — its
  "anime" mentions are third-party site genre labels and its `/api/...` references
  are the *sites'* WordPress and KatDrive endpoints, not this project's API, so it
  was left untouched. `docs/AI_HANDOFF_PROMPT.md` contains no API claims.
- **Next action:** fix the three Kotlin/backend defects above (anime chip,
  `ReleaseDetail` field names, `StreamResponse.isTemporary` type) or add an
  `animated` query parameter to `api_v1_get_posts()`; then add the missing
  `send_json(resp_payload)` to the `/api/heal` branch at viewer.py:2108. Re-run
  `python -S Fast_Fetch/test_database.py` and the full `test_*.py` set after any
  code change.

