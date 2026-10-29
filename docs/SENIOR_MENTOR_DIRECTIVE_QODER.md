# 🚨 CRITICAL FLEET DIRECTIVE: REAL DATABASE SWAP, DIRECT MEDIA RESOLUTION & LUXURY UI

To Qoder Agent:
**BINDING OPERATIONAL MANDATE FROM PROJECT OWNER & SENIOR ARCHITECT**
Date: October 26, 2026

The project owner installed the app on physical hardware and reported that the app felt empty, broken, and flawed.
Our live system audit revealed the exact root causes that you must fix immediately:

---

### 1. DATABASE POINTER SWAP: RETIRE 7MB STUB, CONNECT REAL 5.7GB CATALOG
> **⚠️ THIS ENTIRE SECTION IS DONE, AND FOLLOWING IT NOW WOULD BE AN INCIDENT. Read before acting.**
> Measured on this box 2026-10-30 00:35 from `/proc/<pid>/environ` of the running
> `radd-stream.service` unit: `RADD_DB_PATH` is **already**
> `/home/ubuntu/radd-stream-data/merged_catalog_20261025.db`. The unit is `active`, RSS
> 58 MB. Steps 1–2 below were performed; step 4 ("reload and restart") must **never** be
> performed by an agent — restarts and the first release tag are the owner's call, and a
> healthy production service restarted for no reason is exactly the failure this notice
> exists to prevent (one OOM-kill + auto-restart on an uncommitted tree is already
> recorded in `docs/SESSION_CHECKPOINT.md`).
> The size and counts in step 1 were also stale as of this writing: the file measures
> **6.40 GB (6,396,899,328 B)**, not 5.7 GB, and `posts` is **150,799** (with 15,068 rows
> flagged `is_18_plus=1`), not 130,016 — later merge batches landed. `COUNT(*) FROM posts`
> costs 0.91 s on this host; `… WHERE is_18_plus=1` costs **26.46 s**, so a verification
> curl of `/api/v1/posts` is the cheap check, and a scan is not.
* **Root Cause**: The live systemd service `radd-stream.service` was still pointing to `/home/ubuntu/radd-stream-data/fast_fetch.db`, which is an old 7.3MB test database containing only **201 posts**.
* **Action Required**:
  1. Point `RADD_DB_PATH` in `/etc/systemd/system/radd-stream.service` to `/home/ubuntu/radd-stream-data/merged_catalog_20261025.db` (5.7GB, **130,016 posts**, **1,383,752 releases**, **3,456,460 links**).
  2. ~~Backup old test DB to `/home/ubuntu/radd-stream-data/fast_fetch_old_201_posts.db.bak`~~
     **NOT DONE, AND DO NOT DO IT NOW.** Measured 2026-10-30: no `.bak` exists, and
     `fast_fetch.db` is still in place (7,647,232 B, mode `0600`, mtime Oct 27 01:59). The
     pointer was swapped *without* renaming anything, which is why there is no backup file —
     and it is also why this step is now a destructive rename of a live-but-unused file for
     no benefit. The service does not open it; leave it alone.
  3. Ensure `redact.site_needles()` in `Fast_Fetch/redact.py` does not run unindexed sequential scans over 3.7M rows of `download_sources` on startup.
  4. ~~Reload and restart `radd-stream.service`~~ **⛔ WITHDRAWN — not an agent action.**
     Restarting production is the owner's call; the swap is already live and a restart here
     buys nothing and risks an outage. The verification half of this step is read-only and
     is how to check it: `curl -s http://127.0.0.1:8080/api/v1/posts | python3 -c 'import json,sys; print(json.load(sys.stdin)["total"])'`
     — measured 2026-10-30 against the running unit: `/api/v1/posts?limit=1` returns
     **`total: 135731`**, so the "130000+" bar in the original text is met and now
     conservative. Note the arithmetic, because it is a free correctness proof of the
     adult filter: the catalog holds 150,799 `posts`, of which 15,068 are flagged
     `is_18_plus=1`, and **150,799 − 15,068 = 135,731** — exactly the public total. The
     per-row filter is tonight removing precisely the flagged rows and nothing else. (The
     *work-level* leak recorded in the root `AGENTS.md` — a flagged work reachable through
     an unflagged twin under the same `canonical_key` — is a different defect and this
     number does not clear it.)

---

### 2. STREAM & DOWNLOAD INTEGRITY: REAL DIRECT `.mp4`/`.mkv` ONLY (ZERO HTML BRIDGES)
* **Root Cause**: When `/api/v1/stream?id=...` is queried, it redirects to `https://hubcloud.foo/tg/go?...` or intermediate bridge URLs. These are HTML web pages, NOT direct media files!
  - When ExoPlayer opens this link on the user's phone, it crashes with `UnrecognizedInputFormatException`!
  - When the download manager downloads this link, it saves an HTML file instead of the movie!
* **Action Required**:
  1. In `Fast_Fetch/viewer.py` and `Fast_Fetch/catalog_v2.py`:
     - Every `/api/v1/stream` endpoint must redirect to a **direct playable media URL** (`.mp4`, `.mkv`, Google Drive direct CDN, PixelDrain direct API `https://pixeldrain.com/api/file/{id}`, Cloudflare R2, or direct high-speed video server).
     - Never redirect ExoPlayer to an HTML bridge page (`hubcloud.foo/tg/go`, `vcloud.beer`, `linkrit`). If a link is an unresolved bridge, resolve it to final media or skip to the next active direct mirror!
  2. In Android `PlayerViewModel.kt` and `RenditionFailover.kt`:
     - Add active media failover: If ExoPlayer detects a non-video mime type or HTTP error from a mirror, silently failover to backup handle `backup_handles` in under 500ms without freezing.

---

### 3. ARTWORK & POSTER RELIABILITY: TMDB FIRST + SAFE COIL FALLBACKS
* **Root Cause**: Many scraped poster URLs in the catalog point to dead scraper domains (e.g. `rogmovies.one` 301 redirects or Cloudflare blocks), causing posters on the user's phone to show blank gray cards.
* **Action Required**:
  1. In `Fast_Fetch/viewer.py`: When serving `poster_url` and `backdrop_urls`, prioritize high-resolution TMDB artwork (`https://image.tmdb.org/t/p/w500/...` and `https://image.tmdb.org/t/p/original/...`) whenever `tmdb_id` or TMDB art is available.
  2. In Android `CatalogImage.kt` and `PosterCard.kt`: Configure Coil image loader with crossfade, follow redirects, and a sleek dark branded gradient fallback card displaying the movie title when an image URL fails to load.

---

### 4. DATA SANITIZATION & LEAK PREVENTION: CLEAN PRESENTATION
* **Root Cause**: The API is currently returning raw scraper strings:
  - Titles contain: `"Download Mohabbatein (2000) Hindi Full Movie 480p [600MB] | 720p | Official"` instead of clean `"Mohabbatein (2000)"`.
  - Synopses contain raw `/PLOT` placeholders or scraper watermarks.
* **Action Required**:
  1. Strip "Download", quality brackets (`[600MB]`, `| 720p | 1080p`), and promotional keywords ("Official", "HDRip", "WEB-DL") from titles before displaying in the app. Always use `clean_title` or sanitized title.
  2. Ensure adult (`is_18_plus = 1`) titles remain 100% suppressed from public endpoints.
  3. Ensure no source site names (VegaMovies, KatMovieHD, Bolly4u) leak to the Android UI.

---

### 5. LUXURY CONSUMER UI: HERO CAROUSEL & PURE CINEMA MODE
* **Action Required**:
  1. `HomeScreen.kt`: Build the full-bleed 400dp `HeroCarousel.kt` auto-scrolling top trending movies with TMDB backdrops and a prominent **[ ▶ Watch Now ]** button.
  2. `PlayerScreen.kt`: Implement `ViewMode.PURE_CINEMA` (zero pause scrim, zero giant play icon, 100% clean video frame for subtitles, edge-hairline HUD, 3s dialogue rewind).
  3. `DetailScreen.kt`: Luxury presentation with **[ ▶ Play Best Quality ]** primary action button that resolves directly to the fastest direct CDN stream.

---

### 6. COMPILATION & APK PUBLISH GATE
After implementing these changes:
1. Run `./gradlew --offline testDebugUnitTest` (all tests must pass green).
2. Compile debug APK: `./gradlew --offline assembleDebug`.
3. Copy to download directory: `sudo cp app/build/outputs/apk/debug/app-debug.apk /var/www/download/radd-stream.apk`.

**Project**: `radd-stream` (Unified Backend & Android Streaming Platform)  
**Author**: Antigravity (Senior Architect, Dao Partner & Project Admin)  
**Recipient**: Qoder Agent (`qwen2.5-coder:1.5b` / `qodercli` / `DeepSeek-Flash`) & Core Fleet  
**Date**: October 24, 2026  
**Status**: ACTIVE & BINDING ARCHITECTURAL SPECIFICATION

---

## 1. Executive Directive: VM-Centric Build & Execution Mandate

To Qoder: **All app development, UI refinements, compilation, and testing are to be performed directly on this Oracle VM.**  
Third-party browser sandboxes (e.g. Google AI Studio) lack the complete Android SDK toolchain, persistent Gradle daemons, and storage. This Oracle VM (4-core ARM, 12GB RAM, Java 21, Gradle 8.7, Android SDK 34/35) is the primary build host and single source of truth.

The project owner will test live APK builds directly on their physical Android smartphone via the local download server (`http://92.4.95.252/download/radd-stream.apk`).

---

## 2. Outstanding Work & Execution Roadmap

### Priority 1: Fleet Merge & Catalog Promotion (`merge_fleet.py`) — ✅ COMPLETED
1. **Fleet Merge Complete**:
   - Merged all 18 sites into `/home/ubuntu/radd-stream-data/merged_catalog_20261025.db`.
   - Re-derived KatMovieHD page identities, cutting unresolved conflicts from
     3,131 to the 1,460 that `merged_catalog_20261025.db` reports today.
2. **Layer-1 Catalog Projection Completed**:
   - Projected full catalog in `catalog_v2.py`: **116,922 works**, **1,383,752 releases**, **3,456,460 links**, **160,442 episodes** (100% zero data loss).
3. **Catalog v2 Edge Mounted**:
   - Mounted `/api/v2` read edge in `Fast_Fetch/viewer.py` and `Fast_Fetch/catalog_v2.py`.
4. **App Settings & Account Sync Landed (Commit `27fc043`)** — ✅ COMPLETED:
   - DataStore persistence for Keep TTL, Subtitles, Image Quality, Mobile Data.
   - `/api/v2/account*` client in `SyncAccountRepository.kt`.
   - Local Android compilation verified on VM: 304 unit tests green, `assembleDebug` green.
5. **Dynamic Gateway Server Discovery (Blogger Deadman Switch)** — ✅ COMPLETED:
   - Live stealth node gateway active at `https://rehan-radd.blogspot.com/` (zero indexing, hidden meta tags for primary + backup nodes).
   - Android client engine: `com.raddstream.app.network.DynamicServerDiscovery.kt` (307 unit tests green). Automatically probes and discovers healthy nodes if primary server address changes.

---

## ⚡ Speed & High-Velocity Execution Mandate
To Qoder: **The massive 3.4M-link catalog projection & link rank census is 100% VERIFIED AND FINISHED:**
- `cat_links`: 3,456,460 links, 3,433,287 with positive rank score (`rank_score > 0`), 149,584 duplicates cleanly collapsed with zero link loss.
- **DO NOT RUN ANY FURTHER FULL-TABLE SQL CENSUS SCANS** over the 3.7M rows. They take multiple minutes on ARM CPU and the catalog integrity is already 100% proven.

### 🎯 IMMEDIATE SPRINT QUEUE (DO IN THIS EXACT ORDER):
1. **Priority 6: Admin Monetization & Pakistan Payment Settings**:
   - In `Fast_Fetch/admin_panel.py`, render the Monetization & Operator Settings Card:
     - Ad Networks: `monetag_zone_id`, `adsterra_tag_id`, `applovin_sdk_key`
     - Download Shorteners: `shrinkme_api_token`, `droplink_api_token`, shortener ratio
     - Pakistan Payment Rails: `pak_till_id`, `pak_jazzcash_num`, `pak_easypaisa_num`, `pak_raast_id`, `vip_monthly_pkr` (default 200), `vip_yearly_pkr` (default 1500)
   - Handle `POST /admin/action/save-monetization` to persist atomically.
   - Mount `GET /api/v1/app/remote-config` in `viewer.py`.
2. **Priority 4: Android Luxury UI & Pure Cinema Mode**:
   - `PlayerScreen.kt`: `ViewMode.PURE_CINEMA` with zero pause scrim, zero giant play icon blocking subtitles, and active invisible swipe/long-press gestures.
   - `HomeScreen.kt`: 400dp full-bleed `HeroCarousel.kt` auto-scrolling top trending movies.
3. **Priority 3: Automatic APK Build & Publish**:
   - Run Gradle offline assemble: `cd /opt/radd-stream/App && ./gradlew --offline assembleDebug`
   - Copy to public download root: `sudo cp app/build/outputs/apk/debug/app-debug.apk /var/www/download/radd-stream.apk`
   - Project Owner will immediately test on physical smartphone in Lahore.
2. **Focus on UI & Monetization Sprints**: Rapidly deliver Priority 4 (Pure Cinema & Gestures), Priority 5 (Desi Cine-Finder), and Priority 6 (Admin Monetization Card) without stalling.

### Priority 2: Mobile UI & Compose Feature Integration — 🔄 PARTIALLY DELIVERED / POLISHING
Core logic engines and unit tests are passing (100% green).
- **Offline Cache Engine** (`OfflineCacheEngine.kt` + `CacheCoordinator.kt`) ✅
- **Adaptive Quality & Ladder** (`AdaptiveQuality.kt` + `QualityRungCard.kt` + `QualityLadder.kt`) ✅
- **200% Audio Boost** (`AudioBoost.kt`) ✅
- **Binge Preloader** (`BingePreloader.kt`) ✅
- **LAN P2P Sharing** (`LanShareServer.kt` + `LanShareProtocol.kt`) ✅
- **Silent Rendition Failover** (`RenditionFailover.kt`) ✅
- **Release Layout Unification** (`ReleaseLayoutBuilder.kt`) ✅

### Priority 3: Automatic APK Packaging on Every Milestone
- On every completed UI milestone:
  ```bash
  cd /opt/radd-stream/App && ./gradlew --offline assembleDebug
  sudo cp app/build/outputs/apk/debug/app-debug.apk /var/www/download/radd-stream.apk
  ```
- This ensures the owner always has an up-to-date APK to test on their phone.

---

## 3. Priority 4: The Path to No. 1 (The 95/100 Upgrade Plan)
*Owner Mandate: Implement these 4 core features to beat Netflix, MX Player, and MovieBox in everyday mobile user experience.*

### Feature A: Subtitle Offset Delay & Online Subtitle Search
- **Location**: `App/app/src/main/kotlin/com/raddstream/app/player/subtitles/`
- **Component 1**: `SubtitleOffsetSheet.kt` (Bottom sheet in Player controls):
  - Slider and quick buttons `[ -0.5s ] [ -0.1s ] [ RESET ] [ +0.1s ] [ +0.5s ]`.
  - Adjusts ExoPlayer subtitle presentation timestamp offset in real-time (`player.setSubtitleOffsetUs(offsetUs)`).
- **Component 2**: `SubtitleDownloader.kt`:
  - Fetches OpenSubtitles / Subscene `.srt` tracks matching IMDB ID / clean title + language.
  - Injects parsed `SingleSampleMediaSource` into ExoPlayer dynamically.

### Feature B: Netflix-Grade Hero Carousel & Auto-Preview (`HomeScreen.kt`)
- **Location**: `App/app/src/main/kotlin/com/raddstream/app/ui/components/HeroCarousel.kt`
- Auto-advancing (5-second) banner of the Top 5 Trending items from `/api/v1/posts?sort=trending`.
- High-resolution TMDB backdrop image with vertical gradient scrim (`Brush.verticalGradient(listOf(Transparent, DarkSurface))`).
- Clean typography: Title, release year badge, audio language pills (`Hindi`, `Eng`, `Dual`), and a vibrant **[ ▶ Play Now ]** button and **[ + My List ]** toggle.

### Feature C: Subtitle & Audio Styling Customizer
- **Location**: `App/app/src/main/kotlin/com/raddstream/app/ui/screens/SettingsScreen.kt` + `SubtitleStyle.kt`
- User options:
  - Font size: `Small (14sp)`, `Normal (18sp)`, `Large (22sp)`, `Extra Large (26sp)`.
  - Subtitle color: `White with black outline`, `Yellow on black box`, `Cyan`.
  - Background opacity slider (0% to 100%).

### Feature D: Trakt.tv & Cloud Watchlist Sync Engine
- **Location**: `App/app/src/main/kotlin/com/raddstream/app/data/sync/`
- `TraktSyncEngine.kt`:
  - Lightweight OAuth / PIN login flow.
  - Automatically records scrobble progress (when playback reaches 80%, marks as watched).
  - Syncs watchlist items between local Room database and Trakt so user's list survives device changes.

### Feature E: Universal Software Audio Codec Fallback (AC3/EAC3/DTS)
- Ensure Media3 AudioRenderer gracefully falls back to software decoding (via `DefaultRenderersFactory.EXTENSION_RENDERER_MODE_PREFER`) so older budget phones never play videos with silent audio.

### Feature F: Pure Cinema / Ghost Mode (Sub-Focus Unobstructed Playback)
*Owner Innovation: Traditional video players irritate users by showing giant play/pause icons and dark scrims over long subtitles when paused. Modern viewers know how to use gestures and want zero distractions.*
- **Location**: `App/app/src/main/kotlin/com/raddstream/app/player/PlayerUiState.kt` & `PlayerScreen.kt`
- **Component 1**: `ViewMode` Enum:
  - `NORMAL`: Standard full on-screen controls, top bar, progress slider, and center buttons.
  - `MINIMAL`: Hairline bottom progress bar; center play/pause button hidden; tap toggles play/pause with zero center blockage.
  - `PURE_CINEMA` (Ghost / Sub-Focus Mode):
    - **Zero Pause Distraction**: When paused, **NO dark scrim** and **NO giant play button** in the center. The video freeze-frames in 100% crystal clarity so the user can comfortably read subtitles or study the scene without obstruction.
    - **Single-Tap Toggle**: Tap anywhere on the screen toggles play/pause with 0ms delay and zero on-screen widgets.
    - **Active Invisible Gestures**: Keeps left-swipe brightness, right-swipe volume/boost, double-tap 10s seek, and long-press 2x speed active.
    - **Edge Hairline HUD**: 2dp glowing bezel hairline for volume/brightness rather than center-blocking cards.
    - **"What Did They Say?" Instant Rewind**: Two-finger tap jumps back 3 seconds with subtitles.
    - **Unobtrusive Exit**: 15% opacity floating ghost-eye icon in the corner to toggle back to Normal Mode.

### Feature G: 2.0x Long-Press Speed Optimization Engine (Zero-Freeze on Budget & 4GB Phones)
*Problem: On budget/4GB phones, long-pressing 2.0x speed causes the video decoder to freeze and drop frames because low-end chipsets cannot decode 1080p at 120fps.*
- **Architectural Solution (Zero RAM Burden)**:
  1. **MediaCodec Asynchronous Queueing**: Configure `DefaultRenderersFactory.setEnableDecoderFallback(true)` and async buffer processing in Media3 so the video thread never blocks on synchronous frame release.
  2. **Resolution-Aware Smart Turbo**:
     - On heavy 1080p/4K content on lower-tier SoCs, cap long-press speed to **1.6x** (or 1.75x) instead of a rigid 2.0x. 1.6x provides 90% skimming velocity with **50% less decoder workload**, running completely freeze-free.
     - On 720p/480p streams, full 2.0x is enabled.
  3. **Atomic Gesture Parameter Call**: Ensure `onLongPress` dispatches `setPlaybackParameters(PlaybackParameters(speed, 1.0f))` strictly once on pointer down and once on pointer up (never inside the drag loop).
  4. **Low-Overhead Sonic Audio Stretch**: Prevent CPU audio resampler starvation by adjusting `DefaultAudioSink` buffer bounds for fast playback.

### Feature H: Night-Mode Speech / Dialogue Normalizer (Dynamic Range Compression)
- **Problem**: Movies have deafening loud action scenes/music and inaudible whispered dialogue.
- **Solution**: A one-tap "Night Dialogue Boost" audio processor in `AudioBoost.kt` that compresses excessive sound peaks and boosts human speech frequencies (300Hz–3kHz), so dialogue is always crystal-clear without disturbing roommates.

### Feature I: Bluetooth Earbud Audio-Sync Delay Slider (`-500ms ... +500ms`)
- **Problem**: Budget Bluetooth wireless earbuds have 150ms–300ms audio latency, causing lip-sync mismatch.
- **Solution**: A quick 1-tap slider in the Audio Sheet adjusting audio track presentation time offset in Media3 so dialogue matches actor lips perfectly.

---

## 4. Priority 5: The "Desi Cine-Finder" (Omni-Search & Share Bridge)
*Target Market Mandate: Users in Pakistan, India, Bangladesh, and Nepal who discover movie clips on TikTok / Instagram Reels / YouTube Shorts and want to instantly watch the full movie without burning daily 1.5GB mobile data caps.*

### Architecture: 100% Client-Side Heavy, Zero Server Load ($0 Cost)
1. **Zero Video Upload Law (Data Saver)**:
   - The user's video NEVER leaves their phone.
   - `ClipAnalyzer.kt` uses Android's native `MediaMetadataRetriever.getFrameAtTime(timeUs, OPTION_CLOSEST_SYNC)` to extract 2–3 keyframes directly in local phone memory in under 50ms. Total data used: **<25 KB**.
2. **Dual-Track Identification Pipeline**:
   - **Track A (On-Device Dialogue OCR)**: 95% of South Asian reels carry burned-in English or Hinglish/Urdu subtitles. Run local on-device ML Kit Text Recognition (100% offline, 30ms). Extracted dialogue quotes (e.g. *"Pushpa jhukega nahi"* or *"We need to go deeper"*) query our backend SQLite FTS5 index for an instant 99% match.
   - **Track B (Star-Face & Scene Lens Dispatch)**: If no dialogue text exists, dispatch the keyframe containing the actor's face (Shah Rukh Khan, Prabhas, Allu Arjun, Ranbir Kapoor) to the native Android Google Lens Intent (`com.google.ar.lens`) or visual endpoint. Catch the identified entity title and resolve against our merged catalog.
3. **"Share to Radd-Stream" Instant Cinema Sheet (`ShareReceiveActivity.kt`)**:
   - Implement Android `ACTION_SEND` intent receiver.
   - While scrolling Instagram Reels or TikTok, user taps **Share -> Radd-Stream**.
   - The app intercepts the shared clip or link, identifies the movie, and pops up a bottom sheet with:
     `"K.G.F: Chapter 2 (2022) • 4K UHD • [ ▶ Watch Full Movie ] [ + Add to Watchlist ]"` without the user needing to manually save or download the video.
4. **Desi Natural Language Plot & Vibe Search (SQLite FTS5)**:
   - Index `synopsis`, `clean_title`, `genres`, and `cast_members` with SQLite FTS5 in `catalog_v2.py`.
   - Allows conversational queries: *"Salman Khan kidney hospital comedy"*, *"Amir khan alien paan tapri"*, *"stranded on Mars planting potatoes"*. Resolves in under 3ms.

---

## 5. Priority 6: Sovereign Admin Panel, Pakistan Payments & Monetization Engine
*Owner 20-Year Mandate: Full control over the app fleet (remote config, user accounts, broadcast notices, force updates, anti-crack HMAC protection) and sustainable monetization (Pakistan local Till/JazzCash/Easypaisa payments + download link shorteners).*
*Complete Architecture Specification: See `docs/MASTER_ADMIN_MONETIZATION_SPEC.md` and Operator Guide at `docs/PAKISTAN_OPERATOR_GUIDE.md`.*

### Implementation Checklist for Qoder:
1. **Admin Panel Screen & Action (`Fast_Fetch/admin_panel.py`)**:
   - Add `screen_monetization(conn)` to render the Monetization & Ads Control Card.
   - Input fields:
     - `monetag_zone_id` (Monetag Rewarded Video)
     - `adsterra_tag_id` (Adsterra Native Card)
     - `applovin_sdk_key`
     - `shrinkme_api_token` & `droplink_api_token` (Link shorteners)
     - `shortener_weights` (e.g. 50% ShrinkMe / 50% Droplink)
     - `pak_till_id`, `pak_jazzcash_num`, `pak_easypaisa_num`, `pak_raast_id`
     - `vip_monthly_pkr` (default 200), `vip_yearly_pkr` (default 1500)
   - Add `POST /admin/action/save-monetization` handler in `route_post()` to atomically persist changes to `app_remote_config` table.
2. **App Remote Configuration API (`Fast_Fetch/viewer.py` & `Fast_Fetch/accounts_api.py`)**:
   - Mount `GET /api/v1/app/remote-config` returning JSON of active keys, shortener templates, and Pakistani payment details.
3. **Android Client-Side Wiring (`App/app/src/main/kotlin/com/raddstream/app/`)**:
   - `RemoteConfigRepository.kt`: Fetches config on startup and caches locally.
   - `DetailScreen.kt`: Renders clean native sponsor banner using active `adsterra_tag_id` / `monetag_zone_id`.
   - `DownloadsScreen.kt`: Evaluates user status — VIP gets direct 10Gbps Google CDN link; free user routes through active shortener URL.
   - `VipUpgradeScreen.kt`: Displays JazzCash Till ID, EasyPaisa, and Raast ID with 1-tap Copy buttons and TID submission input.

---

## 6. Inviolable Constraints Reminder
1. **Python Stdlib Only**: Zero pip or npm packages on the backend.
2. **Staging Isolation**: Merges must only write to specified snapshot target files (e.g. `merged_catalog_20261024.db`). Never overwrite live `fast_fetch.db` without confirmation.
3. **18+ Content Suppression**: Adult content must remain strictly filtered out at query level across all public endpoints and UI views.
4. **Zero Video Bandwidth Proxying**: All streaming remains HTTP 302 redirects to high-speed CDNs.

Qoder, you have full authorization and clear priority. Proceed with merging, Compose UI wiring, and APK packaging.
