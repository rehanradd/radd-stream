# 🎬 Single Universal Player & Zero-Latency Cache Directive (qoder1)

> **Owner Priority Directive (2026-10-29)**:
> Build the most responsive, zero-latency streaming and offline download experience on mobile:
> 1. ONE main native player for ALL video types (no webviews or third-party players).
> 2. Zero-latency instant playback start (0.5s buffer) & fast keyframe seeking.
> 3. Offline Keep & Save Internet wiring in Player UI.
> 4. 100% permanent removal of link shorteners.

---

## 🛠️ Implementation Checklist

### 1. Zero-Latency Instant Playback & Fast Seek
In `app/src/main/kotlin/com/raddstream/app/player/PlaybackService.kt`:
- **Fast-Sync Seeking**: Set `player.setSeekParameters(SeekParameters.CLOSEST_SYNC)` so dragging the seekbar snaps immediately to the nearest I-frame without decoding lag.
- **Fast Buffer Start**: Customize `DefaultLoadControl`:
  - `bufferForPlaybackMs = 500` (drop from default 2,500ms down to 500ms).
  - `bufferForPlaybackAfterRebufferMs = 1000`.
- **Cross-Protocol Redirects**: Keep `httpFactory.setAllowCrossProtocolRedirects(true)` so HLS/MP4 streams from all 35+ backend vaults play directly in ExoPlayer.

### 2. Wire "Save Internet / Keep Offline" in Player Screen
In `app/src/main/kotlin/com/raddstream/app/ui/screens/PlayerScreen.kt`:
- Wire the "Keep This" / "Download" icon button to call:
  ```kotlin
  cacheCoordinator.keepNow(sourceKey)
  ```
- Uses the existing `app/src/main/kotlin/com/raddstream/app/data/cache/` engine:
  - Adopts already streamed bytes without re-downloading.
  - Saves remaining segments in background.
  - Allows 100% offline playback via `LocalMediaProxy`.

### 3. Clean Out Link Shorteners 100%
- Remove `wrapWithShortener` in `DetailViewModel.kt`.
- Clean any shortener models in `VipRemoteConfig.kt`.
- All download buttons must invoke direct download intents (`ACTION_VIEW` or background byte-pipe) with zero third-party shortener redirects.

### 4. Media3 Pre-Roll Ad Delegate & 7-Day Streak
- Add pre-roll ad listener callback before playback start, capped to max 1 ad per 25 minutes for non-VIP users (VIP users bypass).
- Add the 7-day login streak reward UI in Settings / Profile.
