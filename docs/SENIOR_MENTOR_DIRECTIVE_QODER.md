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

### Priority 1: Fleet Merge & Catalog Promotion (`merge_fleet.py`)
1. **Fleet Merge in Progress**:
   - Continue running `Fast_Fetch/merge_fleet.py` until all 18 sites are merged into `/home/ubuntu/radd-stream-data/merged_catalog_20261024.db`.
   - Ensure the JSON report is updated at `/home/ubuntu/radd-stream-data/merged_catalog_20261024.db.report.json`.
2. **Quality & Safety Gate Before Promotion**:
   - Run verification query: Assert `SELECT count(*) FROM posts WHERE is_18_plus = 1` are properly flagged.
   - Run `python3 -S Fast_Fetch/sweep_public_edge.py` against the merged DB to ensure zero provenance leaks.
   - When owner gives the final confirmation, point `/etc/nginx` or `fast_fetch.py serve` to the newly merged database so the app is filled with 100k+ real titles.

### Priority 2: Mobile UI & Compose Feature Integration
All core logic engines and 245 unit tests are passing (100% green). Now, wire and polish the visual presentation surfaces in `App/app/src/main/kotlin/com/raddstream/app/`:

1. **Player Gestures HUD Overlay (`PlayerScreen.kt` + `PlayerGestures.kt`)**:
   - **Left Swipe**: Vertical brightness pill with sun icon and animated fill percentage (0–100%).
   - **Right Swipe**: Vertical volume pill with speaker icon and fill percentage (0–100%), transitioning to an orange **"BOOST 200%"** indicator when audio boost is active (`AudioBoost.kt`).
   - **Horizontal Scrub**: Floating time badge displaying `[ -00:45 | 14:20 ]` with scrubbing thumbnail/timestamp.
   - **Double-Tap**: 10-second seek ripple circle animation on left/right screen zones.
   - **Long-Press**: Top-center HUD pill displaying `"2.0x >>"`.
2. **Quality Ladder Bottom Sheet (`QualityRungCard.kt` + `QualityLadder.kt`)**:
   - When user taps the Quality gear/badge in playback controls, display a Compose Bottom Sheet:
     - `Auto (1080p)` (Default, dynamically switches with `AdaptiveQuality.kt`)
     - `4K UHD` (with file size, e.g. `3.2 GB`)
     - `1080p FHD` (with file size, e.g. `1.4 GB`)
     - `720p HD` (with file size, e.g. `650 MB`)
     - `480p SD` (with file size, e.g. `250 MB`)
   - Tapping a rung triggers rendition switch while preserving playback position.
3. **Downloads Screen & Cache Promotion (`DownloadsScreen.kt`)**:
   - Visual download cards with title, poster, quality tier, live speed (MB/s), ETA, and pause/resume buttons.
   - Support zero-waste cache promotion: if user watched 60% of a title and taps "Download", the card starts at 60% and downloads only the remaining 40%.
4. **Local P2P WiFi Sharing Screen (`LanShareServer.kt`)**:
   - In `DownloadsScreen.kt` or `SettingsScreen.kt`, add a "Share via Local WiFi" button.
   - Starts `LanShareServer` on port `8990` and shows a clean dialog with the local IP so other family devices can stream or download without using any mobile data.

### Priority 3: Automatic APK Packaging on Every Milestone
- On every completed UI milestone:
  ```bash
  cd /opt/radd-stream/App && ./gradlew --offline assembleDebug
  sudo cp app/build/outputs/apk/debug/app-debug.apk /var/www/download/radd-stream.apk
  ```
- This ensures the owner always has an up-to-date APK to test on their phone.

---

## 3. Inviolable Constraints Reminder
1. **Python Stdlib Only**: Zero pip or npm packages on the backend.
2. **Staging Isolation**: Merges must only write to specified snapshot target files (e.g. `merged_catalog_20261024.db`). Never overwrite live `fast_fetch.db` without confirmation.
3. **18+ Content Suppression**: Adult content must remain strictly filtered out at query level across all public endpoints and UI views.
4. **Zero Video Bandwidth Proxying**: All streaming remains HTTP 302 redirects to high-speed CDNs.

Qoder, you have full authorization and clear priority. Proceed with merging, Compose UI wiring, and APK packaging.
