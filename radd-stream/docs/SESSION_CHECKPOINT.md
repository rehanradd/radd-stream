# Session checkpoint

Update this file after each independently verified milestone so work can resume across accounts, tools, and usage limits.

## Current checkpoint — 2026-10-19

### Mandatory staging-database merge gate

Never merge a staging database into the unified or Oracle catalog unless the
user explicitly requests that specific merge in the current conversation.
Crawler completion, successful tests, and earlier checkpoint text are not
authorization. Before any merge, give the user the exact source database(s),
target, current row counts, and verified backup/rollback plan and obtain a
separate explicit confirmation. The guarded CLI also requires
`--owner-authorized`. If confirmation is absent or unclear, stop.

- **Goal:** Launch KatMovieHD scraper on Oracle VM in background, diagnose RareAnimes failures, and preserve strict staging database isolation.
- **Milestones & Breakthroughs:**
  1. **Previous Crawler Completions Verified**:
     - Vegamovies: Completed 100% of available valid items (13,978 / 14,316 scraped, 131,654 releases, 397,888 direct sources, 85,138 Google CDN direct streams).
     - 7StarHD: Completed current batch (15,508 / 23,446 scraped, 33,197 releases, 98,199 direct sources).
     - HDHub4u: Completed current batch (10,893 scraped, 47,361 releases, 103,964 direct sources).
     - RareAnimes: Completed initial pass (1,329 scraped, 17,419 releases, 53,767 direct sources, 20,283 PixelDrain direct CDN, 4,219 Cloudflare R2).
  2. **KatMovieHD Background Deployment on Oracle VM**:
     - Pre-tested SvelteKit deserializer and crawler locally on test database (100% pass).
     - Initiated background deployment on Oracle VM (PID 139975 / 139977) streaming unbuffered logs to `/home/ubuntu/radd-stream-data/katmoviehd.log`.
     - Automatically running `--sync-api` followed by multi-threaded crawler (`--workers 5 --delay 0.3`) into isolated staging DB `/home/ubuntu/radd-stream-data/katmoviehd.db`.
     - Live progress monitor verified functional via `python3 check_katmoviehd.py`.
  3. **RareAnimes Failure Diagnosis (1,295 Failed Titles)**:
     - 698 failures caused by master index regex: `sync_master_movies_index` parsed global HTML links from `/all-anime-cartoon-movies-list/` without scoping to `#rai-movies-index`, ingesting non-post URLs (.css, .png, feeds, xmlrpc.php).
     - 597 failures caused by intermediate link bridge types: posts containing `store.animetoonhindi.com/archives/...` and `codedew.com/zipcloud/...` as well as `<h3>` heading tags for episode blocks were not resolved by the initial pattern matcher.
  4. **Strict DB Isolation Maintained**: Zero merges executed into production `fast_fetch.db`.
- **Next action:** Monitor KatMovieHD crawler (`python3 check_katmoviehd.py`) and patch RareAnimes scraper regex & bridge resolution.

## 2026-10-18 — RareAnimes Scraper Launch & Multi-Crawler Operations

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
