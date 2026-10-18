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

- **Goal:** Safely improve crawler throughput and make every pending or parser-empty URL visible and retryable; preserve the no-merge rule.
- **Milestones & Breakthroughs:**
  1. **Latest read-only Oracle crawler check**:
     - Vegamovies (PID 76635; `--workers 5 --delay 0.3`) was the only crawler still running. Its log showed about 0.15 titles/sec. DB counts: 11,471 scraped, 2,615 pending, 230 marked `scraped=-1` for review. Run-status counters differ from cumulative DB counts; trust the DB for current queue state.
     - Rogmovies was no longer running: 7,840 scraped, 0 pending, 28 `scraped=-1` review rows. Its status file incorrectly reports 0 failures.
     - SSRMovies was no longer running: 26,993 scraped, 7 pending, 0 review rows. Those 7 remain resumable (`scraped=0`).
     - Do not stop or restart the active Vegamovies process. No staging DB was changed or merged.
  2. **SSRMovies Live Domain & WP REST API Discovery**:
     - Identified active 2026 production domain **`https://ssrmovies.surf`** (HTTP 301 from `ssrmovies.gripe`).
     - Verified open WordPress REST API at `https://ssrmovies.surf/wp-json/wp/v2/posts?per_page=100` indexing **27,362 total posts** across 274 pages (`X-WP-Total: 27362`).
  3. **Dedicated Staging Importer `Fast_Fetch/import_ssrmovies.py`**:
     - Isolated staging database `Fast_Fetch/ssrmovies.db`.
     - Multi-page WP REST API ingestion into `sitemap_cache` table (`--sync-api`).
     - Enhanced metadata extraction: clean title, year, audio/language, CDN/TMDB poster, synopsis.
     - Per-release button parser extracting exact resolution (`1080p`, `720p`, `480p`, `2160p 4K`), exact file size (`2.8GB`, `434MB`), and codec.
     - LinksZilla mirror unwrapper resolving into Google CDN (`lh3.googleusercontent.com`), 10Gbps Cloudflare R2 (`r2.cloudflarestorage.com`), PixelDrain, and web stream (`watch-online.mom`).
  4. **Live Terminal Monitor `check_ssrmovies.py`**:
     - Remote SSH live monitor querying process metrics, SQLite counts, and log tail.
  2. **Safe crawler changes prepared locally**:
     - All three importers now default to 6 workers, cap concurrency at 6, and keep the 0.3s minimum request delay.
     - Added explicit `--retry-failed` for `scraped=-1` review rows; SSR empty parses now stay reviewable instead of being marked successful.
     - Progress/status output distinguishes pending work from review rows. HTTP failures remain pending for a later resume.
     - These changes are not deployed to Oracle; the active Vegamovies process still runs its existing 5-worker command.
  3. **Verification:** Python compilation passed and the three targeted importer suites passed 20 tests. The suite emitted two SQLite `ResourceWarning`s during the SSR review test, but all assertions passed.
- **GitHub:** Policy and crawler changes are pushed to review branch `agent/staging-merge-approval-gate-20261018` at `d109c37`. The branch is not merged into `main`.
- **Oracle:** No files/services changed; no database was merged or modified. Independent Oracle host-key verification is still required before production writes.
- **Next action:** Continue read-only monitoring; do not stop the active crawler, deploy to Oracle, or merge a staging database without the required verification and separate user approval.

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
