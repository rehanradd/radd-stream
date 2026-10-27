# 🚀 QODER MASTER SPRINT DIRECTIVE: FULL A-TO-Z IMPLEMENTATION
**Model Selected**: `DeepSeek-Flash`  
**Execution Host**: Oracle ARM VM (`/opt/radd-stream`)  
**Project Owner Location**: Lahore, Punjab, Pakistan  
**Status**: APPROVED & BINDING MASTER ROADMAP

---

## 🎯 Task 1: Auto-Landscape Video Player (`PlayerScreen.kt`)
1. In `PlayerScreen.kt`:
   - When entering playback, lock orientation to sensor landscape:
     `(context as? Activity)?.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE`
   - In `DisposableEffect`, when exiting the player, restore orientation to unspecified:
     `(context as? Activity)?.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED`
   - Add a 1-tap Rotate button in the player control bar to toggle between Landscape and Portrait manually.

---

## 🎯 Task 2: Video Playback & Stream Resolution Fix
1. In `Fast_Fetch/viewer.py` and `Fast_Fetch/catalog_v2.py`:
   - On `GET /api/v1/stream?id=...`, ensure the redirect target is a direct playable media stream (Google CDN, PixelDrain direct API `https://pixeldrain.com/api/file/{id}`, Cloudflare R2, MoviezGuru direct `.mkv`/`.mp4` stream).
   - In `_build_option_groups` / release links: prioritize active direct CDN streams so ExoPlayer receives playable media URLs rather than HTML bridge landing pages.
2. In Android `PlayerViewModel.kt` & `ExoPlayer`:
   - Configure `DefaultHttpDataSource.Factory` with browser User-Agent (`Brand.userAgent`), `allowCrossProtocolRedirects(true)`, and follow up to 10 redirects.
   - If ExoPlayer encounters an error or non-video stream, automatically trigger `RenditionFailover` to failover to backup handles in under 500ms.

---

## 🎯 Task 3: Working In-App Video Downloads (`DownloadsScreen.kt`)
1. In `DownloadsViewModel.kt`:
   - Pass verified direct stream/download URLs to Android's `DownloadManager` or background download worker.
   - Set destination to public `Movies/RaddStream/` directory with proper MIME types (`video/mp4` or `video/x-matroska`).
   - Add persistent notification with real download progress, pause/resume, and completed item playback.

---

## 🎯 Task 4: Distinct Season & Episode Posters
1. In `DetailScreen.kt` and `ReleaseLayoutBuilder.kt`:
   - For web series and TV dramas, fetch and display individual season posters (Season 1, Season 2, etc.) and episode preview stills from TMDB rather than repeating the same root series poster.
2. In `CatalogImage.kt` and `PosterCard.kt`:
   - Ensure the branded dark gradient fallback card renders cleanly if an image fails to load.

---

## 🎯 Task 5: Monetization & Pakistani Payment Rails (Our Earning)
1. In `Fast_Fetch/admin_panel.py`:
   - Add `screen_monetization(conn)` to render the Monetization & Operator Settings card:
     - JazzCash Till ID, JazzCash Mobile, EasyPaisa, Raast ID inputs.
     - VIP pricing: PKR 200/month, PKR 1500/year.
     - Monetag Rewarded Video zone ID & Adsterra Native banner ID.
     - Link shortener tokens (ShrinkMe / Droplink).
   - Handle `POST /admin/action/save-monetization` to persist atomically.
   - Mount `GET /api/v1/app/remote-config` in `Fast_Fetch/viewer.py`.
2. In Android App:
   - Create `VipUpgradeScreen.kt` with JazzCash Merchant Till QR/ID, EasyPaisa, Raast ID, 1-tap Copy buttons, PKR pricing, and Transaction ID (TID) verification submission.
   - Add clean native sponsor card in `DetailScreen.kt`.

---

## 🎯 Task 6: User Accounts & 1-Tap Login
1. Support zero-friction Guest mode.
2. Allow account sync via Pakistani mobile number (`03XXXXXXXXX`) or a 16-character Sync Key.
3. Automatically sync Watch History, Resume progress (timestamp), and "My List" bookmarks across devices.

---

## 🎯 Task 7: Subtitle Delay Offset Slider
1. In `PlayerScreen.kt`, add a Subtitle Offset bottom sheet with quick buttons `[-0.5s] [-0.1s] [RESET] [+0.1s] [+0.5s]` and a real-time slider adjusting `player.setSubtitleOffsetUs(offsetUs)`.

---

## 🎯 Task 8: Test Gate & Fresh APK Compilation
1. Run `./gradlew --offline testDebugUnitTest assembleDebug` (all tests must pass green).
2. Copy compiled APK to `/var/www/download/radd-stream.apk`.
