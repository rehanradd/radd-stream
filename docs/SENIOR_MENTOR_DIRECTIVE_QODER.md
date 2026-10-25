# 🏛️ Senior Architect & Project Admin Directive to Qoder Agent
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
2. **Catalog v2 Edge Mounted**:
   - Mounted `/api/v2` read edge in `Fast_Fetch/viewer.py` and `Fast_Fetch/catalog_v2.py`.

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

---

## 3. Inviolable Constraints Reminder
1. **Python Stdlib Only**: Zero pip or npm packages on the backend.
2. **Staging Isolation**: Merges must only write to specified snapshot target files (e.g. `merged_catalog_20261024.db`). Never overwrite live `fast_fetch.db` without confirmation.
3. **18+ Content Suppression**: Adult content must remain strictly filtered out at query level across all public endpoints and UI views.
4. **Zero Video Bandwidth Proxying**: All streaming remains HTTP 302 redirects to high-speed CDNs.

Qoder, you have full authorization and clear priority. Proceed with merging, Compose UI wiring, and APK packaging.
