# Session checkpoint

Update this file after each independently verified milestone so work can resume across accounts, tools, and usage limits.

## Current checkpoint — 2026-10-21 (Milestone 7)

- **Goal:** Rule change per owner directive — scrapers no longer skip adult content; 100% of each site's catalog is stored with full metadata/links behind an `is_18_plus` flag column in every staging database; every presentation surface (REST API, dashboard, M3U, stream resolver, Android app) filters `is_18_plus=1`.
- **Completed:**
  1. Rules rewritten in root `AGENTS.md` and `Fast_Fetch/AGENTS.md` (store flagged, never display).
  2. `fast_fetch.is_adult_title()` shared helper added (fixed latent `\b18\+\b` regex bug); `resolve_live_source()` blocks 18+ source ids.
  3. Flag-not-skip conversion in 5 scrapers; `is_18_plus` inserted (MAX-merged) in all 10 custom-schema scrapers; CREATE + ALTER migrations in each.
  4. All 16 staging DBs now carry `posts.is_18_plus`; 795 previously skipped adult posts re-queued; 36,848 failed posts reset to pending fleet-wide.
  5. `viewer.py` API/dashboard/M3U filters exclude flagged rows.
- **Checks run:** 21/21 offline test modules; import checks; helper smoke tests; synthetic adult-save verified.
- **Fleet:** 15 scrapers relaunched at full speed (sync-then-crawl, workers=4, delay=0.2); KatMovieHD heal still running from earlier.
- **Next action:** Monitor fleet to completion, verify per-site `is_18_plus=1` counts, snapshot databases to Hugging Face.

## Previous checkpoint — 2026-10-21 (Milestone 6)


- **Goal:** Resume the token-limited Milestone 5 session directly on the Oracle VM, finish and verify the in-progress Domain Resolver & Auto-Discovery Engine, and record crawler fleet completion.
- **Completed:**
  1. **Crawler fleet victory confirmed** — all four Milestone 5 crawlers finished cleanly: KatMovieHD (39,277 scraped / 7,938 failed, 130,113 sources), Bolly4U (28,280 scraped, 21,875 sources), World4uFree (13,837 scraped, 85,654 sources), MoviezGuru (3,372 scraped, 8,850+ sources).
  2. **Domain Resolver & Auto-Discovery Engine landed** (`Fast_Fetch/domain_resolver.py` + `domain_registry.json`): registry-driven live domain tracking, redirect-following `probe_site()`, mirror auto-failover across 16 sites, integrated into all 15 `import_*.py` scrapers; FilmyZilla migrated to `thefilmyzilla.in`, HDHub4u to `new8.hdhub4u.cl`, Bolly4U to `bolly4uv.com`, 10xflix to `10xflix.hair`, 7StarHD to `7starhd.dentist`, SSMMovies to `ssrmovies.surf`, MultiMovies to `m1.multimovies.courses`, Vegamovies to `new1.vegamovies.lease`, KatMovieHD to `new.katmoviehd.top`.
  3. **Quality Gate:** all 21 offline test modules pass; all modified importers import cleanly; live `probe_site()` smoke test 200 OK for filmyzilla and hdhub4u.
  4. `auto_chat_sync.py` (PID 210724) confirmed continuously persisting chat to `Fast_Fetch/CHAT_HISTORY.md`.
- **Next action:** Retry-failed posts on katmoviehd/bolly4u/world4ufree (heal pass), snapshot databases to Hugging Face, expand remaining scrapers (`import_9xmovies.py`, `import_10xflix.py`, `import_hdhub4u.py`) for cast/director/synopsis extraction.

## Previous checkpoint — 2026-10-20 (Milestone 5)

- **Goal:** Overhaul KatMovieHD crawler (`import_katmoviehd.py`) with modern multi-host support (BBUpload, GoFile, 1XPlayer, SuperDuperLoad), enrich DesiCinemas with cast/director metadata, and audit database fleet.
- **Architectural Breakthroughs & Deployments:**
  1. **KatMovieHD Root Cause Resolved & Overhauled (`Fast_Fetch/import_katmoviehd.py`)**:
     - Diagnosed why 47,215 titles failed (`scraped = -1`): site migrated from legacy `kmhd.*` links to `bbupload.to`, `gofile.io`, and `1xplayer.com`.
     - Reverse-engineered `download.bbupload.to/ajax.php?action=getdownload&data=<ID>` with `X-Requested-With` header: yields direct `https://superduperload.site/get/...` stream URLs, exact filenames, and exact file sizes in bytes with zero Cloudflare Turnstile blocks.
     - Added direct GoFile cloud storage unwrapping and 1XPlayer (`vd.1xplayer.com/play/...`) streaming embeds.
     - Added rich metadata extraction: `director`, `cast_names`, `genres`, `languages`, `synopsis`, and Amazon/TMDB posters.
     - Auto-migrated `katmoviehd.db` `posts` table with `director`, `cast_names`, and `languages` columns.
     - Re-queued 47,215 failed posts in `/home/ubuntu/radd-stream-data/katmoviehd.db` (`scraped = 0`).
     - Added unit tests in `Fast_Fetch/test_katmoviehd.py` (5/5 passing).
     - Launched background crawler writing to `/home/ubuntu/radd-stream-data/katmoviehd.db` (PID 302661).
  2. **DesiCinemas Metadata Enrichment (`Fast_Fetch/import_desicinemas.py`)**:
     - Completed full catalog ingestion (5,270 titles, 5,270 releases, 4,325 streaming sources) into `desicinemas.db`.
     - Added extraction for `director`, `cast_names`, `genres`, `languages`, and `synopsis`.
     - Unit tests in `Fast_Fetch/test_desicinemas.py` (7/7 passing).
  3. **Database Fleet Audit**:
     - Audited all 17 SQLite staging databases: **129,697 posts**, **1,121,719 releases**, and **2,945,395 direct sources/download links** (~3.1 GB).
  4. **Active Crawler Fleet Status**:
     - `bolly4u.db` (PID 161377): >26,300 processed, >35,500 releases, 21,875 sources (12,677 Google CDN).
     - `world4ufree.db` (PID 249172): >10,500 processed, >55,700 releases, >63,500 sources.
     - `moviezguru.db` (PID 277265): >600 processed, >1,290 releases, >1,670 sources.
     - `katmoviehd.db` (PID 302661): re-crawling 47,215 titles with BBUpload, GoFile, and 1XPlayer streams.
     - `auto_chat_sync.py` (PID 210724): continuous real-time chat persistence.
  5. **Quality Gate**: 65/65 offline unit tests passing (`test_database.py` [36], `test_vidout.py` [6], `test_9xmovies.py` [5], `test_moviezguru.py` [6], `test_desicinemas.py` [7], `test_katmoviehd.py` [5]).
- **Next action:** Expand remaining scrapers (`import_9xmovies.py`, `import_10xflix.py`, `import_hdhub4u.py`) for cast/director/synopsis extraction, snapshot databases to Hugging Face, and analyze FilmyZilla expansion.

## Previous checkpoint — 2026-10-20 (Milestone 4)

- **Goal:** Complete 9xmovies ingestion, conquer DesiCinemas scraper (`desicinemas.pk`) with Dean Edwards packed HLS unwrapper, and expand concurrent crawler fleet.
- **Architectural Breakthroughs & Deployments:**
  1. **9xmovies Ingestion Finished**:
     - Completed crawling `https://9xmovie.bayern` yielding **323,565 streams** across 29,663 releases and 11,560 posts stored in `/home/ubuntu/radd-stream-data/9xmovies.db`.
  2. **DesiCinemas Conquered (`Fast_Fetch/import_desicinemas.py`)**:
     - Automated sitemap ingestion across 7 Yoast XML sitemaps (5,299 URLs queued).
     - Reverse-engineered DooPlay `trembed` router: unwraps VidSrc Me, Netu/Waaw, OK.ru, WatchX, RPMPlay, Short.ink.
     - Built pure Python stdlib Dean Edwards JS unpacker (`unpack_dean_edwards`) resolving `peytonepre.com` packed players directly to `.m3u8` master HLS playlist streams.
     - Unit test suite `Fast_Fetch/test_desicinemas.py` (7/7 passing).
     - Background crawler launched in staging isolation `/home/ubuntu/radd-stream-data/desicinemas.db` (PID 286778).
  3. **Master-Disciple Dual-Tier Workflow Verified**: Delegated title cleaning and test stubs to local offline Qwen (`/usr/local/bin/disciple`) saving cloud tokens, followed by divine review and hardening.
  4. **Active Crawler Fleet Status**:
     - `9xmovies.db`: 323,565 streams (100% finished).
     - `moviezguru.db` (PID 277265): actively unwrapping 10Gbps Google CDN streams.
     - `world4ufree.db` (PID 249172): >8,200 posts, >46,600 sources.
     - `bolly4u.db` (PID 161377): >24,400 posts, >21,800 sources.
     - `desicinemas.db` (PID 286778): 5,299 catalog titles, actively resolving HLS and player embeds.
  5. **Quality Gate**: 60/60 offline unit tests passing (`test_database.py` [36], `test_vidout.py` [6], `test_9xmovies.py` [5], `test_moviezguru.py` [6], `test_desicinemas.py` [7]).
- **Next action:** Monitor active crawlers, prepare Hugging Face backup snapshot, and identify next site.

## Previous checkpoint — 2026-10-20 (Milestone 3)

- **Goal:** Launch MoviezGuru crawler (`import_moviezguru.py`), maintain concurrent crawler fleet on Oracle VM, and track staging database ingestion metrics.
- **Architectural Breakthroughs & Deployments:**
  1. **MoviezGuru Conquered (`Fast_Fetch/import_moviezguru.py`)**:
     - WP REST API ingestion for `https://moviezguru.guru` (3,391 titles).
     - Reverse-engineered `mzgserver.shop/file/<ID>` bridge unwrapping: resolves through `/dl/<MD5>` directly to high-throughput 10Gbps Google CDN streams (`drive.usercontent.google.com`).
     - Added comprehensive unit tests in `Fast_Fetch/test_moviezguru.py` (6/6 passing).
     - Background crawler launched in staging isolation `/home/ubuntu/radd-stream-data/moviezguru.db` (PID 277265).
  2. **Active Crawler Fleet Expansion**:
     - `bolly4u.db` (PID 161377): >24,000 titles, >21,000 sources (12,677 10Gbps Google CDN).
     - `world4ufree.db` (PID 249172): >7,600 titles, >40,000 sources (multi-domain parser active).
     - `9xmovies.db` (PID 261855): >11,000 titles, >247,000 sources resolved, 0 failures.
     - `moviezguru.db` (PID 277265): 3,391 titles synced, actively unwrapping Google CDN streams.
     - `auto_chat_sync.py` (PID 210724): continuous real-time chat persistence.
  3. **Quality Gate**: 53/53 unit tests passing (`test_database.py` [36], `test_vidout.py` [6], `test_9xmovies.py` [5], `test_moviezguru.py` [6]).
- **Next action:** Analyze and conquer DesiCinemas (`desicinemas.pk`) or next target site.

## Previous checkpoint — 2026-10-20 (Milestone 2)

- **Goal:** Repair World4uFree multi-domain parser gap, conquer 9xmovies scraper (`9xmovie.bayern`), demonstrate Master-Disciple local AI law via Ollama Qwen 1.5B, and run concurrent crawler cluster.
- **Architectural Breakthroughs & Deployments:**
  1. **Master-Disciple AI Delegation**: Used local offline Qwen (`/usr/local/bin/disciple`) to draft function signatures, title cleaning, regex patterns, and test suites, preserving cloud tokens. Reviewed and tested before integration.
  2. **World4uFree Parser Repair & Re-crawl**: Diagnosed why 16,758 posts failed (parser only matched `w4links.space` and ignored 68,000+ `fastilinks.beauty`, 7,000+ `wlinksi.site`, and 3,200+ `cloud.mail.ru` links). Added multi-domain link extraction and fallback gateway preservation (Zero Data Loss). Reset 16,758 posts and resumed crawler in background (PID 249172).
  3. **9xmovies Conquered (`Fast_Fetch/import_9xmovies.py`)**: Built full WP REST API crawler for `https://9xmovie.bayern` (20,347 posts). Reverse-engineered `linksddr.com/view/<TOKEN>` session-cookie CSRF unwrapping yielding direct 10Gbps Google CDN, HubCloud, HubDrive, FilePress, GoFile, Streamtape, 1Fichier, and MegaUp streams. Dedicated staging DB `/home/ubuntu/radd-stream-data/9xmovies.db`. Launched background crawler (PID 250953).
  4. **Active Crawler Cluster on Oracle VM**:
     - `import_bolly4u.py` (PID 161377): 20,880+ titles, 30,000+ releases.
     - `import_world4ufree.py` (PID 249172): re-crawling 16,758 posts with multi-domain parser.
     - `import_9xmovies.py` (PID 250953): syncing 20,347 posts & crawling unwrapped streams.
     - `auto_chat_sync.py` (PID 210724): real-time chat persistence active.
  5. **Unit Test Quality Gate**: 47/47 offline unit tests pass (36 `test_database` + 6 `test_vidout` + 5 `test_9xmovies`).
- **Next action:** Monitor active crawlers, proceed to analyze and conquer next streaming site or address `katmoviehd` content extraction.

- **Goal:** Implement local Master-Disciple AI workflow via Ollama `qwen2.5-coder:1.5b` (`disciple.py`), repair and resume `10xflix` background crawler, deploy real-time auto chat sync daemon, and maintain strict staging database isolation.
- **Architectural Breakthroughs & Deployments:**
  1. **Master-Disciple Dual-Tier Local AI**: Implemented `Fast_Fetch/disciple.py` and `/usr/local/bin/disciple` connected to local Ollama on Oracle VM. Local Qwen drafts boilerplate, unit tests, and regex at 0 cloud token cost; Antigravity reviews and verifies.
  2. **10xflix Float Parser Fix & Resilience**: Fixed malformed size string bug (`'3.73.GB'`) in `parse_size_string` in `import_10xflix.py`. Wrapped `process_item` and worker results in exception guards to prevent worker aborts. Added unit tests in `test_10xflix_import.py`.
  3. **10xflix Crawler Resumed**: Restarted `import_10xflix.py` inside persistent detached session `tmux: crawler-10xflix` (PID 198100, 5 workers, 0.3s delay, past 6,620+ titles with 0 errors).
  4. **Real-Time Background Chat Persistence Daemon**: Created and launched `Fast_Fetch/auto_chat_sync.py` inside persistent session `tmux: chat-sync`. Continuously polls Antigravity transcript logs and appends every user/model turn directly to `Fast_Fetch/CHAT_HISTORY.md` in real-time.
  5. **Active Concurrent Crawler Cluster**: 4 crawlers concurrently operating on Oracle VM (`10xflix.db`, `world4ufree.db`, `bolly4u.db`, `katmoviehd.db`). Strict staging DB isolation maintained with zero merges into `fast_fetch.db`.
- **Verification:** 142/142 unit tests passed across 14 modules.
- **Next action:** Continue monitoring 4 background crawlers, proceed with next scraper conquest or API enhancements.

### 2026-10-17 — MultiMovies scraper resume and chat export

### 2026-10-16 — Android App MVP & CI pipeline implementation
- **Goal:** Implement full Android app flow (navigation, details, player, local favorites, settings) and establish root GitHub Actions CI.
- **Completed:**
  1. Created root `.github/workflows/ci.yml` and `.github/workflows/release.yml`.
  2. Created Unix launcher `App/gradlew` with executable permissions.
  3. Implemented Bottom Navigation Bar in `NavGraph.kt` (Home, Search, My List, Settings).
  4. Implemented `DetailScreen.kt` and `DetailViewModel.kt` supporting movies, series season filters, source resolution, and external player launch.
  5. Implemented `PlayerScreen.kt` with Media3 / ExoPlayer full-screen playback.
  6. Implemented Room local database (`FavoritePost`, `FavoriteDao`, `AppDatabase`, `DatabaseModule`, `FavoritesRepository`).
  7. Implemented `MyListScreen.kt` and `MyListViewModel.kt`.
  8. Implemented `SettingsScreen.kt` and `SettingsViewModel.kt` with live server stats.
  9. Extended `Models.kt`, `RaddStreamApi.kt`, `CatalogRepository.kt`, `PosterCard.kt`, and `ModelsTest.kt`.
- **Checks run:**
  - `python -S Fast_Fetch/test_database.py`: 36/36 passed.
  - `python -S Fast_Fetch/test_vidout.py`: 6/6 passed.
  - Live Oracle API tests: `/api/v1/posts`, `/api/v1/posts/203` (details), `/api/v1/stream?id=1` (streams), `/api/v1/stats` all return 200 HTTP OK; administrative routes remain 403 Forbidden.
- **GitHub Status:** Pushed directly to `main` (commit `e0e116e`). Rule updated per owner instruction to permit direct pushes of verified milestones to `main`.
- **Note on GitHub Actions:** GitHub API returns `Actions has been disabled for this user`. The repository has actions enabled, but user account `radddao` needs Actions re-enabled in account billing/settings.
- **Oracle Status:** Live server Nginx updated to proxy `/api/v1/posts` and `/api/v1/stream` to the local backend. Detail and playback endpoints are verified live.

### 2026-10-16 — Android APK Compilation & Server Deployment
- **Goal:** Compile native `app-debug.apk` directly on Oracle server and serve it publicly for download.
- **Completed:**
  1. Solved Google AAPT2 ARM64 binary incompatibility on Oracle by installing `qemu-user-static` and extracting AMD64 dynamic libraries (`libc6`, `libstdc++6`, `zlib1g`).
  2. Executed full Gradle build (`./gradlew assembleDebug`) compiling all Compose UI screens, Room DB, ExoPlayer, and D8/R8 bytecode packaging.
  3. Successfully compiled 21.5 MB `app-debug.apk` with exit code 0.
  4. Deployed APK to `/var/www/download/radd-stream.apk`.
  5. Verified public download endpoint: `http://92.4.95.252/download/radd-stream.apk` returns HTTP 200 OK with `Content-Disposition: attachment`.
- **Checks run:**
  - `python -S Fast_Fetch/test_database.py`: 36/36 passed.
  - `python -S Fast_Fetch/test_vidout.py`: 6/6 passed.
  - `curl -I http://92.4.95.252/download/radd-stream.apk`: HTTP/1.1 200 OK, Content-Length: 21510182.
- **Download Link:** `http://92.4.95.252/download/radd-stream.apk`

### 2026-10-21 — HDHub4u link-topology recovery + two new sites (HindiLinks4u, ToonWorld4All)

- **Goal:** Heal the last failing scrapers, add the three owner-requested sites, and make the
  adult `is_18_plus` flag reliable on every write path.
- **Completed:**
  1. **HDHub4u** (`import_hdhub4u.py`): bridge regexes now also match `linkrit.` and `hubcloud.`
     hosts (old greenmotors links are gone), hubcloud `/drive/<id>` links are unwrapped via
     `fast_fetch.unwrap_hubcloud_drive()`, unresolvable linkrit bridges are stored as bridge
     sources instead of being dropped, and `normalize_hdhub4u_loc()` repoints stale
     `new2/new3.hdhub4u.free` sitemap rows at the live `new8.hdhub4u.cl` host while status
     updates still key on the original stored `loc`.
  2. **FilmyZilla**: verified the redesign pipeline end to end on `thefilmyzilla.in`
     (post → `/server/<slug>.html` → `/download/<id>/server_N` → `fzcdn.store/file/<base64>`);
     remaining `-1` rows are 620 posts absent from the new site plus ~2,842 stub posts whose
     pages carry quality text but no download links at all. Statuses recorded, nothing discarded.
  3. **New site HindiLinks4u** (`import_hindilinks4u.py`, `www.hindilinks4u.zip`): the `.pink`
     domain is behind a Cloudflare JS challenge and was NOT bypassed; the plain-HTML `.zip`
     mirror serves the same catalog (32,271 titles queued). Rewrote `clean_hl4u_title()` to stop
     mid-word truncation ("Bigg Boss" → "Bigg Bo") and dangling-paren leaks ("MobLand (2025").
  4. **New site ToonWorld4All** (`import_toonworld4all.py`, Hindi anime): WP REST API discovery +
     `archive.toonworld4all.me/episode/…` `window.__PROPS__` payloads; one release per encode with
     per-quality mirrors, `/redirect/<hex>` unwrapped to `hubcloud.ist` final URLs via the new
     `--resolve` flag, season-scoped canonical keys (`…_sNN`), legacy `tw4all.workers.dev` tokens
     decoded. Fixed a bug where every release shared one cumulative source list (inflating source
     counts ~2x and mixing qualities) and added a stream-only release fallback.
  5. **Adult flag safety net**: `fast_fetch.save_scraped_data()` now derives `is_18_plus` from
     `is_adult_title()` for every importer that leaves it unset (vegamovies, rogmovies, hdtvb,
     7starhd, ssrmovies all wrote a literal 0). `import_multimovies.py` no longer skips restricted
     titles — it ingests them flagged. Extended `ADULT_TITLE_PATTERNS` with studio names
     (RealityKings, Tushy, Vixen, Blacked, Wankz, Lustery, Moodyz, iuliian, Uncut, Naughty).
  6. Back-flagged every existing staging row: 10xflix 2,665 · 9xmovies 2,726 · katmoviehd 974 ·
     hdhub4u 817 · bolly4u 972 · 7starhd 2,296 · world4ufree 425 · filmyzilla 423 · ssrmovies 924 ·
     hdtvb 1,161 · rogmovies 879 · vegamovies 445 · hindilinks4u 165 · moviezguru 97 ·
     desicinemas 7 · rareanimes 7 · multimovies 30 · toonworld4all 1.
  7. Registered `hindilinks4u` and `toonworld4all` in `domain_registry.json`; documented both in
     `Fast_Fetch/SITES.md` (sections 11 and 12).
- **Files changed:** `Fast_Fetch/fast_fetch.py`, `Fast_Fetch/import_hdhub4u.py`,
  `Fast_Fetch/import_multimovies.py`, `Fast_Fetch/import_hindilinks4u.py` (new),
  `Fast_Fetch/import_toonworld4all.py` (new), `Fast_Fetch/domain_registry.json`,
  `Fast_Fetch/test_hindilinks4u.py` (new, 8 tests), `Fast_Fetch/test_toonworld4all.py`
  (new, 12 tests), `Fast_Fetch/SITES.md`, `Fast_Fetch/CONTINUITY.md`, `docs/SESSION_CHECKPOINT.md`,
  crawler `*_status.json` snapshots.
- **Checks run and exact result:** `test_database.py` 36/36 OK · `test_vidout.py` 6/6 OK ·
  `test_hdhub4u_import.py` 25/25 OK · `test_multimovies_import.py` 9/9 OK ·
  `test_filmyzilla_import.py` 8/8 OK · `test_hindilinks4u.py` 8/8 OK · `test_toonworld4all.py`
  12/12 OK · every pre-existing offline test module re-run OK (21 modules, 147 tests, no network).
- **Known failures or checks not run:** `test_all_sites.py` live audit not re-run this session;
  Android app not built (no app-side change needed); no merge into `fast_fetch.db` yet.
- **GitHub branch/commit/push result:** committed to `master` and pushed (see commit below).
- **Oracle deployment result:** not deployed — code is live-source only; staging DBs remain on
  `/home/ubuntu/radd-stream-data/`.
- **Next concrete action:** let the three running crawlers finish (HDHub4u ~5h, HindiLinks4u ~2.6h,
  ToonWorld4All ~2.5h), then merge all staging catalogs into `fast_fetch.db` via the merge path,
  re-verify the API/dashboard/M3U 18+ filters against the new totals, and snapshot the merged DB.
- **Blockers / decisions needed:** Shemaroo (owner chose "skip"); owner still needs to revoke the
  GitHub credential that was exposed in an earlier session (value never recorded here).

## Template for future checkpoints

### YYYY-MM-DD — short milestone name

- **Goal:**
- **Completed:**
- **Files changed:**
- **Checks run and exact result:**
- **Known failures or checks not run:**
- **GitHub branch/commit/push result:**
- **Oracle deployment result (or why not deployed):**
- **Next concrete action:**
- **Blockers / decisions needed:**
