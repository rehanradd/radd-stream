# 🎬 PLAYER_SPEC.md — MX Player parity map & Media3 capability analysis

> Owner: app-player agent. Research done 2026-10-22.
> Every claim below was cross-checked against the **Media3 1.3.1 source tree**
> (`raw.githubusercontent.com/androidx/media/1.3.1/libraries/...`, files downloaded and grepped:
> `SubtitleView.java`, `PlayerView.java`, `AspectRatioFrameLayout.java`, `TrackSelectionParameters.java`,
> `Tracks.java`, `MediaItem.java`, `MediaMetadata.java`, `Player.java`, `C.java`, `Format.java`,
> `MediaController.java`, `DefaultRenderersFactory.java`, `DefaultSubtitleParserFactory.java`,
> `MimeTypes.java`) and against the **backend contract** (`Fast_Fetch/catalog_v2.py`,
> `Fast_Fetch/API_V2.md`). Anything not verifiable is marked as such.

---

## 1. Sources used for the MX Player side

Web sources consulted (they corroborate the well-known MX gesture surface; the closed-source
app has no public spec, so where the web was thin, product-knowledge of MX's shipped UI was used
and marked ⚠️):

- [MX Player Pro gesture guide (mxplayerpro.org)](https://mxplayerpro.org/guide/mx-player-pro-gestures.html) — double-tap sides skip, vertical swipe volume/brightness, horizontal swipe seek, pinch zoom/fill, tap toggles controls, lock blocks touch.
- [MX official changelog (sites.google.com/site/mxvpen)](https://sites.google.com/site/mxvpen/features/changelog) — sleep timer lives at *Playback screen → menu → Tools → Sleep timer*.
- [MX features page (mx.j2inter.com)](https://mx.j2inter.com/features) — “change playback speed on the fly by swiping up/down with two fingers”; speed range 0.25×–4×.
- [Android Police — Files by Google adopts MX-style gestures](https://www.androidpolice.com/2020-12-14/files-by-google-gets-mx-player-like-gestures-for-volume-and-brightness-control/) — the canonical description of vertical-left=brightness / vertical-right=volume / double-tap-to-seek (±10 s default, with ripple + time toast).
- [Greasyfork “MX Player style” gesture script](https://greasyfork.org/en/scripts/570331-html5%E8%A7%86%E9%A2%91%E6%89%8B%E5%8A%BF) — long-press speed boost that *releases back to normal speed*, double-tap left −10 s / right +10 s.
- [Scribd — MX-style gesture storyboard](https://www.scribd.com/document/871106648/Storyboard-Video-Player-Gesture-Controls) — double-tap center play/pause, zone table.
- [MX Player (Instagram feature reel)](https://www.instagram.com/reel/DNxOLqhWACq/) — speed 0.25×–4×, A-B repeat, equalizer/volume boost.

---

## 2. Feature → implementation matrix

Legend: **Native** = Media3 1.3.1 API does it · **Custom** = implemented by us in this package ·
**Dep** = needs a dependency/module we must request in `HANDOFF_appplayer.md` ·
**No** = not possible on Android/Media3 1.3.1, with the reason.

### 2.1 Gesture surface (`player/PlayerGestures.kt` + the pointer lane in `ui/screens/PlayerScreen.kt`)

> Path corrected 2026-10-29: this heading used to cite `player/ui/GestureLayer.kt`, and §2.2 below
> used to say the overlay was "decomposed in `player/ui/`". **There is no `player/ui/` package in
> this app** — `ls app/src/main/kotlin/com/raddstream/app/player/` has no `ui` directory, and there
> is no `GestureLayer.kt` anywhere in `app/src`. The gesture arithmetic (each detector, the
> arbitration, the clamps, cinema mode, two-finger rewind) is `player/PlayerGestures.kt`, and the
> composable that installs it plus every HUD element it draws is `ui/screens/PlayerScreen.kt`.
> The tests follow the code: `player/PlayerGesturesTest.kt`, not a `GestureLayerTest`.

| MX behavior | Verified MX detail | Our implementation | Status |
|---|---|---|---|
| Double-tap left half = rewind 10 s, with ripple + “−10s” toast | ✔ (AndroidPolice, greasyfork) | `detectTapGestures(onDoubleTap)`; x<⅓w → `seekBy(-skipMs)`; animated circular ripple + label via `SeekRipple` composable | Custom |
| Double-tap right half = forward 10 s | ✔ | x>⅔w → `seekBy(+skipMs)` | Custom |
| Double-tap center = play/pause | ✔ (scribd storyboard; “some skins”) | middle third → toggle; behavior switch `GestureSettings.doubleTapCenterPlays` (MX ships it as an option) | Custom |
| Single tap = toggle controls (and, in some skins, play/pause) | ✔ | when controls hidden → show; when visible → hide | Custom |
| Vertical swipe **left** half = brightness | ✔ | `activity.window.attributes.screenBrightness` (window-local, **no WRITE_SETTINGS permission needed**); HUD bar shown; ±1 clamp; “auto” returns to −1f | Custom |
| Vertical swipe **right** half = volume | ✔ | `AudioManager.STREAM_MUSIC` (with deprecated legacy path below API 26 via `setStreamVolume` percent steps) | Custom |
| Horizontal swipe = scrub with preview | ✔ (no thumbnails in MX on these sources either) | press-and-drag accumulates dx → target position, live “mm:ss → mm:ss” HUD + chapter ticks; release = `seekTo`. **No frame-accurate thumbnails**: `MediaItem` thumbnails API does not exist in 1.3.1 (added upstream ~1.5). Time-preview only | Custom (preview degraded) |
| Long press = speed boost; release returns to normal | ✔ | `detectTapGestures(onLongPress)` → `setPlaybackParameters(boostSpeed=2.0×, default)`; `onRelease` restores. MX’s own default boost is user-configurable; ours: `GestureSettings.boostSpeed` | Custom |
| Two-finger vertical swipe = playback speed | ✔ (MX features page) | secondary-pointer drag nudges speed 0.25× steps | Custom |
| Pinch / expand aspect (“zoom to fill”) | ✔ | pinch-out → `PlayerView.setResizeMode(RESIZE_MODE_ZOOM)`, pinch-in → `RESIZE_MODE_FIT`; also full cycle FIT→ZOOM→FILL→FIXED_WIDTH in the Resize menu. **Why not a transform**: `PlayerSurfaceView` doesn’t exist in 1.3.1 (verified absent from the 1.3.1 ui sources) and view-transform scaling of the internal `SurfaceView` is unreliable below API 30 | Custom (mode-based) |
| Double-tap-to-play on black screen (some skins) | ⚠️ | covered by `doubleTapCenterPlays` toggle | Custom |
| Lock = disable **all** gestures + all controls except the lock button | ✔ | `UiState.locked` short-circuits the gesture layer and hides bars; MX-style corner lock icon | Custom |
| Gesture/sensor auto-rotation + back = rotate | ✔ | cycle `activity.requestedOrientation`: SENSOR ↔ SENSOR_LANDSCAPE ↔ SENSOR_PORTRAIT ↔ LOCKED; landscape flip button included | Custom (plain Activity API) |
| Screen-off keeps playing (wake lock) | ✔ | `player.setWakeMode(C.WAKE_MODE_LOCAL)` (constant verified in `C.java`) + service FGS `mediaPlayback` | Native |

### 2.2 Controls overlay (layout faithful to MX, composed in `ui/screens/PlayerScreen.kt`)

> Corrected 2026-10-29: this heading said "decomposed in `player/ui/`", a package that does not
> exist. The overlay is 41 `@Composable`s living in one file, `ui/screens/PlayerScreen.kt`.
> **And the component names in the table below are the spec's own vocabulary, not the shipped
> identifiers** — checked against `grep -n '^@Composable' -A 1` on that file:
> `PlayerTopBar` → **`TopBar`**, `BottomBar` → **`BottomControls`**, `SeekRipple` →
> **`DoubleTapRipple`**, plus the names that are real: `CenterControls`, `EdgeHud`,
> `GestureOverlay`, `PlayerSurface`, `Scrubber`, `HudToast`, `ScrubToast`, `BoostBadge`,
> `SubtitleOverlay`, `KeepChip`, `QualitySheet`, `TracksSheet`, `SpeedSheet`, `SleepSheet`,
> `SubtitleSettingsSheet`. A reader looking for a `player/ui/` package or a `PlayerTopBar` symbol
> would find neither, so treat §2.2 as "what the overlay does", and the file above as where.

| MX element | Implementation | Status |
|---|---|---|
| Top bar: back · title · print/quality chip · lock · PiP · overflow(⋮) | `PlayerTopBar` — the print chip shows the **settled** rendition label (see §3.3 failover) | Custom |
| Center: play/pause big button fading after 3.5 s of no touch; double-arrow prev/next-episode + ±10s | `CenterControls`; fade via `AnimatedVisibility` | Custom (auto-fade logic) |
| Bottom: time bar with **position + buffered** + elapsed/total | `PlayerTimeBar` — Compose Canvas: buffered band (white 35%), position accent, scrub head, optional chapter ticks | Custom |
| Bottom button row: Subtitles · Audio · Speed · Sleep timer · Resize · Next episode · Playlist · **Keep(cached)** | `PlayerQuickRow` (exact set matches the task’s MX description) | Custom |
| Triple-dot menu sections Playback / Tools / Subtitle / Audio / Video / Lock | `PlayerMoreSheet` — MX structures its overflow exactly this way (changelog proves Tools holds sleep timer) | Custom |
| “Play again from …” dialog & resume prompt | `PlayFromDialog` (mm:ss entry) + resume-confirm when start>10 s | Custom |
| Notification + media-session controls, headphones | service-owned `ExoPlayer` + `MediaSession` (`PlaybackService`), UI drives it through `MediaController` (`buildAsync` — 1.3.1 has **no synchronous build**, verified) | Native |

### 2.3 Playback features

| MX feature | Media3 1.3.1 reality | Our implementation | Status |
|---|---|---|---|
| Speed 0.25–4× **with pitch preservation** | `player.setPlaybackParameters(PlaybackParameters(speed))` — Media3 time-stretches, pitch preserved by default | `setSpeed()` in VM + menu + slider | Native |
| Frame-step | No frame-accurate stepping API exists in 1.3.1 (verified: nothing resembling `seekToFrame` in `Player.java`). MX does it with its SW decoder. | step = `seekTo(pos ± 1000/frameRate)` using `Format.frameRate` (public field, verified) of the selected video track; fallback 24 fps | Custom approximation |
| Background play (video→audio keeps running) | `MediaSessionService` + FGS type `mediaPlayback` (manifest already declares it) | controller keeps service alive; screen-off/back → audio continues | Native |
| Audio-only mode | `TrackSelectionParameters.setTrackTypeDisabled(C.TRACK_TYPE_VIDEO, true)` (method verified @1.3.1) | toggles video off, artwork panel shown; re-enable restores | Native |
| Stereo/downmix control | **No public downmix API**. `setMaxAudioChannelCount(2)` verified — it *restricts selection* to stereo tracks (right answer for dual-audio prints) but cannot downmix a lone 5.1 track (needs custom `AudioSink`). | “Stereo only” toggle = channel-count cap; true 5.1→stereo documented as **No (needs custom renderer)** | Native-partial |
| Hardware vs software decoder switch | `DefaultRenderersFactory.setExtensionRendererMode(OFF/ON/PREFER)` verified; SW decoders *only* exist as source-built extension modules (**not on Google Maven** — FFmpeg README: “not provided via Google's Maven repository”) | H/W-first default; app-level “software decoder” switch only takes effect if `media3 FFmpeg extension` CI build is added → **Dep**, gradle lines requested in handoff | Dep |
| Sleep timer **with fade-out** | `player.setVolume(0..1)` verified | `SleepTimer` pure logic: countdown, pause at 0 or *end of video* mode, volume ramps 1→0 across last 30 s | Native+Custom |
| Subtitles: embedded tracks | `player.currentTracks` (TEXT groups) + `TrackSelectionOverride(TrackGroup, idx)` + `setOverrideForType` — all verified | Subtitle sheet lists embedded tracks, “Off”, external add | Native |
| Subtitles: external files (.srt/.vtt/.ass/.ssa/.ttml) | `DefaultSubtitleParserFactory` in 1.3.1 parses SSA/ASS, WebVTT, SubRip, TX3G, PGS, DVB, TTML (verified). Loaded through `MediaItem.SubtitleConfiguration` (`setSubtitleConfigurations` verified) | “Add external subtitle” = bundle-provided `tracks.subtitles[].url` or user-picked file (SAF) → SubtitleConfiguration append via `controller.replaceMediaItem` | Native |
| Subtitle size / position | `SubtitleView.setFixedTextSize` / `setFractionalTextSize` / `setBottomPaddingFraction` / `setStyle(CaptionStyleCompat)` — all public, verified (note: `SubtitleView` is **`final`** in 1.3.1 and `PlayerView` has **no** subtitle-provider hook — both verified) | applied via `playerView.subtitleView` after attach | Native |
| Subtitle delay for **native (embedded)** cues | ❌ not possible in 1.3.1: cue shifting needs subclassing/factory hooks absent in this version. Upstream added `SubtitleViewProvider` later → **Dep (media3 ≥ 1.4 bump)**. | UI hides native-delay when the selected track is embedded, with an honest note | No (in 1.3.1) |
| Subtitle delay / full styling for **external** subs | ✅ because we render them ourselves: `player/ExternalSubtitleRenderer` parses SRT+WebVTT in pure Kotlin (`subtitle/SubtitleParsers.kt`, JVM-tested) and draws a Compose overlay with ±10 s delay, size, bottom offset, color. The native TEXT renderer is disabled for these files so nothing double-renders. | Custom |
| Audio delay | ❌ **No API and no trick that is honest**: Media3 exposes no audio-render offset; MX does it inside its own decoders. Needs a custom `AudioRenderer` wrapper (extension) — declared in handoff as future work; UI does not offer it. | No |
| Chapters | Chapter ticks accepted in the contract when `coverage.episodes[]` supplies per-episode offsets in-file; no container-chapter parsing in 1.3.1 (`getChapters` absent) | Custom from catalog data | Custom |
| PiP / float-on-desktop | Activity-level PiP: manifest already sets `supportsPictureInPicture` ✔; `PictureInPictureParams.Builder().setAspectRatio(Rational(w,h))` (API 26), `setAutoEnterEnabled` guarded API 31 | `enterPip()` from overflow/back policy while playing | Native |
| “Play again from” on resume | `MediaItem.ClippingConfiguration.Builder().setStartPositionMs` (verified) — but failover must *preserve* position, so we use `controller.seekTo` after `onRenderedFirstFrame`/state change instead of clipping | Resume + startFrom in VM | Custom |
| A-B repeat | MX has it (feature reel). Not in the required feature list → out of scope for this milestone, marked **future** | — | ⏳ Future |

### 2.4 Codecs — honest breadth (verified against Media3 README + extension docs)

**Native on the Android platform (MediaCodec), i.e. works with what we ship today:**
- Video: H.264/AVC, H.265/HEVC (API 21+ device-dependent, near-universal by 2026), VP8/VP9, AV1 (API 29+ SW / newer devices HW), MPEG-2/4.
- Audio: AAC(-LC/HE v1/v2), MP3, PCM/WAV, Vorbis, FLAC (API 29+ full), **Opus (API 21+)**, AMR-NB/WB, ALAC; AAC-ELD (API 29+).
- **AC-3 / E-AC-3 (Dolby Digital/Plus)** and **DTS**: *device-dependent vendor additions* — AOSP does not guarantee them (Android 12+ added EAC3/AC4 & TrueHD on many but not all devices). A CAM print from a phone mic has AAC audio → fine; a BluRay rip with TrueHD/DTS-X → silent audio on stock devices.

**Requires the Media3 decoder extensions (NOT publishable via Maven — must be built from repo sources with the NDK, verified from `libraries/decoder_ffmpeg/README.md`):** FFmpeg (DTS, DTS-HD, TrueHD, WavPack, APE, MDPEG… + every exotic video codec), libdav1d (AV1 on old devices), standalone FLAC/Opus/MPEG-H/IAMF. → The handoff requests the exact CI job + module wiring if the owner accepts the APK-size and build complexity. Until then the player **detects a silent/unrenderable audio track** (`Tracks.Group.isTrackSupported == false` / `C.FORMAT_EXCEEDS_CAPABILITIES`) and offers: switch rendition / stereo-2ch track / external player (Intent exists today).

---

## 3. Backend contract mapping (from `catalog_v2.py` + `API_V2.md` §5)

### 3.1 Link kinds the player must respect
`classify_link()` kinds → client behavior (ported 1:1 as `LinkKindClassifier.kt`, JVM-tested):
`cdn_direct/hls_manifest` (stream) · `embed` (WebView — **never** fed to ExoPlayer; UI says so, WebView screen owned by others → handoff) · `bridge`/`cloud_page(resolve_required)` (needs the `/api/v2/play` round-trip → client-side hook `ResolveRequester`, wired in handoff) · `download_only` (offered to the cache engine, not to the player) · `torrent/dead_end` (never offered).

### 3.2 PlayBundle failover (`RenditionFailover.kt`)
API_V2 §5 mandates: try rank 1 → retry same once → next rank → never beyond `max_ranks`, reporting each failure. Our pure policy does exactly that, keeps a `FailoverLog` (label + human reason of every dead candidate) which the UI surfaces as (a) a top-bar chip “Playing: 1080p WEB-DL · H.265” and (b) a transient strip “#1 4K BluRay died: HTTP 404”. The bundle is held in an in-process store (`PlayerSessionStore`) so the service and the screen share it without serialization.

### 3.3 Coverage / pack offsets (`EpisodeOffsets.kt`, `EpisodeProgression.kt`)
- `season_pack` / `episode_range` prints start an episode at `offset_seconds` from `cat_release_episodes` (via the API `coverage` block). Semantics of `cat_offsets`: keyed by `(work_key, season, episode, release_label)`, latest wins, `confirmed_by` accumulates.
- Resolution order: **locally-learned offset > server offset > unknown ⇒ `needs_offset_calibration`** UI (MX-style “This file contains Season 7” warning + calibration affordance).
- After the user manually finds the right spot: “Mark position as Episode N start” records it locally and emits an `OffsetReport` for `POST /api/v2/episodes/{id}/offset` (API_V2 §8) — the HTTP call is owned by the network agent (handoff), the client contract + buffering live in our files.
- Auto-advance: next episode **inside the same file** when offsets are known (pack/range), else a `NextEpisodeRequest` event so navigation can fetch the next bundle (route wiring → handoff).

### 3.4 Transport realities
- `requires_https`/cleartext: our host and many CDNs are plain HTTP today. Debug build already sets `usesCleartextTraffic=true`; **release** deliberately keeps platform policy → release must wait for TLS or a scoped `network_security_config` decision (handoff, root AGENTS.md rule).
- `expires_at` in the past ⇒ never reuse the URL: `PlayBundle.isExpired` + re-request path (VM blocks stale loads with a visible “Link expired — fetch a fresh one” action).
- `accepts_ranges=false` ⇒ scrubber disabled per §5 contract (`PlayerUiState.seekEnabled`).

## 4. Signature feature — watch → keep (contract in `player/CacheContract.kt`)
The engine (sibling-owned `data/cache/**`) never restarts fetching from zero: the player hands it
`AdoptRequest(url, byteCursor, positionMs, bufferedMs, durationMs, expectedTotalBytes, resumable, ttl)`.
`byteCursor` semantics: authoritative bytes when the engine observes the shared `CacheDataSource`;
otherwise our conservative estimate `floor(bufferedFraction × expectedTotalBytes)` marked `isEstimate=true`.
Hostile cases modeled: `STORAGE_FULL` (engine must free-then-retry, UI offers cleanup hint),
`INTERRUPTED` (auto-retry w/ resume), `APP_PRIVATE_FILE` (UI states “playable in Radd only” + TTL chip),
preview TTL 3–6 h expiry (`PreviewExpiringSoon` chip + “keep permanently” upgrade path). See PLAYER↔ENGINE table in `HANDOFF_appplayer.md`.

## 5. What we could not verify (there IS an Android SDK here — what is missing is a device)

Corrected 2026-10-29. The heading used to read "**no Android SDK in this workspace** … nothing was
compiled or run", and that is false on both halves: `local.properties` sets
`sdk.dir=/home/ubuntu/android-sdk`, and `app/build/outputs/apk/debug/app-debug.apk` (22,738,552
bytes, dated 2026-10-27) was built on this Oracle VM — the ARM64/AAPT2 incompatibility was cleared
with `qemu-user-static` (App Session 5). Builds are now gated locally through the one-at-a-time
queue (`/tmp/qbuild.sh`), most recently **627 JVM unit tests / 0 failures** (build28).

What the sentence was reaching for is still the honest limit, and it is a **device** limit, not an
SDK limit:
- Nothing in this player has run on Android. Compose recomposition edge cases, the PiP window,
  real HLS behaviour, gesture *feel*, the notification/lock-screen appearance and MediaCodec
  coverage on target devices are all unverified, and no JVM test can verify them.
- Two Robolectric suites — `PosterCardProvenanceTest` and `ScreenSnapshotTest`, 9 tests between
  them — are excluded on `aarch64`/`arm64` at `app/build.gradle.kts:220-233` because Robolectric
  ships no native runtime for ARM, and GitHub Actions is disabled at the account level, so the
  x86_64 runner that would execute them is not running either. **Those 9 tests currently execute
  nowhere.** Recorded as a known limitation, not fixed here.
- The Media3 1.3.1 API claims in §2/§3 were checked against the dependency's sources; they are
  compile-verified by the build, not behaviour-verified by a player.
