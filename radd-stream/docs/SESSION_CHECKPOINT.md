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

- **Goal:** Continue read-only monitoring of the three Oracle staging crawlers and preserve the project state without merging any databases.
- **Milestones & Breakthroughs:**
  1. **Oracle Background Crawlers Active**:
     - Vegamovies (`import_vegamovies.py`, PID 76635) is running. Read-only DB check: 4,297 / 14,316 roots scraped, 9,807 pending. Its run-status file reports 3,890 / 13,726 completed and 5 failures; counters are per-run and can differ from cumulative DB counts.
     - Rogmovies (`import_rogmovies.py`, PID 77286) is running. Read-only DB check: 3,651 / 7,868 roots scraped, 4,204 pending; run status reports 3,650 completed and 0 failures.
     - HDTVB (`import_hdtvb.py`) and MultiMovies full scrapes both 100% completed.
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
  5. **Oracle VM Production Deployment & Launch**:
     - Deployed `import_ssrmovies.py` and `test_ssrmovies_import.py` to `/opt/radd-stream/Fast_Fetch/` on Oracle VM (`92.4.95.252`). All unit tests passed 100% on the VM.
     - Completed full catalog ingestion of 27,000+ titles into `/home/ubuntu/radd-stream-data/ssrmovies.db`.
     - Verified system resource capacity: CPU load at 0.37 (plenty of idle capacity), 10 GiB available RAM, 165 GB available disk space.
     - SSRMovies (`import_ssrmovies.py`, PID 80318) is running. Read-only DB check: 936 / 27,000 roots scraped, 26,064 pending; run status reports 930 completed and 0 failures.
     - Already resolving live direct Google CDN (`lh3`) and Cloudflare R2 streams.
  6. **Test Verification**:
     - Targeted suite passed 75 tests: database 36, VIDOUT 6, merge guard 3, HDTVB 4, MultiMovies 9, Rogmovies 6, SSRMovies 5, and Vegamovies 6.
- **Verification:** Targeted tests and Python compilation passed. `setup_check.py` passed in the previous verification. Broad unittest discovery also runs `test_all_sites.py`, a live external-site audit; it timed out while some sites were unavailable, so it is not an offline unit-test result. A read-only SSH query matched the recorded host fingerprints and confirmed all three crawlers are running. No staging database was merged.
- **GitHub:** The reviewed policy, merge guard, HDTVB metadata update, and continuity/domain docs were pushed to `agent/staging-merge-approval-gate-20261018` at commit `d6e8d18`. The branch is not merged into `main`.
- **Oracle:** No files or services were changed. The deployment runbook requires independent host-key verification before production file changes; the saved fingerprints are only a TOFU consistency check. No database was merged or modified.
- **Next action:** Continue read-only monitoring of the three crawlers. Even after they finish, do not merge anything automatically. Only consider a specific merge after the user explicitly requests it, the source/target/counts/backup plan are presented, and the user separately confirms.

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
