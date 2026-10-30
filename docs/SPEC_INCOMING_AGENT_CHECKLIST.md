# ✍️ Incoming Agent Checklist

> moved verbatim out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## ✍️ Incoming Agent Checklist

When you take over this project in a new Replit workspace:
1. Read root `AGENTS.md`, `SESSION.md`, `docs/PROJECT_MAP.md`, and `docs/SESSION_CHECKPOINT.md`.
2. Read `Fast_Fetch/AGENTS.md` and this continuity ledger; inspect Git status, branch, and remotes before pulling or switching branches.
3. Run offline regressions from the repository root (`python -S Fast_Fetch/test_database.py`, `python -S Fast_Fetch/test_vidout.py`) and `python setup_check.py`. Run the live site audit only when relevant and when its network requests are appropriate.
4. Choose a scoped task and work on a task/agent branch. Do not pull or push `main` blindly.
5. After each tested milestone, update the cross-agent checkpoint and this ledger, stage only reviewed files, commit, and push the branch using the askpass procedure in `ORACLE_DEPLOYMENT.md`.
6. If a session may stop before tests finish, push a clearly labeled WIP branch commit and list the pending checks. Do not merge or deploy WIP code.
7. Never use `push.py`, `github_push.py`, or `emergency_push.py`; these legacy uploaders can write broad file sets to `main`, and the emergency uploader skips tests.

### Session 4 — Replit Agent — Oct 2026
**Built:**
- Added standard-library VIDOUT page parsing to identify HLS playlist URLs for MultiMovies movie and episode sources; retained the original embed URL as the source URL.
- Added secret-safe `GITHUB_TOKEN` lookup and workspace-relative root resolution to `github_push.py`.
- Confirmed MultiMovies sitemap sync already processes all numbered title sitemaps discovered in the index; the live index currently lists two.
- Verified six offline VIDOUT tests, the setup check, Python compilation, and the live 10-site audit.

### Session 5 — Replit Agent — Oct 2026
**Built:**
- Added a per-site page catalog that maps each site's source URL/title/slug to one shared media row, with migration backfill for older databases.
- Tightened media matching around IMDb/TMDB IDs, URL consistency, media type, and ambiguous title/year matches; series/season-pack variants now share an identity.
- Serialized identity lookup and writes to prevent concurrent duplicate records; metadata lookups run before the write lock. Thread and multi-process stress checks both converged to one post.
- Preserved previously known releases on empty refreshes and kept legacy releases with unknown site attribution unknown rather than guessing.
- Updated CLI stats/details/export and the dashboard payload to show source-page coverage; fixed empty CSV exports and documented the actual schema and migration behavior.
- Added 22 offline database tests; all pass alongside six VIDOUT tests. Setup checks and Python-standard-library-only runs pass. The live audit exits nonzero on failures; all 10 live samples passed and persisted to a temporary DB: 10 master rows, 10 pages, 62 releases, and 245 links.
- Verified empty JSON/CSV exports and safe-path dashboard generation; the checked-in 8 MB dashboard snapshot was preserved. Four concurrent processes also converged to one master post with four source-page rows.

### Session 6 — Antigravity — Oct 2026
**Built:**
- Investigated git history, local commits from Replit Agent (`9bfb524`, `beca84a`), and unpushed GitHub status.
- Implemented paginated category archive crawling for HDHub4u and SSRMovies:
  - Added `fetch_categories_hdhub4u()`, `fetch_category_urls_hdhub4u()`, `fetch_categories_ssrmovies()`, `fetch_category_urls_ssrmovies()`, and `sync_category_archives()`.
  - Added CLI subcommand `sync-categories` (`--site`, `--pages`, `--category`) and integrated `--categories` / `--cat-pages` options into `sync`.
  - Enforced strict safety policy compliance by filtering out restricted / adult category slugs across both sites.
  - Added 6 new unit tests in `test_database.py` (total 28 database tests, 100% pass).
  - Validated live 10-site audit (10/10 operational).
  - Pushed all accumulated commits and changes from Sessions 4, 5, and 6 to GitHub repo `https://github.com/radddao/radd-stream` via `github_push.py`.

### Session 7 — Antigravity — Oct 2026
**Built:**
- Link lifecycle & token expiration analysis: mapped temporary token lifespans (Cloudflare R2 12h, Google CDN 6-12h) vs permanent streams (PixelDrain, VegaDrive, HubCloud 10G).
- Executed 10-site multi-content bulk ingestion:
  - Scraped 131 catalog posts across movies, full TV series (e.g. *Money Heist*, *Ozark*, *Inside Edge*), anime (*Demon Slayer*, *Vanitas*), and web series.
  - Ingested 1,031 release variants and 2,017 direct sources across 65+ distinct streaming and download services.
  - Verified 100% coverage across all 10 configured websites: Vegamovies (28), MultiMovies (30), HDHub4u (21), SSRMovies (12), KatMovieHD (9), RogMovies (5), 7StarHD (5), 10xflix (5), BollyShares (5), FilmyZilla (5).

### Session 8 — Antigravity — Oct 2026
**Built:**
- Built Just-In-Time (JIT) live stream resolver `resolve_live_source(source_id)`: returns active stream-ready URLs, caches permanent ones, and on-demand re-resolves expiring Cloudflare R2 / Google CDN tokens from bridge pages.
- Built proactive sweep `heal_expiring_sources()` and background healing daemon `start_healing_daemon()` with CLI options (`heal --daemon`, `heal --expiring`, `heal --interval`, `resolve <id>`).
- Built Production REST API Server v1 in `viewer.py`:
  - `GET /api/v1/posts` (paginated catalog search, filter by content_type and query).
  - `GET /api/v1/posts/{id}` (full media detail with nested releases and priority-tiered sources).
  - `GET /api/v1/stream?id={id}` (live JIT stream resolver with HTTP 302 redirect for native video players, or JSON mode).
  - `GET /api/v1/rules` (remote unwrapping regexes for Android app client-side execution).
  - `GET /api/v1/stats` (live database metrics).
- Added 4 new regression tests in `test_database.py` (32 total tests, 100% pass). Verified live HTTP server and all 5 API endpoints.

### Session 9 — Antigravity (Gemini 3.8 Flash) — Oct 2026
**Built:**
- Completed **Milestone 3: Advanced Bridge Resolvers**:
  - Implemented `decode_greenmotors_payload` and `unwrap_greenmotors`: Decodes HDHub4u's 4-layer obfuscated bridge (`b64 -> b64 -> rot_13 -> b64 -> JSON -> dest_url`), traverses the target `hblinks` archive, and extracts high-speed direct streams across HubCloud (`fsl_r2`), PixelDrain (`api/file/`), Direct-Cloud, and FastDL mirrors.
  - Implemented `unwrap_direct_cloud`: Intercepts `storage.direct-cloud.org` sessions, extracts `data-uid` and `data-token`, and performs cookie-aware `/action` `DOWNLOAD_GENERATE` requests yielding direct Google CDN streaming URLs (`video-downloads.googleusercontent.com`).
  - Integrated both resolvers into `unwrap_linkszilla` and dynamic JIT token healing `resolve_live_source`.
  - Added selector patterns and endpoint descriptors for `direct_cloud` and `greenmotors` to `/api/v1/rules` in `viewer.py`.
  - Updated bridge chain documentation in `Fast_Fetch/SITES.md`.
- Added 4 new unit tests in `test_database.py` covering payload decoding, HubCloud/PixelDrain extraction, session action resolution, and JIT healing (36 total tests, 100% pass).
- Verified full suite: `setup_check.py` (15/15 pass), `test_vidout.py` (6/6 pass), and live audit `test_all_sites.py` (10/10 operational).
- Pushed changes to GitHub repo `radddao/radd-stream` via `python github_push.py`.

### Session 10 — Antigravity — Oct 2026
**Built:**
- Completed **Milestone 4: Lightweight Mobile & Web Client Integration**:
  - **In-Dashboard Player Modal** (`viewer.py` `DASHBOARD_HTML`):
    - `▶ Play JIT` button per source row calls `openStreamPlayer(sourceId, url, title)`.
    - Full-screen modal with embedded HTML5 `<video>` element, VLC deep-link button, MPV command snippet, and "Copy URL" clipboard function.
    - Modal dismissal via `✕` or clicking outside the overlay.
    - "Stream / DL" button now routes through `/api/v1/stream?id={id}&redirect=1` for native redirect.
    - `📱 Mobile App` header button links to `/client`.
  - **Mobile PWA Client** (`MOBILE_CLIENT_HTML` in `viewer.py`):
    - Touch-optimized single-page app served at `/client` and `/mobile`.
    - Poster-card catalog grid loaded from `/api/v1/posts`; search debounced at 400ms.
    - Filter chips: All / Movies / Series / Anime — update grid in real time.
    - Bottom-sheet modal with HTML5 `<video>` player, native Android intent URIs for VLC, MPV, and MX Player.
    - Separate `/api/v1/rules` modal displaying all unwrapping patterns and live database stats.
  - **`Fast_Fetch/ANDROID_INTEGRATION.md`** (new file):
    - ExoPlayer / Media3 HLS+DASH setup with `radd-stream` as streaming backend.
    - External player Intent launch patterns (VLC, MPV, MX Player).
    - Client-side IP-based unwrapper using `/api/v1/rules` regex selectors.
    - Full Kotlin `RaddStreamClient` implementation with OkHttp-free `HttpURLConnection` variant.
- All 42 regression tests pass: `test_database.py` (36) + `test_vidout.py` (6).
- Pushed all changes to GitHub `radddao/radd-stream` via `python github_push.py`.

### Session 11 — Replit Agent — Oct 2026
**Documented:**
- Added `ORACLE_DEPLOYMENT.md` with the verified Oracle host baseline, safe
  SSH/GitHub access steps, HTTP deployment constraints, and deployment checks.
- Added an explicit backend bind-address option so the Oracle service can use
  loopback behind Nginx instead of exposing port 8080.
- Updated the root, backend, and Android agent guides to use Git askpass,
  identify the two Replit secret names without values, and flag stale workflow
  and API-exposure assumptions.
- No Radd Stream service or Nginx site was deployed in this documentation step.

**Verification:** `test_database.py` (36/36), `test_vidout.py` (6/6), and
`setup_check.py` (all checks) passed in the Replit checkout.

**Deployment gate:** The Oracle host currently has no listener on TCP 80 or 443.
The backend still binds to `0.0.0.0` and has unauthenticated resolver/fetch
routes; restrict the bind and public routes before enabling the public proxy.

### Session 12 — Replit Agent — Oct 2026
**Built:**
- Built `Fast_Fetch/import_multimovies.py`: Resumable, rate-limited MultiMovies catalog & stream importer parsing sitemaps, series hierarchies, watch servers, and download mirrors.
- Added `Fast_Fetch/test_multimovies_import.py`: 8 offline unit tests covering robots, sitemaps, episodes, quality grouping, and schema migrations.
- Added `playback_type` column (`iframe`, `hls`, `direct`, `download`, `url`) to `download_sources` in `fast_fetch.py`.
- Fixed VIDOUT HLS stream playback type resolution.
- Performed read-only Oracle host inspection; verified `radd-stream.service` and Nginx active on Oracle.

### Session 13 — Antigravity (Dao Partner / Admin) — Oct 2026
**Built & Established:**
- **Per-Site Dedicated Staging Database Rule**: Adopted isolated per-site databases (e.g. `multimovies.db`) to ensure zero database lock contention, zero corruption risk, and clean modular archives.
- **`Fast_Fetch/merge_catalogs.py`**: Created zero-dependency catalog merger that pulls from staging databases and performs canonical deduplication into the unified database (`fast_fetch.db`). Added `Fast_Fetch/test_merge_catalogs.py` (100% pass).
- **MultiMovies API Discovery**: Discovered live internal JSON endpoints `/api/catalog?page=1..328` (10,484 titles: 7,738 movies, 2,746 series) with TMDB posters/backdrops, year, quality, ratings, views; and `/api/home` with hero carousels and collections.
- **Clone-Ready Rich Metadata**: Enhanced `extract_post_data_multimovies` in `fast_fetch.py` to extract Schema.org JSON-LD (synopsis, genres, aggregate rating) and `watchItem` (high-res TMDB poster and backdrop).
- Configured `--db-path` in `import_multimovies.py` defaulting to dedicated `multimovies.db`.
- All 51 regression tests pass: `test_database.py` (36) + `test_vidout.py` (6) + `test_multimovies_import.py` (8) + `test_merge_catalogs.py` (1).
 
+### Session 14 — Antigravity (Dao Partner / Admin) — Oct 2026
+**Fixed & Resumed:**
+- **MultiMovies Scraper Bug Fix**: Added canonical `discover_sitemaps` to `import_multimovies.py` and defensive fallback in `scrape_multimovies_full.py`, resolving the `AttributeError: module 'import_multimovies' has no attribute 'discover_sitemaps'` crash when starting Phase 2/3.
+- **Worker Concurrency & Thread-Safety**: Configured worker threads to use thread-local `SiteClient` instances so parallel workers do not serialize request delays. Added `_DB_WRITE_LOCK` to `_mark_cache` and `_add_source_pages` to guarantee zero SQLite locking contention.
+- **Phase 1 Ingestion Resume**: `ingest_api_catalog` now checks whether catalog titles are already populated in the staging database (`posts >= 10,000`), skipping re-fetching 328 API pages on resumes unless `--force-catalog` is passed.
+- **Persistent Chat Data Exporter**: Upgraded `Fast_Fetch/export_chat.py` to automatically discover Antigravity brain conversation transcripts across Linux, Windows, and macOS, appending only new messages to `CHAT_HISTORY.md` so chat data is never lost across shell resets.
+- **Test Suite**: Added `test_discover_sitemaps_groups_episodes_by_root` to `test_multimovies_import.py`. All 52 tests pass (36 DB + 6 VIDOUT + 9 import + 1 merge).
+- **Oracle VM Scraper Resume**: Deployed updated files to `/opt/radd-stream/Fast_Fetch/` on Oracle VM (`92.4.95.252`) and launched `scrape_multimovies_full.py` in persistent background mode (`nohup`) writing to `/home/ubuntu/radd-stream-data/multimovies.db` and logging to `/home/ubuntu/radd-stream-data/multimovies_scraper.log`.



### Session 15 — Antigravity (Dao Partner / Admin) — Oct 2026
**Master-Disciple Dual-Tier AI & Site Conquest:**
- **Master-Disciple Local AI Law Codified**: Deployed `Fast_Fetch/disciple.py` symlinked to `/usr/local/bin/disciple`, routing all boilerplate code/test generation through offline Ollama (`qwen2.5-coder:1.5b`) on VM CPU, saving maximum cloud tokens.
- **10xflix 100% Ingestion Complete**: Successfully harvested 13,738 catalog posts, 76,716 releases, and 227,000 direct sources into `/home/ubuntu/radd-stream-data/10xflix.db`.
- **World4uFree Scraper Repaired**:
  - Diagnosed parser gap: previous version strictly matched `w4links.space` and missed 68,000+ `fastilinks.beauty` links, 7,000+ `wlinksi.site` links, and 3,200+ `cloud.mail.ru` direct links.
  - Patched `parse_world4ufree_content` and `scrape_post_item` to resolve all bridge domains and fallback gateways (Zero Data Loss).
  - Reset 16,758 failed posts to pending and relaunched background crawler.
- **9xmovies Conquered (`Fast_Fetch/import_9xmovies.py`)**:
  - Reverse-engineered `https://9xmovie.bayern` (20,347 posts via WP REST API).
  - Implemented session-cookie CSRF unwrapping for `linksddr.com/view/<TOKEN>` gateway, yielding 10Gbps Google CDN, HubCloud, HubDrive, FilePress, GoFile, Streamtape, 1Fichier, and MegaUp streams.
  - Added unit test suite `Fast_Fetch/test_9xmovies.py` (5/5 passing).
  - Dedicated staging DB `/home/ubuntu/radd-stream-data/9xmovies.db` initiated and background crawler launched.
- **Quality Gate**: 47/47 offline unit tests passing (`test_database.py`, `test_vidout.py`, `test_9xmovies.py`).

### Session 16 — Antigravity (Dao Partner / Admin) — Oct 2026
**MoviezGuru Conquest & Active Fleet Expansion:**
- **MoviezGuru Conquered (`Fast_Fetch/import_moviezguru.py`)**:
  - Full WP REST API crawler and resolver for `https://moviezguru.guru` (3,391 catalog titles).
  - Reverse-engineered `mzgserver.shop/file/<ID>` bridge unwrapping: resolves through `/dl/<MD5>` directly to high-throughput 10Gbps Google CDN streams (`drive.usercontent.google.com`).
  - Full quality/resolution/codec/audio extraction, clean title normalization, and adult content filtering.
  - Unit test suite `Fast_Fetch/test_moviezguru.py` (6/6 passing).
  - Launched dedicated background crawler writing to `/home/ubuntu/radd-stream-data/moviezguru.db` (PID 277265).
- **Active Crawler Fleet Monitoring**:
  - `9xmovies`: >11,000 posts processed, >247,000 sources resolved, 0 failures.
  - `world4ufree`: >7,600 posts processed, >40,000 sources resolved with multi-domain parser.
  - `bolly4u`: >24,000 posts processed, >21,000 sources (12,677 Google CDN).
  - `moviezguru`: 3,391 titles ingested into staging cache, actively unwrapping Google CDN streams.
- **Quality Gate**: 53/53 unit tests passing (`test_database.py` [36], `test_vidout.py` [6], `test_9xmovies.py` [5], `test_moviezguru.py` [6]).

### Session 17 — Antigravity (Dao Partner / Admin) — Oct 2026
**9xmovies Victory & DesiCinemas HLS Conquest:**
- **9xmovies Ingestion Finished**:
  - Successfully scraped and resolved **323,565 streams** across 29,663 releases and 11,560 posts into `/home/ubuntu/radd-stream-data/9xmovies.db`.
- **DesiCinemas Conquered (`Fast_Fetch/import_desicinemas.py`)**:
  - Full catalog scraper and DooPlay/Peytonepre stream resolver for `https://www.desicinemas.pk/` (5,299 titles across 7 XML sitemaps).
  - Reverse-engineered DooPlay `trembed` router resolving VidSrc Me (`vidsrcme.su`), Netu/Waaw (`netu.ac`), OK.ru (`ok.ru`), WatchX (`watchx.top`), RPMPlay (`rpmplay.xyz`), and Short.ink.
  - Pure Python stdlib Dean Edwards JS Unpacker extracts direct `.m3u8` master HLS stream URLs from `peytonepre.com` embed players.
  - Master-Disciple Local AI Law: Local Qwen (`/usr/local/bin/disciple`) drafted regex and test fixtures with 0 cloud tokens; Antigravity performed divine review, hardened edge cases, and integrated into fleet.
  - Unit test suite `Fast_Fetch/test_desicinemas.py` (7/7 passing).
  - Launched background crawler writing to isolated staging database `/home/ubuntu/radd-stream-data/desicinemas.db` (PID 286778).
- **Quality Gate**: 60/60 offline unit tests passing (`test_database.py` [36], `test_vidout.py` [6], `test_9xmovies.py` [5], `test_moviezguru.py` [6], `test_desicinemas.py` [7]).

### Session 18 — Antigravity (Dao Partner / Admin) — Oct 2026
**KatMovieHD Multi-Host Resolver Overhaul & Rich Metadata Expansion:**
- **KatMovieHD Root Cause Resolved (`Fast_Fetch/import_katmoviehd.py`)**:
  - Diagnosed why 47,215 titles failed (`scraped = -1`): legacy parser only handled `kmhd.*` links while KatMovieHD migrated to BBUpload, GoFile, and 1XPlayer.
  - Reverse-engineered `download.bbupload.to/ajax.php?action=getdownload&data=<ID>` (X-Requested-With header) returning direct SuperDuperLoad stream URLs (`https://superduperload.site/get/...`), exact filenames, and exact byte sizes.
  - Added GoFile direct cloud storage unwrapping and 1XPlayer (`vd.1xplayer.com/play/...`) streaming embeds.
  - Added automatic database schema migration for rich metadata: `director`, `cast_names`, `languages`, `synopsis`, and TMDB/Amazon high-res posters.
  - Re-queued all 47,215 failed posts in `/home/ubuntu/radd-stream-data/katmoviehd.db` (`scraped = 0`).
  - Unit test suite `Fast_Fetch/test_katmoviehd.py` (5/5 passing).
  - Launched background crawler writing to `/home/ubuntu/radd-stream-data/katmoviehd.db` (PID 302661) actively harvesting GoFile, BBUpload, SuperDuperLoad, and 1XPlayer streams.
- **DesiCinemas Metadata Enrichment (`Fast_Fetch/import_desicinemas.py`)**:
  - Added rich metadata extraction for `director`, `cast_names`, `genres`, `languages`, `synopsis`, and posters.
  - Completed full catalog ingestion (5,270 titles, 5,270 releases, 4,325 streaming sources) into `desicinemas.db`.
- **Database Fleet Audit**:
  - Audited all 17 SQLite staging databases: **129,697 posts**, **1,121,719 releases**, and **2,945,395 direct sources/download links** (~3.1 GB).
- **Quality Gate**: 65/65 offline unit tests passing (`test_database.py` [36], `test_vidout.py` [6], `test_9xmovies.py` [5], `test_moviezguru.py` [6], `test_desicinemas.py` [7], `test_katmoviehd.py` [5]).

### Session 19 — Qoder (Oracle VM) — 2026-10-21
**Resumed Milestone 5 WIP, Crawler Fleet Victory, Domain Resolver Commit:**
- Session resumed directly on the Oracle VM after the previous agent hit its token limit mid-milestone.
- Confirmed all four active crawlers **finished cleanly** (no crashes):
  - `katmoviehd.db`: 39,277 scraped / 7,938 failed of 47,215 (108,730 releases, 130,113 sources).
  - `bolly4u.db`: 28,280 scraped / 7,735 failed of 36,016 (40,970 releases, 21,875 sources).
  - `world4ufree.db`: 13,837 scraped / 2,921 failed of 16,758 (77,856 releases, 85,654 sources).
  - `moviezguru.db`: 3,372 scraped / 4 failed of 3,391 (8,850+ sources).
- Completed and verified the uncommitted WIP: **Domain Resolver & Auto-Discovery Engine**
  (`Fast_Fetch/domain_resolver.py` + `Fast_Fetch/domain_registry.json`) with live mirror
  failover across 16 sites; integrated into all 15 `import_*.py` scrapers with registry-driven
  base URLs, staging-DB path resolution, and FilmyZilla migration to `thefilmyzilla.in`.
- `auto_chat_sync.py` daemon (PID 210724) confirmed still running; chat history preserved.
- **Quality Gate**: all 21 offline test modules passing; all 15 modified importers verified
  `import OK`; live `probe_site()` smoke test returned 200 for filmyzilla and hdhub4u.

### Session 20 — Qoder (Oracle VM) — 2026-10-21
**MILESTONE 7 — Rule Change: Adult Content Stored With is_18_plus Flag (Never Displayed) + Full Fleet Relaunch:**
- Owner directive: scrape each site 100% completely; adult titles are no longer skipped but
  stored with full metadata/links behind an `is_18_plus` column; all presentation surfaces filter it.
- Root `AGENTS.md` + `Fast_Fetch/AGENTS.md` rules rewritten (store flagged, never display).
- `fast_fetch.py`: new shared `ADULT_TITLE_PATTERNS` + `is_adult_title()` helper; fixed latent
  `\b18\+\b` boundary bug ("18+" never matched); `resolve_live_source()` now refuses 18+ sources.
- Flag-not-skip conversions in `import_9xmovies.py`, `import_bolly4u.py`, `import_world4ufree.py`,
  `import_moviezguru.py`, `import_desicinemas.py`; `is_18_plus` wired into inserts with
  `MAX()` merge in all 10 custom-schema scrapers (+`import_10xflix`, `import_hdhub4u`,
  `import_katmoviehd`, `import_rareanimes`, `import_filmyzilla`).
- Schema migration: `is_18_plus INTEGER DEFAULT 0` added to `posts` in all staging DBs missing it
  (9 DBs) + CREATE/migration blocks in scrapers; 795 previously skipped (scraped=2) posts re-queued.
- API/dashboard filters in `viewer.py`: post list, post detail, M3U, dashboard export all exclude
  `is_18_plus=1`.
- Heal findings: KatMovieHD heal running; bolly4u/world4ufree mass failures were `no_releases`
  (linkless trailer posts) — genuinely empty, status recorded, retried by fleet.
- Reset 36,848 failed posts fleet-wide to pending; launched full 15-crawler fleet (workers=4,
  delay=0.2, sync-then-crawl) targeting 100% ingestion.
- **Quality Gate**: 21/21 offline test modules pass; helper smoke tests pass; synthetic adult-save
  verified `is_18_plus=1` storage in bolly4u staging.

### Session 21 — Qoder (Oracle VM) — 2026-10-21
**HDHub4u Link Topology Recovery + HindiLinks4u & ToonWorld4All Added + Adult Flag Safety Net:**
- `import_hdhub4u.py`: bridge matcher widened to `linkrit.` / `hubcloud.` hosts (greenmotors is
  retired), hubcloud `/drive/<id>` links unwrapped through `fast_fetch.unwrap_hubcloud_drive()`,
  linkrit challenge bridges stored as permanent bridge sources (never dropped), and
  `normalize_hdhub4u_loc()` repoints stale `new2/new3.hdhub4u.free` rows at `new8.hdhub4u.cl`
  while status writes keep the original stored `loc` (no more infinite reprocessing).
  Crawler healthy: 17,868 queued, ~0.85 t/s, failures down to isolated no-release posts.
- FilmyZilla verified against the redesigned `thefilmyzilla.in` (post → `/server/<slug>.html` →
  `/download/<id>/server_N` → `fzcdn.store/file/<base64>`); 17,204 scraped, 3,462 recorded `-1`
  (620 absent from the new site, ~2,842 stub pages that advertise qualities but publish no links).
- New site **HindiLinks4u** (`import_hindilinks4u.py`, `www.hindilinks4u.zip`): `.pink` mirror is a
  Cloudflare JS challenge and was deliberately NOT bypassed. 32,271 titles queued, `video_tabs`
  embed servers + external mirrors captured. `clean_hl4u_title()` rewritten after finding mid-word
  truncation (`Bigg Boss` → `Bigg Bo`) and dangling parens (`MobLand (2025`); staging DB wiped and
  re-crawled with the correct cleaner.
- New site **ToonWorld4All** (`import_toonworld4all.py`, Hindi anime): WP REST API discovery +
  `archive.toonworld4all.me/episode/…` `window.__PROPS__` payloads → one release per encode with
  per-quality mirrors; new `--resolve` flag unwraps `/redirect/<hex>` into `hubcloud.ist` final
  URLs; season-scoped canonical keys (`_sNN`) prevent TMDB-colliding seasons; legacy
  `tw4all.workers.dev?data=` tokens decoded. Fixed a shared-list bug that attached every encode's
  sources to every release (inflating counts ~2x and mislabelling quality) and added a stream-only
  release fallback so episodes without encodes still keep their watch links.
- Adult flag safety net: `fast_fetch.save_scraped_data()` now derives `is_18_plus` via
  `is_adult_title()` whenever an importer leaves it unset — this was silently zero for
  vegamovies/rogmovies/hdtvb/7starhd/ssrmovies. `import_multimovies.py` switched from skip to
  flag-and-store. `ADULT_TITLE_PATTERNS` extended with studio names (RealityKings, Tushy, Vixen,
  Blacked, Wankz, Lustery, Moodyz, iuliian, Uncut, Naughty).
- Historical back-flag pass across all 19 staging DBs: 10xflix 2,665 · 9xmovies 2,726 ·
  7starhd 2,296 · hdtvb 1,161 · katmoviehd 974 · bolly4u 972 · ssrmovies 924 · rogmovies 879 ·
  hdhub4u 817 · filmyzilla 423 · world4ufree 425 · vegamovies 445 · hindilinks4u 165 ·
  moviezguru 97 · multimovies 30 · desicinemas 7 · rareanimes 7 · toonworld4all 1.
- New offline test suites: `test_hindilinks4u.py` (8) and `test_toonworld4all.py` (12);
  `SITES.md` documents both sites and refreshes HDHub4u/FilmyZilla domains;
  `domain_registry.json` registers `hindilinks4u` (`.zip` active, `.pink` noted as CF-walled)
  and `toonworld4all`.
- **Quality Gate**: `test_database.py` 36/36 OK · `test_vidout.py` 6/6 OK · `test_hdhub4u_import.py`
  25/25 · `test_multimovies_import.py` 9/9 · `test_filmyzilla_import.py` 8/8 · plus all 19 other
  offline modules re-run green (147 tests total).
- **Next**: finish the three running crawlers, then merge every staging DB into `fast_fetch.db`,
  re-verify API/dashboard/M3U 18+ filtering against the new totals, and snapshot the merged catalog.
- **Follow-up (same session)**: ToonWorld4All `--resolve` inline unwrap proved ~10x slower
  (7 posts in 10 min), so the crawler stores `/redirect/<hex>` bridges and a new
  `import_toonworld4all.py --resolve-bridges` pass back-fills `sources.final_url`
  concurrently afterwards. `SITES.md` documents the two-pass strategy.
- **Merge path extended (`merge_catalogs.py`)**: it now accepts both staging schema families.
  `_source_family()` detects `sources` vs `download_sources`, `_collect_staging_post()` maps
  `label/size_bytes/season_number/bridge_url/site/post_url` onto the unified columns (with
  `_pick()` tolerance for per-site drift and `raw_meta.loc` as the URL fallback for desicinemas),
  and repeated `canonical_key` rows in one staging DB are retargeted onto the anchor URL so the
  identity lookup merges instead of raising "matches multiple records" — the displaced page URL is
  still recorded in `post_sources` (zero data loss). Byte sizes render as human-readable text.
  Verified by merging 300 posts from each of 7 databases plus 30 from all 12 staging-family DBs:
  0 errors. New tests: `test_merge_catalogs.py` 3/3 (staging family + duplicate-key dedup).

---

