# Session checkpoint

Update this file after each independently verified milestone so work can resume across accounts, tools, and usage limits.

## Current checkpoint — 2026-10-18

### Mandatory staging-database merge gate

Never merge a staging database into the unified or Oracle catalog unless the
user explicitly requests that specific merge in the current conversation.
Crawler completion, successful tests, and earlier checkpoint text are not
authorization. Before any merge, give the user the exact source database(s),
target, current row counts, and verified backup/rollback plan and obtain a
separate explicit confirmation. The guarded CLI also requires
`--owner-authorized`. If confirmation is absent or unclear, stop.

- **Goal:** Deploy and launch dedicated 7StarHD scraper on Oracle VM, maintain Vegamovies execution, and uphold strict staging DB isolation.
- **Milestones & Breakthroughs:**
  1. **SSRMovies 100.0% Completion**:
     - Verified and processed the 7 legacy 2017/2018 pending rows in `/home/ubuntu/radd-stream-data/ssrmovies.db`.
     - Ingestion reached **100.0% (27,000 / 27,000 titles)** with 0 pending.
     - Final metrics: 13,905 catalog posts, 46,115 releases, 664,469 direct sources (24,472 Google CDN, 2,907 Cloudflare R2, 14,345 watch streams).
  2. **Rogmovies 100.0% Completion**:
     - Audited all 28 review rows (`scraped = -1`) in `/home/ubuntu/radd-stream-data/rogmovies.db`. Confirmed trailer/promo/collection status with 0 releases.
     - Marked all 28 audited rows as scraped; Rogmovies reached **100.0% (7,868 / 7,868 titles)** with 0 pending.
     - Final metrics: 7,740 catalog posts, 55,273 releases, 199,655 direct sources (34,723 Google CDN direct streams).
  3. **Vegamovies Live Crawler Progress**:
     - Vegamovies (PID 76635; `--workers 5 --delay 0.3`) remains active and uninterrupted on Oracle.
     - Progress reached **84.5%** (12,091 / 14,316 titles, 101,640 releases, 319,096 direct sources, 68,000+ Google CDN direct streams).
     - Pending titles down to 1,994 (under 2,000 remaining).
  4. **7StarHD / 10xflix Deployed and Running Live on Oracle**:
     - Oracle host key independently verified against fingerprints in `ORACLE_DEPLOYMENT.md` (RSA, ECDSA, ED25519 all matched).
     - Deployed `fast_fetch.py`, `import_7starhd.py`, and `test_7starhd_import.py` to `/opt/radd-stream/Fast_Fetch/`.
     - Unit tests executed natively on Oracle VM: 5/5 passed (100% OK).
     - Full WP REST API catalog indexed: **23,446 titles** populated into `sitemap_cache` in `/home/ubuntu/radd-stream-data/7starhd.db`.
     - Verified live end-to-end scrape of 3 titles: 19 releases, 278 sources extracted with 0 failures, unlocking 10Gbps Cloudflare R2 direct stream endpoints.
     - Launched multi-threaded background crawler: **PID 119530** (`--workers 5 --delay 0.3`) actively crawling in `/home/ubuntu/radd-stream-data/7starhd.db`.
  5. **System Resource & Performance Verification**:
     - Oracle VM running both crawlers concurrently with load average ~0.08-0.15, 10GB free RAM, and 165GB free disk.
  6. **Staging Database Isolation**:
     - Zero merges performed. All databases (`multimovies.db`, `hdtvb.db`, `rogmovies.db`, `ssrmovies.db`, `vegamovies.db`, `7starhd.db`) remain strictly isolated.
- **Next action:** Monitor dual live crawler execution (Vegamovies + 7StarHD).

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
