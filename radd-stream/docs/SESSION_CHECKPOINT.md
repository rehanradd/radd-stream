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

- **Goal:** Deploy and launch dedicated RareAnimes scraper on Oracle VM, maintain Vegamovies, 7StarHD, and HDHub4u execution, and uphold strict staging DB isolation.
- **Milestones & Breakthroughs:**
  1. **RareAnimes API Discovery & Catalog Indexing**:
     - Discovered open WordPress REST API (`https://www.rareanimes.mov/wp-json/wp/v2/posts?_embed=1`).
     - Ingested entire catalog of **1,926 titles** across 20 pages with rich embedded metadata (featured high-res posters, anime categories, and episode descriptions).
     - Augmented with master movies index (`/all-anime-cartoon-movies-list/`), bringing total catalog to **2,624 anime titles**.
     - Identified direct underlying download links in the REST API payload bypassing web redirect shorteners (`codedew.com/zipper`).
  2. **Dedicated Importer & Test Suite**:
     - Built `Fast_Fetch/import_rareanimes.py` and `Fast_Fetch/test_rareanimes_import.py`.
     - 14/14 unit tests passed natively on Oracle VM in 0.08s.
     - Live stream unwrapping verified: PixelDrain CDN direct video streams (`https://pixeldrain.com/api/file/<ID>`) and HubCloud 10Gbps Cloudflare R2 direct streams (`r2.cloudflarestorage.com`).
  3. **Launched 4th Background Crawler on Oracle VM**:
     - Background crawler **PID 123020** (`--workers 5 --delay 0.3`) actively crawling in `/home/ubuntu/radd-stream-data/rareanimes.db`.
     - Created local monitor utility `check_rareanimes.py`.
  4. **Active Concurrent Crawler Status**:
     - Vegamovies: PID 76635 (~88% scraped, 106,991+ releases, 332,762+ direct sources).
     - 7StarHD: PID 120570 (~20% scraped, 10,395+ releases, 39,791+ direct sources).
     - HDHub4u: PID 121847 (14,504 titles indexed, actively crawling).
     - RareAnimes: PID 123020 (2,624 titles indexed, actively crawling PixelDrain and HubCloud R2 streams).
  5. **Staging Database Isolation**:
     - Zero merges performed. All staging databases remain strictly isolated.
- **Next action:** Monitor all four live crawlers (Vegamovies + 7StarHD + HDHub4u + RareAnimes).

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
