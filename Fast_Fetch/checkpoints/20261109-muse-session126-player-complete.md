# Session 126 — video player complete (2026-11-09, base main ce4fdd1)

Branch `session126-player-complete`. Base main @ ce4fdd1. NOT pushed — parent
reviews and pushes. Five commits, author rehanradd:

- `0030dbd` backend: P-8 probe measures the file + VIP pass via header
  (tests: test_link_state 33 OK re-run at the tip, test_redact 82 OK at commit).
- `d67f787` pure policy: start-low ABR, thermal cap, resume re-seed
  (`ResumeSeed.newerSeed`), brightness base, `keepingProgress`, `ShareMoment`,
  `PlayerGlass`.
- `7bfda85` VM/state: PlayerUiState fields, PL-2 ad removal (VM side),
  start-low service, EXPIRED_LINK handoff.
- `ea24092` screen: D-35 backdrop, PL-2 screen removal, offline/locked/up-next/
  cast strip, PL-6/8/9/10/11/12/13/14, D-37/D-40/D-43, data saver, honest
  boost, SC.7 ring, ShareMoment.
- `7e3e818` embed/nav/downloads/settings: VIP header send, deep-link routing
  + dead link, saved-on-device pills, auto-PiP setting.

## What was built (open list from player-plan-consolidated-20261109.md)

- D-35 poster/backdrop behind loading: staged `TitleMeta` (poster/year/cast)
  flows store → VM → state; the start state shows the blurred (24 dp) dimmed
  poster + real progress ring, never a black void. Deep links stage nothing,
  so they honestly show none.
- PL-2 sponsor placeholder ad removed entirely: `SponsorBreakDialog` + call
  gone, `requestAdBreak`/`requestBetweenEpisodesBreak`/`pendingCrossEpisode`/
  `adBreak`/`dismissAdBreak` gone from VM + state; the countdown advances
  directly via `advanceCrossEpisode(held)`. `AdSlotPolicy`/`AdSlot` +
  pure tests stay as the seam for a real ad one day. `AdCadenceGuardTest`
  pins the removal.
- PL-3 offline card: `state.isOffline` shows an offline card with Retry
  immediately, not the 30 s deadline card.
- PL-4 locked time chip: position/duration in frosted glass (solid on
  low-RAM) while locked.
- PL-5 keep chip for local files: already VM-side — `refreshKeepState` sets
  `Unavailable` for local bundles, `keepCurrent` early-outs; the screen
  already hides the chip then. No screen change needed.
- PL-6 print sheet: user-facing rows only (quality, HLS, Playing). Ranks,
  failover log and policy sit behind a long-press on the "Prints" title.
- PL-8 scrubber semantics: `progressBarRangeInfo` + `setProgress` +
  contentDescription naming position and current chapter.
- PL-9 brightness: drag base is the real window brightness, then the system
  brightness (`initialBrightnessBase`), never an assumed 0.5f.
- PL-10 PiP: aspect ratio from `videoAspectRatio` + source rect from the
  surface bounds; opt-in auto-enter on leaving while playing (Settings
  switch `player_auto_pip`, default off; `saveAutoPip` + `autoPip` flow
  already in the settings repository).
- PL-11 More rows "Next episode"/"Calibrate" gated on `state.isSeriesScope`.
- PL-12 end card "Up next" preview (title/number/still via the VM-published
  `nextEpisode*` fields) + countdown card names the episode + Play now.
- PL-13 give-up card: outside-tap = keep-waiting (dismisses, playback
  continues); Back still exits via the screen-level BackHandler
  (`DialogProperties(dismissOnBackPress = false, dismissOnClickOutside = true)`).
- PL-14 connection-error + give-up cards mutually exclusive.
- D-37 TopBar subtitle = year · quality · source-kind (HLS/expiring/Auto),
  never the title. "Source" is the playback kind, never a host name.
- D-40 notice-card Retry/Try-another are real OutlinedButtons.
- D-43 filled selected states (jade disc behind the icon; filled sheet rows
  and quality rungs) + visible 10 sp labels under the six primaries.
- 25a dialogBlocking gains `moreSheetVisible` (audit bug: chrome auto-hid
  while the More sheet was open). 25b `selectQualityBand` emits
  `PlayerEvent.Message` on a missing band. 25c Quality primary stays visible
  on single-rung titles, dimmed, tapping it explains why. 25d resume
  re-seed via `ResumeSeed.newerSeed`.
- Start-low ABR (3-part chain: cold `pickBand` → lowest; director
  `configure` auto → lowest rung; service `startLowBundle` rewrites the
  initial rendition) + 3-step progress story (Finding the best print →
  Warming the link → Buffering) in the notice card.
- Data saver row in the Quality sheet next to Auto (`state.dataSaver` +
  `vm.toggleDataSaver()`).
- Volume boost, honest UI only: slider requests up to 200%, the setter
  clamps at the 100% player ceiling, `AudioBoostUi.honestSummary` states
  requested vs applied. True gain stays parked (needs DynamicsProcessing).
- Low-end verified as prescribed: PlayerView default SurfaceView (no
  PlayerSurfaceView in Media3 1.3.1), DefaultRenderersFactory untouched
  except the subtitle-offset TextRenderer (HW decode + platform SW fallback
  are Media3 defaults), LoadControl from PlayerBuffering values (15 s min /
  50 s max / 500 ms for playback / 1 s after rebuffer, time over size).
  Only gap added was the thermal cap (`ThermalCap.maxBandFor`, applied to
  climbs only, never forcing a step down; service thermal listener API 29+).
- Embed VIP header: `X-Radd-Vip-Pass` (`redact.VIP_PASS_HEADER` server-side,
  `ApiProvider.VIP_PASS_HEADER` app-side) sent on the initial redirector
  request only via `WebView.loadUrl(url, headers)` — never in the URL,
  never in history. Backend acceptance landed in 0030dbd
  (`request_is_vip` / `_request_is_vip`).
- NAV-4 expired handle: `HandoffWhy.EXPIRED_LINK` (service stale bundle +
  expired rendition) → the give-up card says the link expired and offers
  Home. NAV-5: `MainActivity` parses incoming `radd://` VIEW intents with
  `DeepLinks.parse()` (first caller ever) and the graph routes Detail /
  Stream / Browse, or the new `DeadLink` destination with a Home button
  when nothing parses. `DeepLinksTest` gains the two shapes the dead-link
  route depends on.
- SC.7 living keep ring: `CacheAffordance.keepingProgress` (null when the
  total is unknown — no 0% ring, no "Keeping 0 B of 3.05 GB") drawn on the
  Keep chip while Keeping.
- SC.8 "Saved on device" badge on READY pills (both device downloads and
  kept items). Storage meter + auto-delete toggle already existed.
- SC.24 share a moment: `ShareMoment.shareText` (title — time + deep link),
  VM emits `PlayerEvent.ShareMoment`, screen opens the system chooser;
  More-sheet row; hidden for local bundles (no handle to link to).
- SC §3 pause = discovery: cast strip on pause (chips from staged
  `castNames`); tapping an actor searches them (NavGraph → Search route).
- BM rule 9 frosted glass via `PlayerGlass.spec` (tint + border; solid on
  low-RAM devices via `ActivityManager.isLowRamDevice`).
- P-8 server probe fix (0030dbd): text/* or HLS → no size; 206 without a
  Content-Range total → no size; Content-Range total wins; 200
  video/audio/octet-stream with Content-Length still records.

## Deliberately parked (do not build without the named decision)

- Skip Intro — no server intro-timing data.
- Audio delay — needs a custom AudioRenderer.
- SW decoder toggle — needs FFmpeg extension + owner decision.
- True audio gain — needs DynamicsProcessing.
- Chromecast — needs sender infra.
- Watch party, AI features.
- Scrub thumbnails (E9) — Media3 is 1.3.1 (`gradle/libs.versions.toml:7`),
  minSdk 21. Thumbnails need Media3 ≥ 1.5; the bump to 1.11.x needs
  minSdk 21 → 23 (Media3 1.9.0 raised it; drops Android 5.0/5.1).
  Owner decision, not taken here.
- Device verification (N1–N3) — owner-only.
- P-1 server truth — out of scope for this session.

## Checks

- Backend: `test_link_state.py` 33 OK (re-run at the tip, P-8 module);
  `test_redact` 82 OK at 0030dbd.
- Pre-push Kotlin checks per commit, all clean: full import diff base→HEAD
  (every new import used; one real catch fixed — an edit had dropped the
  `AndroidView` import; one KDoc link de-bracketed after the `AdSlot`
  import was removed), @Composable counts (PlayerScreen 47 → 48 = +2 new
  cards −1 removed dialog; all other files unchanged), `/*` vs `*/`
  unchanged vs base (PlayerScreen's naive 23/22 is the pre-existing
  `"video/*"` / `"*/*"` string artifact; the diff adds zero `/*`),
  strings.xml parses, no new drawables, no new network data classes.
- Two real slips caught in review and fixed before commit: `state.isLoaded`
  and `vm.onRetryTapped()` do not exist — replaced with `durationMs > 0`
  and `retryCurrentCandidates()`; a disabled Quality button whose onClick
  would have been dead code — it stays tappable, dimmed, and explains on tap.

## Not done

- Push (parent's step, then Android CI judges — no local Gradle by owner
  order). Device verification of all of the above on the next emulator /
  device session (owner-only). The scrub-thumbnails version-bump decision
  (owner). Gate-deploy after CI green (parent).

## Parent fixup 1 — Android CI red on first push (compile, bf49a36 + this commit)

Branch CI on bf49a36: Backend SUCCESS (42632823555), Android FAILURE
(42632823748, job 129213194491, `:app:compileDebugKotlin`). All 16
errors in PlayerScreen.kt, all builder slips — the parent's pre-push
checks (duplicate types, unused imports) do not catch missing imports
or wrong member names, and there is no local Gradle to catch them
either; CI is the judge. Root causes, each fixed in PlayerScreen.kt:

- `LocalLifecycleOwner` (lines 148, 335): `androidx.lifecycle.compose`
  is not a dependency — the version catalog carries only
  `lifecycle-viewmodel-compose`, no `lifecycle-runtime-compose`. The
  screen is always hosted by the Activity, so the owner is the context:
  `val lifecycleOwner = context as LifecycleOwner` (import swapped to
  `androidx.lifecycle.LifecycleOwner`, same artifact as the already
  imported `LifecycleEventObserver`, so it resolves).
- `formatTime(positionMs)` bare (1904, 1905, 2240 ×2): the only
  `formatTime` is the `Long` extension in the viewmodel, already
  imported, always called receiver-style elsewhere in the file —
  changed to `positionMs.formatTime()` / `durationMs.formatTime()`.
- `WifiOff` (2206): `Icons.Default.WifiOff` used with no import — added
  `androidx.compose.material.icons.filled.WifiOff`.
- `spec.tint` / `spec.shape` / `spec.borderWidth` / `spec.border`
  (2235, 2236): GlassSpec has no such members — its fields are
  `useGlass`, `tintAlpha`, `borderAlpha`. LockedTimeChip rebuilt from
  the real fields: dark chip at `tintAlpha` (opaque when solid), 1dp
  white edge at `borderAlpha` (invisible when solid), `RoundedCornerShape(8.dp)`
  (import added). Same frosted/solid split the builder intended.
- `combinedClickable` (3381): `PrintLogSheet` had only the Material3
  opt-in; added `ExperimentalFoundationApi` to its `@OptIn`.

## Parent fixup 2 (19:4x PKT, CI run 42634752406 on d03fba6 — compile fixed, 7 tests failed)

All 7 were builder slips the pre-push checks cannot catch (the checks verify
imports and duplicate types, not test-guard contracts). Each was root-caused
from the failing test's own assertion before editing; the guard replicas were
re-run against the edited tree and all read clean.

- `BrandDriftTest.deepLinkSchemeIsNeverHardcoded`: the only offender was
  `ShareMoment.kt`'s KDoc example — a double-quoted `"Title — 12:34\nradd://…"`
  that the test's naive literal regex catches even inside a comment. Reworded
  to backticked fragments; the link itself is unchanged (`DeepLinks.streamUri`).
- `DeadCodeGuardTest` + `PlayerChromeCopyTest` (vocabulary): the PL-2 ad removal
  deleted the ad code but left 6 strings in `strings.xml` (`player_slot_pre_roll`,
  `player_slot_between`, `player_ad_title`, `player_ad_body`, `player_continue`,
  `player_rune_rank`) — all unreferenced. Deleted. `player_saved_on_device`
  (SC.8) was also unpainted by the player because its pills live on the
  downloads screen, not the player — renamed to `downloads_saved_on_device`
  (2 refs in `DownloadsScreen.kt`), same text.
- `PlayerChromeCopyTest` (prose): three hardcoded literals with letters+spaces
  in `PlayerScreen.kt` — the chapter suffix `", $it"`, the Up-next join
  `"${…player_up_next}: $nextEpisodeTitle"`, the position/duration join
  `"${…} / ${…}"`. Each moved into `strings.xml` as a format resource
  (`player_seek_chapter`, `player_up_next_title`, `player_position_duration`)
  with matching placeholder counts (verified: 0 arg mismatches).
- `PlayerBackExitTest` x2: the builder's PL-13 broke the Session 114 pinned
  rule — `onDismissRequest` pointed at the keep-waiting lambda and a comment
  mentioned `BackHandler` a third time (count must be exactly 2: import + call).
  Restored `onDismissRequest = onBackToDetails`, `dismissOnClickOutside = false`
  (outside tap does nothing; Close keeps waiting; Back exits via the screen
  handler), comment reworded without the word. The PL-13 "outside tap dismisses"
  design is superseded by the pinned rule.
- `PlayerControlSemanticsTest` (More sheet): fixup 1's own doing — extending
  `PrintLogSheet`'s `@OptIn` to `(…, ExperimentalFoundationApi::class)` broke
  the test's end marker, the literal `"\n@OptIn(ExperimentalMaterial3Api::class)"`.
  Split into two separate `@OptIn` lines; same opt-ins, marker restored.

## Parent fixup 3 (19:5x PKT, CI run 42637503486 on 8f6e0c5 — Backend green, Android compile red)

One error, mine, not the builder's: `PlayerScreen.kt:3377 "This annotation is
not repeatable"` — `@OptIn` cannot be stacked, so fixup 2's two-line split of
`PrintLogSheet`'s opt-in was illegal Kotlin. Reverted to the single combined
`@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)`.
The test that needed the split (`PlayerControlSemanticsTest.moreSheetBody`)
uses the next sheet's annotation as its end marker; the marker now tracks the
real combined annotation (same intent — the body still ends at PrintLogSheet),
with a comment saying why. Precedent: Session 122 fixup 3 updated a guard
string after proving the guarded invariant intact; the More-sheet control
assertions themselves are untouched.
