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

- **Goal:** Concurrently crawl 4 major production scrapers on Oracle VM (10xflix, World4uFree, Bolly4u, KatMovieHD), and maintain strict staging database isolation.
- **Milestones & Breakthroughs:**
  1. **10xflix Oracle Production Crawler Active**:
     - Running in background (PID 146221/146852) with zero failures.
     - 12,170+ catalog posts processed, 43,637+ releases, 151,865+ direct sources extracted (2,414 HubCloud 10G, 6,761 FilePress Google Drive, 14,156 1fichier, 7,156 GoFile).
  2. **World4uFree Oracle Production Crawler Active**:
     - Running in background (PID 152560/153724).
     - 24,240 catalog titles synced into world4ufree.db.
     - Actively unwrapping 5,149+ releases, 49,367+ direct sources, and 1,138 direct 10Gbps Cloudflare Worker streams.
  3. **Bolly4u Deployed Concurrently on Oracle VM**:
     - Running in background (PID 156129/156130).
     - Automated WP REST API bulk synchronization of 36,709 titles into bolly4u.db.
     - Multi-worker crawler with hidden photojin JSON API yielding 10Gbps Google CDN streams.
  4. **KatMovieHD Full Scale Deployed on Oracle VM**:
     - Running in background (PID 156329/156330).
     - Unconstrained full catalog sync traversing 5,000+ pages (~60k titles) via SvelteKit API.
     - Multi-worker crawler extracting DandnDn API mirrors (Cloudflare R2, PixelDrain CDN).
  5. **FilmyZilla Staging Batch Finished**:
     - 4,149 titles scraped, 13,114 releases, 13,516 direct sources, 402 Google CDN 302 streams.
  6. **Master Test Suite & Isolation**:
     - All 145/145 unit tests passing (100% OK) across 14 modules.
     - Strict staging DB isolation maintained across all sites with zero merges into production fast_fetch.db.
- **Next action:** Monitor all 4 live concurrent crawlers (`check_10xflix.py`, `check_world4ufree.py`, `check_bolly4u.py`, `check_katmoviehd.py`) and probe next candidate streaming sites.

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
