package com.raddstream.app.ui.screens

import android.app.Activity
import android.app.ActivityManager
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.content.pm.ActivityInfo
import android.graphics.Typeface
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.view.TextureView
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.AspectRatio
import androidx.compose.material.icons.filled.Bedtime
import androidx.compose.material.icons.filled.BrightnessHigh
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.FastForward
import androidx.compose.material.icons.filled.Forward10
import androidx.compose.material.icons.filled.FullscreenExit
import androidx.compose.material.icons.filled.KeyboardArrowLeft
import androidx.compose.material.icons.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.ListAlt
import androidx.compose.material.icons.filled.LocalMovies
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.LockOpen
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.MusicNote
import androidx.compose.material.icons.filled.PictureInPicture
import androidx.compose.material.icons.filled.Replay10
import androidx.compose.material.icons.filled.RotateRight
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.Speed
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material.icons.filled.VolumeMute
import androidx.compose.material.icons.filled.VolumeUp
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material.icons.filled.WifiOff
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.blur
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.boundsInWindow
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.progressBarRangeInfo
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.setProgress
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.DialogProperties
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.media3.common.util.UnstableApi
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.CaptionStyleCompat
import androidx.media3.ui.PlayerView
import androidx.media3.ui.SubtitleView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.LifecycleOwner
import com.raddstream.app.R
import com.raddstream.app.brand.Brand
import com.raddstream.app.player.AspectMode
import com.raddstream.app.player.AudioBoost
import com.raddstream.app.player.AudioBoostUi
import com.raddstream.app.player.AudioTrackPolicy
import com.raddstream.app.player.CacheAffordance
import com.raddstream.app.player.initialBrightnessBase
import com.raddstream.app.player.EpisodeCoverage
import com.raddstream.app.player.chapterTicks
import com.raddstream.app.player.CalibrationState
import com.raddstream.app.player.DominantAxis
import com.raddstream.app.player.DragCommand
import com.raddstream.app.player.GestureMapper
import com.raddstream.app.player.GestureSettings
import com.raddstream.app.player.HandoffWhy
import com.raddstream.app.player.KeepUiState
import com.raddstream.app.player.PlayerGlass
import com.raddstream.app.player.looksLikeQualityLabel
import com.raddstream.app.player.PinchCommand
import com.raddstream.app.player.PlayerOrientation
import com.raddstream.app.player.PlayerStatusWord
import com.raddstream.app.player.PlayerUiState
import com.raddstream.app.player.bufferingPercent
import com.raddstream.app.player.playerStatusWord
import com.raddstream.app.player.ScreenZone
import com.raddstream.app.player.ScrubPreviewPlayer
import com.raddstream.app.player.ScrubThumbnails
import com.raddstream.app.player.SleepMode
import com.raddstream.app.player.SleepTimerState
import com.raddstream.app.player.StartDeadline
import com.raddstream.app.player.StartDeadlineStage
import com.raddstream.app.player.StartPhase
import com.raddstream.app.player.SubtitleColor
import com.raddstream.app.player.TapCommand
import com.raddstream.app.player.subtitles.SubtitleOffset
import com.raddstream.app.player.subtitles.SubtitleOffsetSheet
import com.raddstream.app.player.dragHalfZone
import com.raddstream.app.player.dominantAxis
import com.raddstream.app.player.qualityCostPerHour
import com.raddstream.app.ui.components.CatalogImage
import com.raddstream.app.ui.components.RaddDialogTitle
import com.raddstream.app.ui.components.raddFilterChipColors
import com.raddstream.app.ui.components.rememberReduceMotion
import com.raddstream.app.ui.theme.RaddCaptionPlate
import com.raddstream.app.ui.theme.RaddCaptionPlateArgb
import com.raddstream.app.ui.theme.RaddCoral400
import com.raddstream.app.ui.theme.RaddCurrent500
import com.raddstream.app.ui.theme.RaddDanger
import com.raddstream.app.ui.theme.PlayerChromeTheme
import com.raddstream.app.ui.theme.RaddHudPillIdle
import com.raddstream.app.ui.theme.RaddHudToast
import com.raddstream.app.ui.theme.RaddMotion
import com.raddstream.app.ui.theme.RaddNarrationCheck
import com.raddstream.app.ui.theme.RaddNarrationPlate
import com.raddstream.app.ui.theme.RaddPlayerDialog
import com.raddstream.app.ui.theme.RaddPlayerSheet
import com.raddstream.app.ui.theme.RaddPlayerSnackbarPlate
import com.raddstream.app.ui.theme.RaddPlayerStage
import com.raddstream.app.ui.theme.RaddSuccess
import com.raddstream.app.ui.theme.RaddTideIndigo
import com.raddstream.app.ui.theme.RaddTokens
import com.raddstream.app.ui.theme.brandSp
import com.raddstream.app.ui.theme.paint
import com.raddstream.app.viewmodel.PlayerEvent
import com.raddstream.app.viewmodel.PlayerViewModel
import com.raddstream.app.viewmodel.formatTime
import kotlinx.coroutines.delay
import kotlin.math.roundToInt

/**
 * The MX-style player screen (PLAYER_SPEC.md §2). Decomposed into small composables so every
 * zone is readable in isolation:
 *
 *  - [PlayerSurface] — Media3 `PlayerView` with `useController=false`; aspect + subtitle
 *    styling only (all chrome is Compose).
 *  - [GestureOverlay] — the researched gesture table (PLAYER_SPEC §2.1), decisions delegated
 *    to the pure `GestureMapper`; tap / boost-release / drag / pinch live in independent
 *    `pointerInput` lanes so they never fight over events.
 *  - [TopBar] / [CenterControls] / [BottomControls] — three-zone fading chrome with the MX
 *    bottom button row (subtitles, audio, speed, lock, ±10s, frame-step, next episode,
 *    sleep, aspect, rotate, audio-only, stereo-select, cinema, PiP).
 *  - [EdgeHud] — what the same three zones collapse to in Ghost mode
 *    ([com.raddstream.app.player.ViewMode.PURE_CINEMA]): no pause scrim, no centre button,
 *    only edge chips and a 2dp progress line.
 *  - Sheets/dialogs — speed, sleep timer (fade-out), subtitle settings (sync applies to
 *    both render paths), tracks, prints + failover log, resume prompt, pack calibration,
 *    play-from, give-up card with the four §5 handoff reasons.
 *  - [SubtitleOverlay] — custom-rendered external SRT/VTT (delay read straight from the
 *    settings); embedded and Media3-parsed tracks get the same delay from the service's
 *    decoder wrapper.
 *  - [KeepChip] — signature "watching → keeping" affordance fed by `ProgressiveCacheEngine`
 *    snapshots through [CacheAffordance].
 *
 * Entry points: the `streamId`/`title` route the NavGraph uses (an opaque handle of ours,
 * never an upstream address), plus a title-only overload for bundle-driven navigation.
 */
@Composable
fun PlayerScreen(
    streamId: String,
    title: String,
    onBackClick: () -> Unit,
    onPlayNextEpisode: (workKey: String?, postId: Int?, season: Int, episode: Int) -> Unit = { _, _, _, _ -> },
    localUri: String? = null,
    // SC §3 (Session 126): tapping an actor on the pause strip searches them, the
    // same route the detail screen's cast chips take. NAV-4: the expired-link
    // card's Home button.
    onActorClick: (String) -> Unit = {},
    onHomeClick: (() -> Unit)? = null,
    viewModel: PlayerViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()
    LaunchedEffect(streamId, localUri) {
        if (!localUri.isNullOrBlank()) {
            viewModel.startLocalUri(localUri, title)
        } else if (streamId.isNotBlank()) {
            viewModel.startStreamHandle(streamId, title)
        }
    }
    PlayerScreenContent(state, viewModel, onBackClick, onPlayNextEpisode, onActorClick, onHomeClick)
}

/** Bundle-driven entry (PlayBundle already installed into the session store by the caller). */
@Composable
fun PlayerScreen(
    title: String,
    onBackClick: () -> Unit,
    onPlayNextEpisode: (workKey: String?, postId: Int?, season: Int, episode: Int) -> Unit = { _, _, _, _ -> },
    onActorClick: (String) -> Unit = {},
    onHomeClick: (() -> Unit)? = null,
    viewModel: PlayerViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()
    PlayerScreenContent(state, viewModel, onBackClick, onPlayNextEpisode, onActorClick, onHomeClick)
}

// ── Root ───────────────────────────────────────────────────────────────────────

@OptIn(UnstableApi::class, ExperimentalMaterial3Api::class)
@Composable
private fun PlayerScreenContent(
    state: PlayerUiState,
    vm: PlayerViewModel,
    onBackClick: () -> Unit,
    onPlayNextEpisode: (workKey: String?, postId: Int?, season: Int, episode: Int) -> Unit,
    onActorClick: (String) -> Unit = {},
    onHomeClick: (() -> Unit)? = null,
) {
    val context = LocalContext.current
    val activity = remember(context) { context.findActivity() }
    // The chrome theme this device wears: resolved once here and handed to the
    // transient overlays that take no state of their own; the stateful chrome
    // pieces resolve it from `state.playerTheme` themselves.
    val chrome = PlayerChromeTheme.forId(state.playerTheme)

    // BM rule 9: low-end devices get solid chrome, not frosted glass — the
    // blur is a cost they pay for nothing, and a solid plate reads the same.
    val lowRam = remember(context) {
        (context.getSystemService(Context.ACTIVITY_SERVICE) as? ActivityManager)?.isLowRamDevice == true
    }

    // System Back always leaves the player (Session 117): the give-up card's
    // AlertDialog declines Back while it is showing (PL-13: an outside tap is
    // keep-waiting, Back is exit), and the top-left arrow always worked, but
    // nothing handled Back during playback — the 114 device retest pressed it
    // three times on a stuck player and once while the card was up, and the
    // player never exited. This handler is the fallback underneath the dialog's
    // own: it is registered first, so a dialog or sheet that is showing wins
    // the press (its handler was added later and both end in the same place —
    // back to details), and with
    // nothing showing, Back pops the player instead of doing nothing. The
    // lock does not gate it: a locked player must still let its viewer out.
    BackHandler { onBackClick() }

    var controlsVisible by remember { mutableStateOf(true) }
    var interactTick by remember { mutableStateOf(0L) }
    var brightness by remember { mutableFloatStateOf(-1f) } // -1 → follow system
    var hud by remember { mutableStateOf<Hud?>(null) }
    var snackbar by remember { mutableStateOf<String?>(null) }
    var scrubPreviewMs by remember { mutableStateOf<Long?>(null) }

    // Scrub thumbnails (API 23+ only): a second, muted ExoPlayer that renders
    // the frame at the scrub target into the toast's TextureView. Created
    // lazily on the first scrub; null on Android 5, where the toast stays
    // time-only, exactly as now. Released when this screen leaves.
    var scrubPreviewPlayer by remember { mutableStateOf<ScrubPreviewPlayer?>(null) }
    // The target the thumbnail is actually showing. It trails scrubPreviewMs
    // by ScrubThumbnails.SETTLE_MS (see the LaunchedEffect below): during a
    // fast drag the preview player never settles, so the toast shows only
    // the time until the finger pauses and a real frame is ready.
    var scrubSettledMs by remember { mutableStateOf<Long?>(null) }
    DisposableEffect(scrubPreviewPlayer) {
        onDispose { scrubPreviewPlayer?.release() }
    }

    val showCoach by vm.showCoach.collectAsState()
    var coachDismissed by remember { mutableStateOf(false) }

    // PL-10: the PiP window follows the video's own shape, and the source rect is
    // the surface's own bounds — the window grows out of the picture, not the corner.
    var pipSourceRect by remember { mutableStateOf<androidx.compose.ui.geometry.Rect?>(null) }
    val launchPip = rememberPipLauncher(aspectRatio = state.videoAspectRatio, sourceRect = pipSourceRect)
    PlayerEventWatcher(vm, context, onPlayNextEpisode) { snackbar = it }

    // PL-10: opt-in auto-enter PiP — when the switch is on and the title is playing,
    // leaving the player (home, recents, another app) keeps it playing in a window.
    // Off by default: a window the viewer did not open is a window they did not ask for.
    // The screen is always hosted by the Activity, so its context is the owner;
    // lifecycle-runtime-compose is not a dependency, so no LocalLifecycleOwner.
    val lifecycleOwner = context as LifecycleOwner
    DisposableEffect(lifecycleOwner, state.autoPip, state.isPlaying) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_PAUSE && state.autoPip && state.isPlaying) launchPip()
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    // Immersive fullscreen + keep-screen-on while the player exists (MX behaviour).
    DisposableEffect(activity) {
        val window = activity?.window
        window?.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val insets = window?.let { WindowInsetsControllerCompat(it, it.decorView) }
        insets?.systemBarsBehavior =
            WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        insets?.hide(WindowInsetsCompat.Type.systemBars())
        val originalBrightness = window?.attributes?.screenBrightness
        // Session 157 (S4): playback starts in forced landscape, not
        // sensor landscape. A sensor reading only picks which landscape the
        // device is already in — on a device whose sensor is fixed, flat
        // or slow (a cloud device, an emulator) it can hold the player in
        // portrait while a landscape picture plays sideways. Forced
        // landscape is what "play this video" means; the rotate button's
        // portrait branch below still follows the sensor.
        activity?.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
        onDispose {
            window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            insets?.show(WindowInsetsCompat.Type.systemBars())
            window?.let {
                val attrs = it.attributes
                attrs.screenBrightness =
                    originalBrightness ?: WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE
                it.attributes = attrs
            }
            // Session 158 (S5): UNSPECIFIED alone does not snap the app
            // back on a device whose rotation is locked (a cloud device,
            // or a phone with auto-rotate off) — after exiting the Salaar
            // player the detail stayed landscape while the device frame
            // was portrait, until the tester rotated the device. Ask the
            // sensor once, so the app follows how the device is actually
            // held right now, then release back to neutral a second later
            // so the rest of the app is not sensor-driven forever. The
            // delayed post survives the composition (it is tied to the
            // decor view, not the composable) and is a no-op on a
            // finishing activity.
            activity?.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_SENSOR
            activity?.window?.decorView?.postDelayed(
                { activity?.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED },
                1_000L,
            )
        }
    }

    // Fullscreen toggle: immersive (bars hidden) ↔ normal (bars shown). Entry hides
    // them in the DisposableEffect above; this effect applies every later flip, and
    // the dispose step still restores the bars when the player leaves.
    LaunchedEffect(state.fullscreen) {
        val window = activity?.window ?: return@LaunchedEffect
        val insets = WindowInsetsControllerCompat(window, window.decorView)
        if (state.fullscreen) insets.hide(WindowInsetsCompat.Type.systemBars())
        else insets.show(WindowInsetsCompat.Type.systemBars())
    }

    // Brightness override from the left-half vertical gesture.
    LaunchedEffect(brightness) {
        activity?.let { a ->
            val attrs = a.window.attributes
            attrs.screenBrightness = brightness.coerceIn(-1f, 1f)
            a.window.attributes = attrs
        }
    }

    // Manual orientation (rotate button). configChanges on MainActivity keeps playback alive.
    // Session 157 (S4): the landscape branch is forced, matching the entry
    // effect above — the orientation state is the source of truth, and its
    // first composition would otherwise overwrite the forced request with
    // the sensor one. The portrait branch keeps the sensor, so an explicit
    // flip to portrait still follows how the viewer holds the device.
    LaunchedEffect(state.orientation) {
        activity?.requestedOrientation = when (state.orientation) {
            PlayerOrientation.LANDSCAPE -> ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
            PlayerOrientation.PORTRAIT -> ActivityInfo.SCREEN_ORIENTATION_SENSOR_PORTRAIT
        }
    }

    // Auto-hide the chrome 3.0 s into uninterrupted playback.
    LaunchedEffect(controlsVisible, state.isPlaying, interactTick, state.dialogBlocking) {
        if (controlsVisible && state.isPlaying && !state.dialogBlocking) {
            delay(3000)
            if (state.isPlaying) controlsVisible = false
        }
    }

    // First-run gesture coach (plan §5 step 7): owed once per major version, shown
    // only once the picture is actually moving — never over a loading notice, an error,
    // a dialog, a sheet, or a locked player. Four seconds, then never again this version.
    val coachVisible = showCoach && !coachDismissed && !state.dialogBlocking &&
        !state.moreSheetVisible && !state.locked && state.connectionError == null && state.isPlaying
    LaunchedEffect(coachVisible) {
        if (coachVisible) {
            delay(4000)
            coachDismissed = true
            vm.markCoachSeen()
        }
    }

    // Double-tap ripple lifetime (nonce-keyed).
    LaunchedEffect(state.ripple?.nonce) {
        if (state.ripple != null) {
            delay(900)
            vm.clearRipple()
        }
    }

    // HUD + settled banner fades.
    LaunchedEffect(hud) {
        if (hud != null) {
            delay(800)
            hud = null
        }
    }
    LaunchedEffect(snackbar) {
        if (snackbar != null) {
            delay(3000)
            snackbar = null
        }
    }
    LaunchedEffect(state.settledBanner) {
        if (state.settledBanner != null) {
            delay(5000)
            vm.dismissSettledBanner()
        }
    }

    // Scrub thumbnails (API 23+ only): every scrub target seeks the preview
    // player at once — ExoPlayer coalesces rapid seeks, so a fast drag just
    // keeps retargeting and the player renders once the finger pauses. The
    // thumbnail itself waits SETTLE_MS after the last move: until then the
    // TextureView would show the frame from the last settled position, which
    // is the wrong scene for the time the toast prints. On Android 5 this
    // whole effect is a no-op (no preview player exists) and the toast stays
    // time-only, exactly as now. The Scrubber (bottom bar) does not come
    // through here — it seeks the main player directly, so the picture
    // itself is already the preview and no thumbnail is owed.
    LaunchedEffect(scrubPreviewMs, state.activeRendition) {
        val target = scrubPreviewMs
        if (target == null) {
            scrubSettledMs = null
            return@LaunchedEffect
        }
        // Hide the thumbnail the moment the target moves: the frame on screen
        // is from the last settled position, and showing it against the new
        // time would be the wrong scene. It comes back SETTLE_MS after the
        // finger stops, once the preview player has rendered this target.
        scrubSettledMs = null
        if (ScrubThumbnails.isSupported()) {
            val preview = scrubPreviewPlayer ?: ScrubPreviewPlayer(context.applicationContext).also {
                scrubPreviewPlayer = it
            }
            state.activeRendition?.let { preview.setRendition(it) }
            preview.previewAt(target)
        }
        delay(ScrubThumbnails.SETTLE_MS)
        scrubSettledMs = target
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(chrome.background),
    ) {
        // 1 — video surface or audio-only placeholder
        if (state.audioOnly) {
            AudioOnlySurface(
                title = state.pendingTitle ?: state.activeRendition?.displayLabel() ?: stringResource(R.string.player_audio_title),
                isPlaying = state.isPlaying,
            )
        } else {
            PlayerSurface(vm, state, onBounds = { pipSourceRect = it })
        }

        // D-35: the poster's blurred shadow behind the loading state. The window before
        // the first frame is the one a viewer cannot tell apart from a crash, and a black
        // void is the worst thing to show in it — so the staged poster sits dimmed and
        // blurred behind the notice card, with the real progress ring on top. (Blur is a
        // no-op below API 31; the scrim carries the dimming there.) It stands down the
        // moment the picture starts, and a deep link with no staged poster shows none.
        if (state.startPhase != StartPhase.NONE && !state.posterUrl.isNullOrBlank()) {
            Box(Modifier.fillMaxSize()) {
                CatalogImage(
                    url = state.posterUrl,
                    contentDescription = null,
                    modifier = Modifier
                        .fillMaxSize()
                        .blur(24.dp),
                    contentScale = ContentScale.Crop,
                )
                Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.55f)))
            }
        }

        // 2 — our own subtitle overlay (external SRT/VTT with delay)
        SubtitleOverlay(state, vm)

        // 3 — gesture plane (single full-screen layer, lanes split by pointerInput)
        GestureOverlay(
            state = state,
            vm = vm,
            onToggleControls = {
                controlsVisible = !controlsVisible
                interactTick = System.nanoTime()
            },
            onBrightness = { frac ->
                if (brightness < 0f) {
                    // PL-9: the drag starts where the screen already is — the window's
                    // own brightness first, then the system brightness — never an
                    // assumed 0.5 that jumps a dim screen to half brightness on touch.
                    val windowBrightness = activity?.window?.attributes?.screenBrightness ?: -1f
                    val system01 = runCatching {
                        Settings.System.getInt(
                            context.contentResolver,
                            Settings.System.SCREEN_BRIGHTNESS,
                            -1,
                        ).takeIf { it >= 0 }?.div(255f)
                    }.getOrNull()
                    brightness = initialBrightnessBase(windowBrightness, system01)
                }
                brightness = (brightness + frac).coerceIn(0f, 1f)
                hud = Hud.Brightness(brightness)
            },
            onVolume = { frac ->
                val v = (state.userVolume + frac).coerceIn(0f, 1f)
                vm.setUserVolume(v)
                hud = Hud.Volume(v)
            },
            onScrubPreview = { scrubPreviewMs = it },
            onScrubCommit = {
                vm.seekTo(it)
                scrubPreviewMs = null
                interactTick = System.nanoTime()
            },
            onBoostStart = {
                vm.beginBoost()
                hud = Hud.Boost
            },
            onBoostEnd = vm::endBoost,
        )

        // 4 — transient feedback layers
        DoubleTapRipple(state)
        hud?.let { HudToast(it, chrome) }
        scrubPreviewMs?.let { target ->
            ScrubToast(
                target = target,
                durationMs = state.durationMs,
                previewPlayer = scrubPreviewPlayer,
                // The thumbnail only shows once the target has settled: while
                // dragging, the frame on screen is from the last settled
                // position — the wrong scene for the time the toast prints.
                showThumbnail = ScrubThumbnails.shouldShowThumbnail(
                    settledMs = scrubSettledMs,
                    targetMs = target,
                    previewAvailable = scrubPreviewPlayer != null,
                ),
            )
        }
        if (state.boosting) BoostBadge()

        // 5 — chrome. Ghost mode paints only the edge strip; everything else keeps the
        // three-zone MX bars, the pause scrim and the big centre button.
        // Session 121 (P-17): while the player is still starting there is no picture
        // to protect and no back button anywhere — the top bar (or the edge strip
        // in Ghost mode) stays up until the start phase ends, even if the viewer
        // tapped the chrome away. The centre controls and the bottom bar still
        // obey the tap; only the way out is forced visible.
        val chromeVisible = controlsVisible || state.startPhase != StartPhase.NONE
        if (chromeVisible && !state.locked) {
            if (state.pureCinema) {
                EdgeHud(state = state, vm = vm, onBack = onBackClick)
            } else {
                TopBar(vm = vm, state = state, onBack = onBackClick)
                if (controlsVisible) {
                    CenterControls(state, vm)
                    BottomControls(
                        state = state,
                        vm = vm,
                        onEnterPip = launchPip,
                        onActivity = { interactTick = System.nanoTime() },
                        onActorClick = onActorClick,
                        onMessage = { snackbar = it },
                    )
                }
            }
        }
        if (state.locked) {
            UnlockFab(chrome, onUnlock = { vm.setLocked(false) })
        }

        // 6 — narration cards
        state.settledBanner?.let { banner ->
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.TopCenter) {
                Surface(
                    color = RaddNarrationPlate,
                    shape = MaterialTheme.shapes.small,
                    modifier = Modifier
                        .padding(horizontal = 16.dp)
                        .padding(top = 60.dp)
                        .clickableNoRipple { vm.dismissSettledBanner() },
                ) {
                    Row(
                        Modifier.padding(horizontal = 14.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(Icons.Default.Check, null, tint = RaddNarrationCheck, modifier = Modifier.size(16.dp))
                        Spacer(Modifier.width(8.dp))
                        Text(banner, color = Color.White, fontSize = brandSp(14), maxLines = 2, overflow = TextOverflow.Ellipsis)
                    }
                }
            }
        }

        // Samsung RTL retest (Issue 7): "Back to details" must dismiss the
        // card even when the pop itself cannot run yet. Clearing the card's
        // own state first means the tap is visibly answered at once — the
        // card is gone whatever the pop does — and the pop then leaves the
        // player. A tap that only pops leaves the same card on screen
        // whenever the pop is swallowed, or when the Detail underneath
        // re-pushes the player on return (its autoplay effect re-fires on
        // a fresh composition), which reads exactly as "the button did
        // nothing". Both give-up sources clear here: the handoff card is
        // store-driven, the deadline card is state-driven.
        val backToDetails = { vm.dismissGiveUp(); vm.dismissDeadlineGiveUp(); onBackClick() }

        state.giveUp?.let { (message, why) ->
            GiveUpCard(
                message = message,
                why = why,
                onRetry = { vm.retryCurrentCandidates() },
                onExternal = { vm.openWithExternalPlayer() },
                onDismiss = { vm.dismissGiveUp() },
                onBackToDetails = backToDetails,
                // NAV-4: an expired shared link gets its own way home.
                onHomeClick = onHomeClick,
                // Session 120: the deadline card offered this and the handoff
                // card did not, so after every candidate failed the viewer
                // could only retry the same dead ladder. A further print past
                // max_ranks is still an honest manual hop — tryNextPrint
                // moves to a different print, never the same URL again.
                onTryAnother = if (state.canTryAnotherPrint) {
                    { vm.tryNextPrint() }
                } else {
                    null
                },
            )
        } ?: if (state.deadlineGiveUp) {
            // The 30 s hard deadline (§5 P5): no candidate failed, but none produced a
            // frame in time. The card is the same one the service shows, with the timeout
            // reason and the third action the plan promises — try another print now.
            // Dismissing it keeps waiting with a fresh thirty seconds.
            GiveUpCard(
                message = stringResource(R.string.player_start_giveup_message),
                why = HandoffWhy.START_TIMEOUT,
                onRetry = { vm.retryCurrentCandidates() },
                onExternal = { vm.openWithExternalPlayer() },
                onDismiss = { vm.dismissDeadlineGiveUp() },
                onBackToDetails = backToDetails,
                onHomeClick = onHomeClick,
                onTryAnother = if (state.canTryAnotherPrint) {
                    { vm.tryNextPrint() }
                } else {
                    null
                },
            )
        } else {
            // Neither a give-up nor a deadline expiry is showing.
        }

        // PL-14: the connection-error card and the give-up card are mutually
        // exclusive — they used to stack on the same failure, two cards saying
        // the same thing in different words. The give-up card is the one that
        // stays; the connection error owns only the failures it does not cover.
        if (state.connectionError != null && state.giveUp == null && !state.deadlineGiveUp) {
            state.connectionError?.let { err ->
                ConnectionErrorCard(err, onRetry = { vm.retryCurrentCandidates() })
            }
        }

        // PL-3: an offline start or an offline failure shows an offline card
        // immediately, with Retry — not just the 30-second deadline card. Waiting
        // half a minute to be told there is no network is not a wait, it is a lie.
        if (state.isOffline && state.giveUp == null && !state.deadlineGiveUp) {
            OfflineCard(onRetry = { vm.retryCurrentCandidates() })
        }

        // PL-4: a locked player keeps a small time chip visible — position and
        // remaining, without unlocking. A locked screen that says nothing about
        // where you are is a screen that says nothing at all. A duration the
        // player has not learned yet is not a time to show. F29 (Batch B): a
        // live stream has no remaining to show, so the chip stays down.
        if (state.locked && !state.isLive && state.durationMs > 0) {
            LockedTimeChip(
                positionMs = state.positionMs,
                durationMs = state.durationMs,
                lowRam = lowRam,
                modifier = Modifier
                    .align(Alignment.BottomStart)
                    .padding(12.dp),
            )
        }

        if (state.isBuffering && !state.isPlaying && state.giveUp == null &&
            state.startPhase == StartPhase.NONE
        ) {
            // Robo run 7: the loading notice's title was unreadable over the
            // frame on a translucent plate — the same rule holds here. The
            // bare "Buffering…" sat directly on the video frame; it gets the
            // notice's solid plate, so the wait is readable over any frame.
            Surface(
                color = RaddPlayerStage,
                shape = MaterialTheme.shapes.medium,
                modifier = Modifier.align(Alignment.Center),
            ) {
                // F4 (Batch B): the notice names how much is buffered ahead
                // ("Buffering… 42%") on a VOD, so a stall shows progress, not
                // just a spinner. A live stream never shows a percent — see
                // [bufferingPercent].
                val bufferedPct = bufferingPercent(state.bufferedMs, state.durationMs, state.isLive)
                PlayerLoadingIndicator(
                    label = if (bufferedPct != null) {
                        stringResource(R.string.player_buffering_percent, bufferedPct)
                    } else {
                        stringResource(R.string.player_buffering)
                    },
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
                )
            }
        }

        // The window before the first frame is the one a viewer cannot tell apart from a
        // crash, so it is the one window the player narrates out loud. It survives the lock
        // and Ghost mode for the same reason the buffering spinner does: feedback is not
        // furniture. Past two seconds the card gains the slow line (§5 P5); past eight it
        // gains something to press. At thirty seconds the deadline card owns the screen
        // instead, so this notice stands down.
        if (state.startPhase != StartPhase.NONE &&
            state.startDeadlineStage != StartDeadlineStage.GIVE_UP
        ) {
            val actions = state.startDeadlineStage == StartDeadlineStage.ACTIONS
            // Session 121 (P-36): the 30-second wait showed no progress at all. When
            // the bundle has more than one copy, say which one is being tried — the
            // active rendition's place in the bundle is the attempt number, and the
            // bundle's size is the total. One copy needs no counter.
            val attemptLabel = run {
                val renditions = state.bundle?.renditions.orEmpty()
                if (renditions.size <= 1) {
                    null
                } else {
                    val index = state.activeRendition?.let { renditions.indexOf(it) }
                        ?.takeIf { it >= 0 } ?: 0
                    stringResource(R.string.player_attempt_counter, index + 1, renditions.size)
                }
            }
            StartNoticeCard(
                phase = state.startPhase,
                title = state.pendingTitle,
                attemptLabel = attemptLabel,
                slowHint = state.startDeadlineStage != StartDeadlineStage.SILENT,
                // 26: the three-step progress story — the label names the step
                // being done, not the generic phase: finding the best print,
                // then warming the link, then buffering.
                stepLabel = when (state.startPhase) {
                    StartPhase.CONNECTING_PLAYER -> stringResource(R.string.player_step_finding)
                    StartPhase.STARTING -> stringResource(R.string.player_step_warming)
                    else -> stringResource(R.string.player_step_buffering)
                },
                // Session 121 (P-7): the rung label must name a rung. The display label
                // used to fall back to the print's title, so the notice read
                // "Quality: Ali Baba aur 40 Bhoot"; a non-quality label falls through
                // to the band label instead, and the line is dropped when neither
                // names a rung.
                rungLabel = if (state.startDeadlineStage != StartDeadlineStage.SILENT) {
                    state.activeRendition?.displayLabel()?.takeIf { looksLikeQualityLabel(it) }
                        ?: state.qualityLabel.takeIf { it.isNotBlank() && looksLikeQualityLabel(it) }
                } else {
                    null
                },
                // P-3: the elapsed line counts from the request, so the
                // resolve wait is counted too (see StartDeadline).
                waitElapsedMs = state.startRequestElapsedMs,
                onRetry = if (actions) {
                    { vm.retryCurrentCandidates() }
                } else {
                    null
                },
                onTryAnother = if (actions && state.canTryAnotherPrint) {
                    { vm.tryNextPrint() }
                } else {
                    null
                },
                onCancel = onBackClick,
            )
        }

        if (state.isEnded && controlsVisible && !state.locked && !state.pureCinema) {
            // Session 123 (PL-1): while the countdown runs the ended overlay is
            // the countdown, not the buttons — one clear action, Cancel.
            val countdown = state.autoplayCountdownSeconds
            if (countdown != null) {
                AutoplayCountdownCard(
                    chrome,
                    secondsLeft = countdown,
                    onCancel = { vm.cancelAutoplayCountdown() },
                    nextEpisodeTitle = state.nextEpisodeTitle,
                    onPlayNow = { vm.requestNextEpisode() },
                )
            } else {
                EndedButtons(
                    chrome,
                    showNextEpisode = state.endedHasNextEpisode,
                    onPlayAgain = { vm.playFrom(0) },
                    onNextEpisode = { vm.requestNextEpisode() },
                    nextEpisodeTitle = state.nextEpisodeTitle,
                    nextEpisodeSeason = state.nextEpisodeSeason,
                    nextEpisodeEpisode = state.nextEpisodeEpisode,
                    nextEpisodePosterUrl = state.nextEpisodePosterUrl,
                )
            }
        }

        // 7 — dialogs & sheets (VM-flag driven so every entry point is centralized)
        ResumeDialog(state, vm)
        state.calibration?.let { cal ->
            CalibrationDialog(
                state = cal,
                onConfirm = { episode -> vm.calibrateEpisodeStart(episode) },
                onDismiss = { vm.dismissCalibration() },
            )
        }
        if (state.playFromDialogVisible) {
            PlayFromDialog(
                onSubmit = { ms ->
                    vm.playFrom(ms)
                    vm.hidePlayFromDialog()
                },
                onDismiss = { vm.hidePlayFromDialog() },
            )
        }
        if (state.speedSheetVisible) SpeedSheet(state, vm)
        if (state.sleepSheetVisible) SleepSheet(state, vm)
        if (state.subtitleSheetVisible) SubtitleSettingsSheet(state, vm)
        if (state.subtitleOffsetSheetVisible) {
            SubtitleOffsetSheet(
                offsetMs = state.subtitle.delayMs,
                hasCustomOverlay = state.customSubtitleLoaded != null,
                onOffsetChange = { vm.setSubtitleOffset(it) },
                onDismiss = { vm.hideSubtitleOffsetSheet() },
            )
        }
        if (state.tracksSheetVisible) TracksSheet(state, vm)
        if (state.printSheetVisible) PrintLogSheet(state, vm)
        if (state.qualitySheetVisible) QualitySheet(state, vm)
        if (state.moreSheetVisible) MoreSheet(state, vm, onEnterPip = launchPip)

        // 8 — lightweight snackbar. F4 (Batch A): suppressed while a start card is
        // showing — in landscape (~360dp tall) the card's bottom edge sits where
        // this bar lands, so the two overlapped and neither was readable. The
        // message is not lost: it reappears on the next start-phase-free frame
        // because the snackbar state lives in the ViewModel, not in this Box.
        if (state.startPhase == StartPhase.NONE) {
            snackbar?.let { msg ->
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.BottomCenter) {
                    Surface(
                        color = RaddPlayerSnackbarPlate,
                        shape = MaterialTheme.shapes.small,
                        modifier = Modifier
                            .padding(horizontal = 24.dp)
                            .padding(bottom = 100.dp),
                    ) {
                        Text(msg, color = Color.White, fontSize = brandSp(14), modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp))
                    }
                }
            }
        }

        // 9 — first-run gesture coach (plan §5 step 7): once per major version, 4 s,
        // any tap dismisses. Sits above the chrome and the narration cards; sheets and
        // dialogs are gated out by the visibility rule above, so it never covers one.
        if (coachVisible) {
            PlayerCoachOverlay(
                onDismiss = {
                    coachDismissed = true
                    vm.markCoachSeen()
                },
            )
        }
    }
}

/**
 * How long after a two-finger rewind the single-tap chrome toggle stays suppressed. The
 * two lanes see the same up event in different passes, so this is a safety margin for the
 * one that wins by a hair — not a debounce a user can feel.
 */
private const val TWO_FINGER_TAP_GUARD_NS = 250_000_000L

/**
 * True when a sheet the viewer opened is up — pauses the controls auto-hide.
 *
 * Session 126 (audit bug a): the More sheet was missing from this list, so the
 * chrome auto-hid three seconds into a More-sheet browse and the viewer had to
 * tap back in to read the rows they had just opened. Every sheet that can hold
 * the viewer's attention belongs here — including More, which is a sheet like
 * any other. (The old paragraph about the sponsor slot is gone with the slot
 * itself: PL-2 removed the placeholder ad entirely, and there is no ad state
 * left in this file to exclude.)
 */
private val PlayerUiState.dialogBlocking: Boolean
    get() = resumeOfferMs != null || calibration != null || giveUp != null ||
        speedSheetVisible || tracksSheetVisible || subtitleSheetVisible ||
        subtitleOffsetSheetVisible || printSheetVisible || sleepSheetVisible ||
        playFromDialogVisible || qualitySheetVisible || moreSheetVisible

// ── 1. Surface ─────────────────────────────────────────────────────────────────

// Fully qualified on purpose: this file also uses Kotlin's `@OptIn` for
// ExperimentalMaterial3Api, and the two annotations answer different checkers. Media3's
// `UnsafeOptInUsageError` is a *lint* check that reads `androidx.annotation.OptIn` only, so the
// Kotlin form here compiled clean and left 20 lint errors.
@androidx.annotation.OptIn(UnstableApi::class)
@Composable
private fun PlayerSurface(
    vm: PlayerViewModel,
    state: PlayerUiState,
    // PL-10: the surface reports its own bounds so the PiP window can grow
    // out of the picture.
    onBounds: ((androidx.compose.ui.geometry.Rect) -> Unit)? = null,
) {
    val player by vm.player.collectAsState()
    AndroidView(
        modifier = Modifier
            .fillMaxSize()
            .then(
                if (onBounds != null) {
                    Modifier.onGloballyPositioned { onBounds(it.boundsInWindow()) }
                } else {
                    Modifier
                },
            ),
        factory = { ctx ->
            PlayerView(ctx).apply {
                useController = false // all chrome is Compose
                resizeMode = AspectRatioFrameLayout.RESIZE_MODE_FIT
                setShutterBackgroundColor(android.graphics.Color.BLACK)
                layoutParams = FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT,
                )
            }
        },
        update = { view ->
            if (view.player !== player) view.player = player
            view.resizeMode = state.aspect.resizeMode
            styleNativeSubtitles(view, state)
        },
    )
}

/**
 * Native embedded-subtitle rendering (size/position/colors) — every call below was verified
 * public in media3-ui 1.3.1. Sync is applied below this layer by the service's decoder
 * wrapper, so this styling and the custom SRT/VTT overlay ([SubtitleOverlay]) agree.
 *
 * Both paths read the ONE [PlayerUiState.subtitle] snapshot, which is why the viewer's picked
 * colour and weight land on an embedded track exactly as they land on an external SRT: the
 * sheet never has to say which renderer a file happens to use.
 */
@androidx.annotation.OptIn(UnstableApi::class)
private fun styleNativeSubtitles(view: PlayerView, state: PlayerUiState) {
    val sv: SubtitleView = view.subtitleView ?: return
    val s = state.subtitle
    sv.setFractionalTextSize(
        SubtitleView.DEFAULT_TEXT_SIZE_FRACTION * s.sizePercent / 100f,
        false,
    )
    sv.setBottomPaddingFraction(s.bottomFraction)
    sv.setStyle(
        CaptionStyleCompat(
            s.colour.argb,
            if (s.textBackground) RaddCaptionPlateArgb else android.graphics.Color.TRANSPARENT,
            android.graphics.Color.TRANSPARENT,
            CaptionStyleCompat.EDGE_TYPE_NONE,
            android.graphics.Color.BLACK,
            // Bold was overlay-only until the sheet persisted the style; the native path has
            // always had a typeface slot, it was simply never filled.
            if (s.bold) Typeface.DEFAULT_BOLD else null,
        ),
    )
    // Robo run 4: embedded styles were applied on top of the viewer's own
    // colour, so a track that styles its cues dark renders black text on a
    // black frame — invisible subtitles, and a 1.03:1 contrast flag. The
    // viewer's picked colour (bright by the SubtitleColor rule, white by
    // default) is the readable one, so it wins over whatever the file says.
    // Position/size still come from the viewer's snapshot below.
    sv.setApplyEmbeddedStyles(false)
}

@Composable
private fun AudioOnlySurface(title: String, isPlaying: Boolean) {
    Box(Modifier.fillMaxSize().background(RaddPlayerStage), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Icon(Icons.Default.MusicNote, null, tint = RaddCurrent500, modifier = Modifier.size(72.dp))
            Spacer(Modifier.height(12.dp))
            Text(
                title,
                color = Color.White,
                style = MaterialTheme.typography.titleMedium,
                textAlign = TextAlign.Center,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.padding(horizontal = 32.dp),
            )
            Spacer(Modifier.height(6.dp))
            Text(
                if (isPlaying) stringResource(R.string.player_audio_only_active)
                else stringResource(R.string.player_audio_only_paused),
                color = Color.White.copy(alpha = 0.6f),
                fontSize = brandSp(12),
            )
        }
    }
}

// ── 3. Gesture plane ───────────────────────────────────────────────────────────

@Composable
private fun GestureOverlay(
    state: PlayerUiState,
    vm: PlayerViewModel,
    onToggleControls: () -> Unit,
    onBrightness: (Float) -> Unit,
    onVolume: (Float) -> Unit,
    onScrubPreview: (Long) -> Unit,
    onScrubCommit: (Long) -> Unit,
    onBoostStart: () -> Unit,
    onBoostEnd: () -> Unit,
) {
    val settings = GestureSettings(
        lockGestures = state.locked,
        pureCinema = state.pureCinema,
    )
    // Values that must be fresh inside long-lived pointer loops:
    val latestSettings by rememberUpdatedState(settings)
    val latestDuration by rememberUpdatedState(state.durationMs)
    val latestPosition by rememberUpdatedState(state.positionMs)
    /**
     * Stamp of the last confirmed two-finger tap. The two-finger lane below watches the
     * Initial pass, which every frame delivers before the Main pass the tap lane reads, so
     * by the time `detectTapGestures` decides an up was a tap this stamp is already set —
     * one two-finger tap rewinds, it does not also toggle the chrome. A stamp rather than
     * consumption: consuming the pointers here would silently kill pinch-to-zoom, which
     * needs the same two fingers.
     */
    val twoFingerStamp = remember { LongArray(1) }

    Box(
        Modifier
            .fillMaxSize()
            // Lane E — two fingers down, still, together → the Ghost rewind. Reads only, never
            // consumes, so lanes A–D keep working exactly as they did.
            .pointerInput(Unit) {
                awaitEachGesture {
                    val down = awaitFirstDown(requireUnconsumed = false)
                    val origins = hashMapOf(down.id.value to down.position)
                    val slop = viewConfiguration.touchSlop
                    var sawSecondPointer = false
                    var moved = false
                    while (true) {
                        val event = awaitPointerEvent(PointerEventPass.Initial)
                        // Both fingers in one frame counts, even if only one of them is a
                        // pointer we happened to see go down: index-then-thumb and a true
                        // simultaneous tap must behave the same.
                        if (event.changes.size >= 2) sawSecondPointer = true
                        event.changes.filter { it.pressed }.forEach { change ->
                            val at = origins[change.id.value]
                            if (at == null) {
                                origins[change.id.value] = change.position
                                if (origins.size >= 2) sawSecondPointer = true
                            } else if (kotlin.math.abs(change.position.x - at.x) > slop ||
                                kotlin.math.abs(change.position.y - at.y) > slop
                            ) {
                                moved = true
                            }
                        }
                        if (event.changes.none { it.pressed }) break
                    }
                    if (sawSecondPointer && !moved) {
                        when (val cmd = GestureMapper.onTwoFingerTap(latestSettings)) {
                            is TapCommand.SeekWithRipple -> {
                                twoFingerStamp[0] = System.nanoTime()
                                vm.seekBy(cmd.deltaMs)
                                vm.showRipple(cmd.zone, cmd.deltaMs)
                            }
                            else -> Unit
                        }
                    }
                }
            }
            // Lane A — taps: single → controls, double → ±10s ripple / play-pause, long → boost
            .pointerInput(Unit) {
                // PointerInputScope.size is an IntSize (width/height), not an Offset.
                val paneSize: androidx.compose.ui.unit.IntSize = this.size
                detectTapGestures(
                    onTap = {
                        val justRewound = System.nanoTime() - twoFingerStamp[0] < TWO_FINGER_TAP_GUARD_NS
                        if (!justRewound &&
                            GestureMapper.onSingleTap(latestSettings) == TapCommand.ToggleControls
                        ) {
                            onToggleControls()
                        }
                    },
                    onDoubleTap = { offset ->
                        when (val cmd = GestureMapper.onDoubleTap(offset.x, paneSize.width.toFloat(), latestSettings)) {
                            is TapCommand.SeekWithRipple -> {
                                vm.seekBy(cmd.deltaMs)
                                vm.showRipple(cmd.zone, cmd.deltaMs)
                            }
                            TapCommand.TogglePlayPause -> vm.togglePlayPause()
                            TapCommand.ToggleControls -> onToggleControls()
                            else -> Unit
                        }
                    },
                    onLongPress = {
                        if (GestureMapper.onLongPress(latestSettings)) onBoostStart()
                    },
                )
            }
            // Lane B — any gesture *release* restores boosted speed (MX boost semantics)
            .pointerInput(Unit) {
                awaitEachGesture {
                    try {
                        awaitFirstDown(requireUnconsumed = false)
                        while (true) {
                            val event = awaitPointerEvent(PointerEventPass.Main)
                            if (event.changes.none { it.pressed }) break
                        }
                    } finally {
                        onBoostEnd()
                    }
                }
            }
            // Lane C — drags: vertical = brightness (left half) / volume (right half);
            //           horizontal = scrub preview+commit
            .pointerInput(Unit) {
                val paneSize: androidx.compose.ui.unit.IntSize = this.size
                awaitEachGesture {
                    val down = awaitFirstDown(requireUnconsumed = false)
                    val startX = down.position.x
                    val startY = down.position.y
                    var lastY = startY
                    var axis: DominantAxis = DominantAxis.NONE
                    val zone = dragHalfZone(startX, paneSize.width.toFloat())
                    val basePosition = latestPosition
                    var scrubTarget: Long? = null
                    try {
                        while (true) {
                            val event = awaitPointerEvent(PointerEventPass.Main)
                            val change = event.changes.firstOrNull { it.id == down.id } ?: break
                            if (!change.pressed) break
                            val totalDx = change.position.x - startX
                            val dy = change.position.y - lastY
                            lastY = change.position.y
                            val totalDy = lastY - startY
                            if (axis == DominantAxis.NONE) {
                                axis = dominantAxis(totalDx, totalDy, viewConfiguration.touchSlop)
                            }
                            when (axis) {
                                DominantAxis.VERTICAL ->
                                    when (val cmd = GestureMapper.onVerticalDrag(zone, dy, paneSize.height.toFloat(), latestSettings)) {
                                        is DragCommand.BrightnessDelta -> onBrightness(cmd.fractionPerSwipe)
                                        is DragCommand.VolumeDelta -> onVolume(cmd.fractionPerSwipe)
                                        else -> Unit
                                    }
                                DominantAxis.HORIZONTAL ->
                                    when (val cmd = GestureMapper.onHorizontalScrub(basePosition, totalDx, paneSize.width.toFloat(), latestDuration, latestSettings)) {
                                        is DragCommand.ScrubTarget -> {
                                            scrubTarget = cmd.targetMs
                                            onScrubPreview(cmd.targetMs)
                                        }
                                        else -> Unit
                                    }
                                DominantAxis.NONE -> Unit
                            }
                            change.consumed.positionChange = true
                        }
                    } finally {
                        if (axis == DominantAxis.HORIZONTAL) {
                            scrubTarget?.let { onScrubCommit(it) }
                        }
                    }
                }
            }
            // Lane D — pinch: expand → ZOOM, squeeze → FIT (mode mapping per PLAYER_SPEC §2.1)
            .pointerInput(Unit) {
                detectTransformGestures { _, _, zoom, _ ->
                    val cause = when {
                        zoom > 1.02f -> "out"
                        zoom < 0.98f -> "in"
                        else -> ""
                    }
                    when (GestureMapper.onPinch(cause, latestSettings)) {
                        PinchCommand.ZoomFill -> vm.setAspect(AspectMode.ZOOM)
                        PinchCommand.ZoomFit -> vm.setAspect(AspectMode.FIT)
                        else -> Unit
                    }
                }
            },
    )
}

// ── 4. Transient feedback ──────────────────────────────────────────────────────

@Composable
private fun DoubleTapRipple(state: PlayerUiState) {
    // A held copy, not the live state: the 900 ms lifetime ends by setting the ripple to null,
    // and the pill that is fading out still has to name the side and the seconds it was showing.
    // Reading the live value first means the frame a tap lands on is never the previous pill's.
    var held by remember { mutableStateOf(state.ripple) }
    val ripple = state.ripple ?: held ?: return
    state.ripple?.let { held = it }
    val forward = ripple.deltaMs >= 0
    val chrome = PlayerChromeTheme.forId(state.playerTheme)
    val label = (if (forward) "+" else "−") + (kotlin.math.abs(ripple.deltaMs) / 1000L) + "s"
    val alignment = when (ripple.zone) {
        ScreenZone.LEFT -> Alignment.CenterStart
        ScreenZone.RIGHT -> Alignment.CenterEnd
        ScreenZone.CENTER -> Alignment.Center
    }
    Box(Modifier.fillMaxSize(), contentAlignment = alignment) {
        // P-3 (emulator audit): the HUD itself is a plain conditional in
        // main now, so this ripple pill is the last fade in the player —
        // and it ignored Reduce Motion. Under reduced motion it crossfades
        // in 30 ms (the NavGraph pattern) instead of riding the effects
        // springs. The acknowledgement still appears rather than arrives:
        // quick in, slow out, so a double-tap over a dark scene is never
        // a flash.
        val reduceMotion = rememberReduceMotion()
        AnimatedVisibility(
            visible = state.ripple != null,
            enter = fadeIn(if (reduceMotion) tween(RaddMotion.FadeWhenReduced) else RaddMotion.fastEffects()),
            exit = fadeOut(if (reduceMotion) tween(RaddMotion.FadeWhenReduced) else RaddMotion.defaultEffects()),
        ) {
            Surface(
                color = chrome.card,
                shape = MaterialTheme.shapes.medium,
                modifier = Modifier.padding(horizontal = 34.dp),
            ) {
                Row(
                    Modifier.padding(horizontal = 14.dp, vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(
                        if (forward) Icons.Default.Forward10 else Icons.Default.Replay10,
                        contentDescription = null,
                        tint = Color.White,
                        modifier = Modifier.size(26.dp),
                    )
                    Spacer(Modifier.width(6.dp))
                    Text(label, color = Color.White, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                }
            }
        }
    }
}

private sealed class Hud {
    data class Brightness(val value: Float) : Hud()
    data class Volume(val value: Float) : Hud()
    object Boost : Hud()
}

@Composable
private fun HudToast(hud: Hud, chrome: PlayerChromeTheme) {
    val icon = when (hud) {
        is Hud.Brightness -> Icons.Default.BrightnessHigh
        is Hud.Volume -> if (hud.value <= 0.01f) Icons.Default.VolumeMute else Icons.Default.VolumeUp
        is Hud.Boost -> Icons.Default.FastForward
    }
    val label = when (hud) {
        is Hud.Brightness -> stringResource(R.string.player_brightness, (hud.value * 100).toInt())
        is Hud.Volume -> stringResource(R.string.player_volume, (hud.value * 100).toInt())
        is Hud.Boost -> stringResource(R.string.player_boost_hint)
    }
    val fraction = when (hud) {
        is Hud.Brightness -> hud.value
        is Hud.Volume -> hud.value
        is Hud.Boost -> -1f
    }
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Surface(color = chrome.card, shape = MaterialTheme.shapes.medium) {
            Column(
                Modifier.padding(horizontal = 22.dp, vertical = 14.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Icon(icon, null, tint = Color.White, modifier = Modifier.size(30.dp))
                if (fraction >= 0f) {
                    Spacer(Modifier.height(8.dp))
                    Box(
                        Modifier
                            .width(110.dp)
                            .height(4.dp)
                            .background(Color.White.copy(alpha = 0.25f)),
                    ) {
                        Box(
                            Modifier
                                .fillMaxWidth(fraction.coerceIn(0f, 1f))
                                .height(4.dp)
                                .background(Color.White),
                        )
                    }
                }
                Spacer(Modifier.height(6.dp))
                Text(label, color = Color.White, fontSize = brandSp(12))
            }
        }
    }
}

@Composable
private fun ScrubToast(
    target: Long,
    durationMs: Long,
    previewPlayer: ScrubPreviewPlayer?,
    showThumbnail: Boolean,
) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.BottomCenter) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier.padding(bottom = 130.dp),
        ) {
            // The thumbnail: the preview player's live TextureView, shown only
            // once the target has settled (showThumbnail). Until then the frame
            // on screen is from the last settled position — the wrong scene
            // for this time — so only the time shows. On Android 5 there is
            // no preview player and this stays time-only, exactly as before.
            if (showThumbnail && previewPlayer != null) {
                AndroidView(
                    factory = { ctx ->
                        TextureView(ctx).also { previewPlayer.setVideoTextureView(it) }
                    },
                    onRelease = { view -> previewPlayer.clearVideoTextureView(view) },
                    modifier = Modifier
                        .size(
                            ScrubThumbnails.THUMBNAIL_WIDTH_DP.dp,
                            ScrubThumbnails.THUMBNAIL_HEIGHT_DP.dp,
                        )
                        .padding(bottom = 8.dp),
                )
            }
            Surface(
                color = RaddHudToast,
                shape = MaterialTheme.shapes.small,
            ) {
                Text(
                    stringResource(R.string.player_time_of, target.formatTime(), durationMs.formatTime()),
                    color = Color.White,
                    fontSize = brandSp(14),
                    modifier = Modifier.padding(horizontal = 14.dp, vertical = 6.dp),
                )
            }
        }
    }
}

@Composable
private fun BoostBadge() {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.TopCenter) {
        Surface(
            color = RaddCurrent500,
            shape = MaterialTheme.shapes.small,
            modifier = Modifier.padding(top = 92.dp),
        ) {
            Row(Modifier.padding(horizontal = 10.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Default.FastForward, null, tint = Color.Black, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(4.dp))
                Text(stringResource(R.string.player_boost_badge), color = Color.Black, fontSize = brandSp(12), fontWeight = FontWeight.Bold)
            }
        }
    }
}

// ── 5. Chrome bars ─────────────────────────────────────────────────────────────

@Composable
private fun TopBar(vm: PlayerViewModel, state: PlayerUiState, onBack: () -> Unit) {
    val print = state.activeRendition
    val chrome = PlayerChromeTheme.forId(state.playerTheme)
    // Restyle 2026-11-13: the bar ends in a 1dp specular line where it meets
    // the picture — the same glass edge the bottom bar carries on its top —
    // so the chrome reads as a sheet over the frame, not a black slab.
    Column(Modifier.fillMaxWidth()) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(chrome.bar)
            .padding(start = 4.dp, end = 4.dp, top = 6.dp, bottom = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconButton(onClick = onBack) {
            Icon(Icons.Default.ArrowBack, stringResource(R.string.player_back), tint = Color.White)
        }
        Spacer(Modifier.width(6.dp))
        Column(Modifier.weight(1f)) {
            Text(
                state.pendingTitle ?: print?.displayLabel() ?: Brand.name,
                color = Color.White,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            if (print != null) {
                val hlsTag = stringResource(R.string.player_tag_hls)
                val expiringTag = stringResource(R.string.player_tag_expiring)
                val autoTag = state.autoQualityBand?.let { band -> stringResource(R.string.player_tag_auto, band) }
                // D-37: the subtitle is metadata — year · quality · source — never
                // the title again. The year comes from the staged title metadata;
                // the quality is the rung label; the "source" half is the playback
                // kind (HLS / expiring / Auto), never a host name or a raw link.
                // Session 121 (P-7): when the quality is unknown the display label
                // is a rank ("Rank #1"), not a rung — printing it would repeat the
                // title's job badly. The tags are still worth showing on their own,
                // and the line is dropped entirely when there is nothing to say.
                val subtitle = buildString {
                    state.titleYear?.let { append(it.toString()) }
                    print.displayLabel().takeIf { looksLikeQualityLabel(it) }?.let {
                        if (isNotEmpty()) append(" · ")
                        append(it)
                    }
                    if (print.playback.isHls()) {
                        if (isNotEmpty()) append(" · ")
                        append(hlsTag)
                    }
                    if (print.playback.ephemeral) {
                        if (isNotEmpty()) append(" · ")
                        append(expiringTag)
                    }
                    // Says out loud that the rung shown is Auto's current choice, so a
                    // quality that moves on its own is never mistaken for a hand-picked one.
                    autoTag?.let {
                        if (isNotEmpty()) append(" · ")
                        append(it)
                    }
                }
                if (subtitle.isNotBlank()) {
                    Text(
                        subtitle,
                        // E-C2: 11sp white at 72% over the 53%-black top bar was
                        // ~3.13:1 over a bright frame. Full white now.
                        color = Color.White,
                        style = MaterialTheme.typography.labelSmall,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }
        if (state.sleep.mode == SleepMode.COUNTDOWN) {
            Icon(
                Icons.Default.Bedtime,
                stringResource(R.string.player_sleep_remaining, state.sleep.remainingMs.formatTime()),
                tint = RaddCurrent500,
                modifier = Modifier
                    .size(16.dp)
                    .padding(end = 6.dp),
            )
        }
        if (state.speed != 1f && !state.boosting) {
            Text(
                stringResource(R.string.player_speed_short, state.speed),
                color = RaddCurrent500,
                style = MaterialTheme.typography.labelLarge,
                fontWeight = FontWeight.Bold,
                modifier = Modifier.padding(end = 6.dp),
            )
        }
        // Session 121 (P-35): the keep chip lived here and squeezed the title to a
        // stub ("Ali Baba …") on a narrow phone. It now rides its own row above
        // the scrubber in BottomControls, where it cannot crowd anything.
        IconButton(onClick = { vm.showPrintSheet() }) {
            Icon(Icons.Default.ListAlt, stringResource(R.string.player_prints_tools), tint = Color.White)
        }
    }
        Box(
            Modifier
                .fillMaxWidth()
                .height(1.dp)
                .background(Color.White.copy(alpha = 0.08f)),
        )
    }
}

@Composable
private fun CenterControls(state: PlayerUiState, vm: PlayerViewModel) {
    val chrome = PlayerChromeTheme.forId(state.playerTheme)
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        // App-design audit #4: three distinct states, never a bare play
        // triangle while nothing is playing and nothing is paused. While
        // the start is in flight or the player is rebuffering, the centre
        // is a spinner; while playing it is pause; while paused it is play.
        if (state.startPhase != StartPhase.NONE || state.isBuffering) {
            Surface(color = chrome.chip, shape = CircleShape) {
                // F4 (Batch B): the centre spinner was 44dp in a 72dp chip —
                // the round-2 re-review read it as very small against the
                // playback area, with no visible buffering progress. The ring
                // is 56dp in an 88dp chip now, and the buffering notice below
                // carries the buffered percent.
                Box(Modifier.size(88.dp), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator(
                        color = Color.White,
                        strokeWidth = 4.dp,
                        modifier = Modifier.size(56.dp),
                    )
                }
            }
        } else {
            Surface(color = chrome.chip, shape = CircleShape) {
                IconButton(onClick = { vm.togglePlayPause() }, modifier = Modifier.size(72.dp)) {
                    Icon(
                        painter = if (state.isPlaying) painterResource(R.drawable.ic_player_pause) else painterResource(R.drawable.ic_player_play),
                        // CL-5: the centre control says "Pause video"/"Play video",
                        // not bare "Pause"/"Play" — the bottom bar's button is
                        // visible at the same time, and two controls with the
                        // same name is the bug. Robo run 4 flagged the paused
                        // pair (two "Play"); the playing pair already differed.
                        contentDescription = if (state.isPlaying) stringResource(R.string.player_pause_centre) else stringResource(R.string.player_play_centre),
                        tint = Color.White,
                        modifier = Modifier.size(44.dp),
                    )
                }
            }
        }
    }
}

/**
 * The whole chrome of Ghost mode ([com.raddstream.app.player.ViewMode.PURE_CINEMA]) — and
 * the only thing left when the frame is deliberately furniture-free:
 *
 *  - no scrim across the picture and no scrim behind a pause: the frame keeps its own
 *    brightness whether you are playing or paused, which is the entire point of the mode;
 *  - no giant centre play button. Transport lives at the bottom-left edge;
 *  - three small chips hugging the edges (back + title, transport + time, exit + lock), each
 *    with its own rounded backing so it stays readable over a white frame without any of
 *    them dimming the image;
 *  - a 2dp played-progress line along the very top edge, so position is legible without a
 *    bar sitting on top of the picture.
 *
 * It fades on the same timer as the normal bars, a single tap brings it back, and a
 * two-finger tap rewinds [com.raddstream.app.player.GestureSettings.cinemaRewindMs] — the
 * affordance that makes a chrome-less frame still usable. The exit chip is why leaving is
 * never a hunt: one tap returns the full MX chrome.
 */
@Composable
private fun EdgeHud(
    state: PlayerUiState,
    vm: PlayerViewModel,
    onBack: () -> Unit,
) {
    val played = if (state.durationMs > 0) {
        (state.positionMs.toFloat() / state.durationMs).coerceIn(0f, 1f)
    } else {
        0f
    }
    val chrome = PlayerChromeTheme.forId(state.playerTheme)
    Box(Modifier.fillMaxSize()) {
        // Progress, painted on the edge of the frame rather than across the image.
        // F29 (Batch B): no line on a live stream — position over a DVR-window
        // duration is not progress, and the bar would imply a scrub that does
        // not exist.
        if (!state.isLive) {
            Box(
                Modifier
                    .fillMaxWidth()
                    .align(Alignment.TopStart)
                    .height(2.dp)
                    .background(chrome.track),
            ) {
                Box(
                    Modifier
                        .fillMaxWidth(played)
                        .height(2.dp)
                        .background(chrome.played),
                )
            }
        }

        // Top-left: leave, and what is playing.
        Row(
            modifier = Modifier
                .align(Alignment.TopStart)
                .padding(start = 6.dp, top = 6.dp)
                .background(chrome.chip, CircleShape)
                .padding(horizontal = 6.dp, vertical = 2.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            ControlTarget(label = stringResource(R.string.player_back), onClick = onBack) {
                Icon(Icons.Default.ArrowBack, null, tint = Color.White, modifier = Modifier.size(20.dp))
            }
            Text(
                text = state.pendingTitle ?: state.activeRendition?.displayLabel() ?: Brand.name,
                color = Color.White.copy(alpha = 0.85f),
                fontSize = brandSp(12),
                fontWeight = FontWeight.Medium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier
                    .widthIn(max = 220.dp)
                    .padding(end = 8.dp),
            )
        }

        // Bottom-left: transport. Tapping it at the end of a file replays from the top,
        // because this mode has no separate "play again" furniture to fall back on.
        Row(
            modifier = Modifier
                .align(Alignment.BottomStart)
                .padding(start = 6.dp, bottom = 10.dp)
                .background(chrome.chip, CircleShape)
                .padding(horizontal = 6.dp, vertical = 2.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            ControlTarget(
                // CL-5: the Ghost-mode edge control is the centre control by
                // another name — it says "Pause video"/"Play video", not bare
                // "Pause"/"Play". Robo run 4 flagged two "Play" controls; the
                // centre button now says "Play video", and this one is the
                // centre button in Ghost mode, so it says the same.
                label = if (state.isPlaying) stringResource(R.string.player_pause_centre) else stringResource(R.string.player_play_centre),
                onClick = { if (state.isEnded) vm.playFrom(0) else vm.togglePlayPause() },
            ) {
                Icon(
                    painter = if (state.isPlaying && !state.isBuffering) painterResource(R.drawable.ic_player_pause) else painterResource(R.drawable.ic_player_play),
                    contentDescription = null,
                    tint = Color.White,
                    modifier = Modifier.size(20.dp),
                )
            }
            Text(
                // Session 121 (P-11): same rule as the bottom bar — "Loading…" while
                // the start is in flight, position alone once playing with an
                // unknown total, never a "--:--" total that was never measured.
                text = if (state.startPhase != StartPhase.NONE) {
                    stringResource(R.string.app_loading)
                } else if (!state.isLive && state.durationMs > 0) {
                    stringResource(
                        R.string.player_time_of,
                        state.positionMs.formatTime(),
                        state.durationMs.formatTime(),
                    )
                } else {
                    state.positionMs.formatTime()
                },
                color = Color.White.copy(alpha = 0.8f),
                fontSize = brandSp(11),
                modifier = Modifier.padding(end = 8.dp),
            )
        }

        // Bottom-right: the way back to the full chrome, plus the lock.
        Row(
            modifier = Modifier
                .align(Alignment.BottomEnd)
                .padding(end = 6.dp, bottom = 10.dp)
                .background(chrome.chip, CircleShape)
                .padding(horizontal = 4.dp, vertical = 2.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            ControlTarget(label = stringResource(R.string.player_leave_cinema), onClick = { vm.toggleViewMode() }) {
                Icon(
                    Icons.Default.LocalMovies,
                    null,
                    tint = RaddCurrent500,
                    modifier = Modifier.size(20.dp),
                )
            }
            ControlTarget(label = stringResource(R.string.player_lock), onClick = { vm.setLocked(true) }) {
                Icon(Icons.Default.Lock, null, tint = Color.White, modifier = Modifier.size(18.dp))
            }
        }
    }
}

@Composable
private fun BottomControls(
    state: PlayerUiState,
    vm: PlayerViewModel,
    onEnterPip: () -> Unit,
    onActivity: () -> Unit,
    // SC §3: tapping an actor on the pause strip searches them, the same
    // route the detail screen's cast chips take.
    onActorClick: (String) -> Unit = {},
    // 25c: the single-rung Quality button explains itself through the
    // screen's snackbar, which lives in the content scope, not here.
    onMessage: (String) -> Unit = {},
) {
    var showVolumeDialog by remember { mutableStateOf(false) }
    val chrome = PlayerChromeTheme.forId(state.playerTheme)
    val context = LocalContext.current
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.BottomCenter) {
        Column(
            Modifier
                .fillMaxWidth()
                .background(chrome.bar),
        ) {
            // Restyle 2026-11-13: a 1dp specular line on the bar's top edge,
            // where it meets the picture — the same glass edge the top bar
            // carries on its bottom.
            Box(
                Modifier
                    .fillMaxWidth()
                    .height(1.dp)
                    .background(Color.White.copy(alpha = 0.08f)),
            )
            // SC §3: pause is discovery — the cast strip. Tapping an actor
            // searches them. Only while paused: a strip that appears mid-play
            // is a strip that steals the picture. The cast list itself is the
            // loaded signal — it is empty until the title stages it.
            if (!state.isPlaying && state.castNames.isNotEmpty()) {
                LazyRow(
                    Modifier
                        .fillMaxWidth()
                        .padding(start = 12.dp, end = 12.dp, top = 8.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(state.castNames, key = { it }) { actor ->
                        FilterChip(
                            selected = false,
                            onClick = { onActorClick(actor) },
                            label = { Text(actor, maxLines = 1) },
                            colors = raddFilterChipColors(),
                            // Audit #54: a FilterChip is 32 dp tall — the touch-target floor is 48 dp, so the chip itself carries it.
                            modifier = Modifier.heightIn(min = 48.dp),
                        )
                    }
                }
            }
            // Session 121 (P-35): the keep chip's own row, above the scrubber. It is
            // not a seventh transport button, so the six-primaries rule still holds —
            // and here it cannot crowd the title the way it did in the top bar.
            // The guard matters: an empty row would still take its top padding.
            if (state.keep !is KeepUiState.Unavailable) {
                Row(
                    Modifier
                        .fillMaxWidth()
                        .padding(start = 12.dp, end = 12.dp, top = 8.dp),
                ) {
                    KeepChip(state, vm)
                }
            }
            // F19b (Batch A): the seek bar and its time row only exist once the
            // player knows a duration. A live stream never reports one
            // (ExoPlayer's duration stays TIME_UNSET, so durationMs stays 0),
            // which used to leave a dead scrubber reading "0:00 / --:--" under a
            // live picture. A VOD's duration is known at prepare, so the bar
            // appears as soon as playback can start; while the start card is up
            // the card itself narrates the phase, so nothing is lost.
            // F29 (Batch B): the duration gate was not enough — a live HLS
            // playlist can report a finite DVR-window duration (Discover
            // Pakistan: 2:00:12), and the scrubber came back with it. The
            // gate is the explicit live flag now: a live stream gets no
            // scrubber and no time row at all, only a LIVE mark in their
            // place, whatever duration the playlist claims.
            if (!state.isLive && state.durationMs > 0) {
                Scrubber(
                    chrome = chrome,
                    positionMs = state.positionMs,
                    bufferedMs = state.bufferedMs,
                    durationMs = state.durationMs,
                    enabled = state.seekEnabled,
                    onSeek = { vm.seekTo(it) },
                    onActivity = onActivity,
                    episodes = state.activeRendition?.coverage?.episodes.orEmpty(),
                )
                Row(
                    Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    // App-design audit #3/#4: current time and total duration are
                    // always beside the scrubber — "--:--" until the total is
                    // known — plus one status word, so the viewer can tell
                    // loading, paused and buffering apart at a glance.
                    val statusWord = when (
                        playerStatusWord(state.startPhase, state.isBuffering, state.isPlaying)
                    ) {
                        PlayerStatusWord.LOADING -> stringResource(R.string.app_loading)
                        PlayerStatusWord.BUFFERING -> stringResource(R.string.player_buffering)
                        PlayerStatusWord.PAUSED -> stringResource(R.string.player_paused)
                        PlayerStatusWord.NONE -> null
                    }
                    Text(
                        text = state.positionMs.formatTime(),
                        color = Color.White,
                        style = MaterialTheme.typography.labelMedium,
                    )
                    if (statusWord != null) {
                        Spacer(Modifier.width(8.dp))
                        Text(statusWord, color = Color.White.copy(alpha = 0.85f), style = MaterialTheme.typography.labelMedium)
                    }
                    Spacer(Modifier.weight(1f))
                    Text(
                        state.durationMs.takeIf { it > 0 }?.formatTime() ?: "--:--",
                        color = Color.White,
                        style = MaterialTheme.typography.labelMedium,
                    )
                }
            } else if (state.isLive) {
                LiveMark()
            }
            Row(
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 4.dp, vertical = 2.dp),
                verticalAlignment = Alignment.CenterVertically,
                // D-43: the labels need room to breathe — the six primaries
                // spread across the bar instead of packing left.
                horizontalArrangement = Arrangement.SpaceEvenly,
            ) {
                val subtitleWord = subtitleStatusLabel(state, stringResource(R.string.player_off))
                val volumePercent = (state.userVolume * 100).toInt()
                // Exactly six primaries, frozen left to right (plan §4.2): Play/Pause,
                // Volume, Subtitles, Quality, Fullscreen, More. Everything else lives
                // in the More sheet — nothing was deleted, only moved. The row no
                // longer scrolls: six 48 dp buttons fit every phone, and a hidden
                // seventh button would be a button that lies.
                PlayerControlButton(
                    { if (state.isEnded) vm.playFrom(0) else vm.togglePlayPause() },
                    if (state.isPlaying) stringResource(R.string.player_pause) else stringResource(R.string.player_play),
                    shortLabel = if (state.isPlaying) stringResource(R.string.player_pause) else stringResource(R.string.player_play),
                ) {
                    Icon(
                        painter = if (state.isPlaying) painterResource(R.drawable.ic_player_pause) else painterResource(R.drawable.ic_player_play),
                        contentDescription = null,
                        tint = Color.White,
                    )
                }
                PlayerControlButton(
                    { vm.toggleMute() },
                    if (state.userVolume > 0f) stringResource(R.string.player_volume, volumePercent)
                    else stringResource(R.string.player_volume_muted),
                    onLongClick = { showVolumeDialog = true },
                    shortLabel = stringResource(R.string.player_volume_title),
                ) {
                    if (state.userVolume > 0f) {
                        Icon(
                            painter = painterResource(R.drawable.ic_player_volume),
                            contentDescription = null,
                            tint = Color.White,
                        )
                    } else {
                        // No brand icon for muted: the speaker with waves would lie
                        // about the state, so the Material mute mark stays.
                        Icon(
                            Icons.Default.VolumeMute,
                            null,
                            tint = Color.White,
                        )
                    }
                }
                PlayerControlButton(
                    { vm.showSubtitleSheet() },
                    stringResource(R.string.player_subtitles_label, subtitleWord),
                    selected = subtitleActive(state),
                    shortLabel = stringResource(R.string.player_subtitles_title),
                ) {
                    Icon(painterResource(R.drawable.ic_player_subtitles), null, tint = if (subtitleActive(state)) RaddCurrent500 else Color.White)
                }
                // 25c: the Quality primary never vanishes — on a single-rung title
                // it stays visible, dimmed, and tapping it says why instead of
                // opening a sheet with one row. Six primaries, always.
                if (state.canSwitchQuality) {
                    PlayerControlButton(
                        { vm.showQualitySheet() },
                        stringResource(R.string.player_quality_label, state.qualityLabel),
                        selected = !state.qualityAuto,
                        shortLabel = stringResource(R.string.player_quality_title),
                    ) {
                        Icon(
                            painterResource(R.drawable.ic_player_quality),
                            null,
                            tint = if (state.qualityAuto) Color.White else RaddCurrent500,
                        )
                    }
                } else {
                    // Single rung: the button stays, dimmed, and tapping it says
                    // why instead of opening a sheet with one row. It is not
                    // disabled in the clickable sense — a dead tap explains nothing.
                    PlayerControlButton(
                        { onMessage(context.getString(R.string.player_quality_single)) },
                        stringResource(R.string.player_quality_label, state.qualityLabel),
                        shortLabel = stringResource(R.string.player_quality_title),
                    ) {
                        Icon(
                            painterResource(R.drawable.ic_player_quality),
                            null,
                            tint = Color.White.copy(alpha = 0.4f),
                        )
                    }
                }
                PlayerControlButton(
                    { vm.toggleFullscreen() },
                    if (state.fullscreen) stringResource(R.string.player_exit_fullscreen)
                    else stringResource(R.string.player_fullscreen),
                    shortLabel = stringResource(R.string.player_fullscreen),
                ) {
                    if (state.fullscreen) {
                        // No brand icon for exit: the expand-corners mark would lie
                        // about the state, so the Material exit mark stays.
                        Icon(Icons.Default.FullscreenExit, null, tint = Color.White)
                    } else {
                        Icon(painterResource(R.drawable.ic_player_fullscreen), null, tint = Color.White)
                    }
                }
                PlayerControlButton(
                    { vm.showMoreSheet() },
                    stringResource(R.string.player_more),
                    shortLabel = stringResource(R.string.player_more),
                ) {
                    Icon(Icons.Default.MoreVert, null, tint = Color.White)
                }
            }
        }
        // Volume long-press: a level slider with the % in words, so the exact level
        // is reachable without the gesture. Dragging writes straight to the same
        // setUserVolume the gesture uses, so mute remembers the restore point.
        if (showVolumeDialog) {
            AlertDialog(
                onDismissRequest = { showVolumeDialog = false },
                title = { RaddDialogTitle(stringResource(R.string.player_volume_title)) },
                text = {
                    Column {
                        // Robo run 4: this level line says "Volume 100%" — and so
                        // does the HUD toast — so the two read identically. The
                        // dialog is the level control, so it announces itself as
                        // one ("Volume level, 100 percent") while the paint stays
                        // the short "Volume 100%".
                        val volumeLevelSpoken = stringResource(
                            R.string.player_volume_level,
                            (state.userVolume * 100).toInt(),
                        )
                        Text(
                            stringResource(R.string.player_volume, (state.userVolume * 100).toInt()),
                            modifier = Modifier.semantics { contentDescription = volumeLevelSpoken },
                        )
                        Slider(
                            value = state.userVolume,
                            onValueChange = { vm.setUserVolume(it) },
                            valueRange = 0f..1f,
                            modifier = Modifier.fillMaxWidth(),
                        )
                        // Volume boost, honest UI only (Session 126): the slider lets
                        // the viewer request up to 200%, but this build has no software
                        // gain stage, so the setter clamps at the 100% player ceiling
                        // and the summary below says what was requested and what was
                        // actually applied. The requested level lives in this dialog
                        // only — the stored level is the clamped one, and a request
                        // that was never applied is not a setting to persist.
                        var requestedBoost by remember { mutableStateOf(state.audioBoostLevel) }
                        Spacer(Modifier.height(12.dp))
                        Text(stringResource(R.string.player_volume_boost))
                        Slider(
                            value = requestedBoost,
                            onValueChange = {
                                requestedBoost = it
                                vm.setAudioBoostLevel(it)
                            },
                            valueRange = 0f..AudioBoost.MAX,
                            modifier = Modifier.fillMaxWidth(),
                        )
                        Text(
                            AudioBoostUi.honestSummary(requestedBoost, state.userVolume),
                            color = Color.White.copy(alpha = 0.6f),
                            fontSize = brandSp(12),
                        )
                    }
                },
                confirmButton = {
                    TextButton({ showVolumeDialog = false }) {
                        Text(stringResource(R.string.player_close))
                    }
                },
            )
        }
    }
}

private fun subtitleActive(state: PlayerUiState) =
    state.selectedSubtitleId != null || state.customSubtitleLoaded != null ||
        state.nativeExternals.isNotEmpty()

/**
 * The word the subtitles control speaks: which text is loaded, or an honest "off". Internal
 * so `PlayerControlSemanticsTest` can assert a named control is never rendered nameless.
 */
internal fun subtitleStatusLabel(state: PlayerUiState, offWord: String): String =
    state.customSubtitleLoaded
        ?: state.selectedSubtitleId?.let { id -> state.subtitleTracks.firstOrNull { it.id == id }?.label }
        ?: offWord

/** Android's minimum touch target. Every press in this file is at least this wide and tall. */
private val MinControlTarget = 48.dp

/**
 * The one press a player control uses: a [MinControlTarget] circle, [label] as the words a
 * screen reader says, and [Role.Button] so TalkBack offers the press itself as an action.
 *
 * Both halves were missing before. The control lane forced a 42 dp slot and the cinema chips
 * 38 dp — both under the minimum a fingertip is entitled to — and each drew an Icon whose own
 * description is deliberately null, so the sixteen named lane controls announced nothing at
 * all. A preference a viewer cannot hear is a preference only sighted users can set.
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun ControlTarget(
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    onLongClick: (() -> Unit)? = null,
    // D-43: a selected control shows a filled state — a jade disc behind the
    // icon — so the viewer can see at a glance which control is active. A
    // disabled control dims and does not fire.
    selected: Boolean = false,
    enabled: Boolean = true,
    content: @Composable () -> Unit,
) {
    val spoken = label
    // Long-press is opt-in per control (the Volume button's level slider). A control
    // without one keeps the plain clickable below — the press the semantics test pins.
    val base = modifier
        .size(MinControlTarget)
        .clip(CircleShape)
        .background(
            if (selected) RaddCurrent500.copy(alpha = 0.25f) else Color.Transparent,
            CircleShape,
        )
        .alpha(if (enabled) 1f else 0.4f)
    val pressModifier = if (onLongClick != null) {
        base
            .combinedClickable(onClick = onClick, onLongClick = onLongClick, role = Role.Button, enabled = enabled)
            .semantics { contentDescription = spoken }
    } else {
        base
            .clickable(onClick = onClick, role = Role.Button, enabled = enabled)
            .semantics { contentDescription = spoken }
    }
    Box(
        pressModifier,
        contentAlignment = Alignment.Center,
    ) { content() }
}

@Composable
private fun PlayerControlButton(
    onClick: () -> Unit,
    label: String,
    onLongClick: (() -> Unit)? = null,
    // D-43: the filled selected state, and the visible label under the icon —
    // the control bar finally says what each glyph does, where space allows.
    // The label duplicates the button's spoken label, so it is cleared from the
    // semantics tree rather than announced twice.
    selected: Boolean = false,
    enabled: Boolean = true,
    shortLabel: String? = null,
    content: @Composable () -> Unit,
) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        ControlTarget(label = label, onClick = onClick, onLongClick = onLongClick, selected = selected, enabled = enabled) {
            Box(Modifier.size(26.dp), contentAlignment = Alignment.Center) { content() }
        }
        if (shortLabel != null) {
            Text(
                shortLabel,
                // E-C3: 10sp white at 75% over the bar was ~3.3:1 over a bright
                // frame. 0.85f is the floor the audit allows for these labels.
                // Session 154: 11sp now — 10sp is off the M3 type scale.
                color = if (selected) RaddCurrent500 else Color.White.copy(alpha = 0.85f),
                fontSize = brandSp(11),
                maxLines = 1,
                modifier = Modifier.clearAndSetSemantics { },
            )
        }
    }
}

/** Thin MX scrubber: grey track, brighter buffered segment, theme played segment + thumb. */
@Composable
private fun Scrubber(
    chrome: PlayerChromeTheme,
    positionMs: Long,
    bufferedMs: Long,
    durationMs: Long,
    enabled: Boolean,
    onSeek: (Long) -> Unit,
    onActivity: () -> Unit,
    episodes: List<EpisodeCoverage> = emptyList(),
) {
    // Chapter ticks (plan §5 step 11): the pack's episode boundaries, from the same
    // pure function the print sheet's chapter list uses, so the two can never disagree.
    val ticks = remember(episodes, durationMs) { chapterTicks(episodes, durationMs) }
    // PL-8: the scrubber is a progress bar to a screen reader — its description
    // names the position and the chapter the position is inside, and setProgress
    // lets a switch or voice user seek without ever touching the track.
    val currentChapter = ticks.lastOrNull { it.offsetMs <= positionMs }?.title
    val seekDescription = stringResource(
        R.string.player_seek,
        positionMs.formatTime(),
        durationMs.formatTime(),
    ) + (currentChapter?.let { stringResource(R.string.player_seek_chapter, it) } ?: "")
    BoxWithConstraints(
        Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 10.dp)
            .height(20.dp)
            .semantics(mergeDescendants = true) {
                contentDescription = seekDescription
                if (enabled && durationMs > 0) {
                    progressBarRangeInfo = ProgressBarRangeInfo(
                        current = positionMs.toFloat() / durationMs.coerceAtLeast(1L),
                        range = 0f..1f,
                    )
                    setProgress { value ->
                        onSeek((value.coerceIn(0f, 1f) * durationMs).toLong())
                        true
                    }
                }
            },
    ) {
        val trackWidthPx = constraints.maxWidth.toFloat().coerceAtLeast(1f)
        val duration = durationMs.coerceAtLeast(1L)
        val posFraction = (positionMs.toFloat() / duration).coerceIn(0f, 1f)
        val bufFraction = (bufferedMs.toFloat() / duration).coerceIn(0f, 1f)

        Box(
            Modifier
                .align(Alignment.CenterStart)
                .fillMaxWidth()
                .height(4.dp)
                .background(Color.White.copy(alpha = 0.28f)),
        )
        Box(
            Modifier
                .align(Alignment.CenterStart)
                .fillMaxWidth(bufFraction)
                .height(4.dp)
                .background(Color.White.copy(alpha = 0.5f)),
        )
        Box(
            Modifier
                .align(Alignment.CenterStart)
                .fillMaxWidth(posFraction)
                .height(4.dp)
                .background(chrome.played),
        )
        // One short white mark per chapter, straddling the track. Tapping one seeks —
        // the track's own tap-to-seek already does that, so a tick needs no gesture
        // of its own. The thumb passes over them; that is the point of a mark.
        ticks.forEach { tick ->
            Box(
                Modifier
                    .align(Alignment.CenterStart)
                    .offset(x = (maxWidth * tick.fraction) - 1.dp)
                    .width(2.dp)
                    .height(9.dp)
                    .background(Color.White.copy(alpha = 0.85f)),
            )
        }
        Box(
            Modifier
                .align(Alignment.CenterStart)
                .offset(x = maxWidth * posFraction.coerceIn(0f, 0.98f))
                .size(16.dp)
                .background(chrome.played, shape = CircleShape),
        )
        if (enabled && durationMs > 0) {
            Box(
                Modifier
                    .fillMaxSize()
                    .pointerInput(durationMs) {
                        awaitEachGesture {
                            val down = awaitFirstDown(requireUnconsumed = false)
                            fun targetFor(x: Float): Long =
                                ((x / trackWidthPx).coerceIn(0f, 1f) * durationMs).toLong().coerceAtLeast(0)
                            onActivity()
                            onSeek(targetFor(down.position.x))
                            while (true) {
                                val event = awaitPointerEvent(PointerEventPass.Main)
                                val change = event.changes.firstOrNull { it.id == down.id } ?: break
                                if (!change.pressed) {
                                    onSeek(targetFor(change.position.x))
                                    break
                                }
                                onActivity()
                                onSeek(targetFor(change.position.x))
                                change.consumed.positionChange = true
                            }
                        }
                    },
            )
        }
    }
}

@Composable
private fun UnlockFab(chrome: PlayerChromeTheme, onUnlock: () -> Unit) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.CenterEnd) {
        Surface(
            color = chrome.bar,
            shape = MaterialTheme.shapes.small,
            modifier = Modifier.padding(16.dp),
        ) {
            IconButton(onClick = onUnlock) {
                Icon(Icons.Default.LockOpen, stringResource(R.string.player_unlock), tint = Color.White)
            }
        }
    }
}

@Composable
private fun EndedButtons(
    chrome: PlayerChromeTheme,
    showNextEpisode: Boolean,
    onPlayAgain: () -> Unit,
    onNextEpisode: () -> Unit,
    // PL-12: the "Up next" preview — the next episode's title, number and still,
    // so the end card shows what is coming instead of only a bare button.
    nextEpisodeTitle: String? = null,
    nextEpisodeSeason: Int? = null,
    nextEpisodeEpisode: Int? = null,
    nextEpisodePosterUrl: String? = null,
) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Surface(
                color = chrome.card,
                shape = MaterialTheme.shapes.medium,
                modifier = Modifier.clickableNoRipple(onPlayAgain),
            ) {
                Row(
                    Modifier.padding(horizontal = 20.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(Icons.Default.Replay10, null, tint = Color.White)
                    Spacer(Modifier.width(8.dp))
                    Text(stringResource(R.string.player_play_again), color = Color.White, fontSize = brandSp(14))
                }
            }
            // Only when autoplay-next is off and a numbered successor exists: the
            // episode ends on this button instead of advancing on its own (plan §5
            // step 10). Same card, same tap — a choice, not an ambush.
            if (showNextEpisode) {
                if (nextEpisodeTitle != null || nextEpisodePosterUrl != null) {
                    val number = listOfNotNull(
                        nextEpisodeSeason?.let { "S$it" },
                        nextEpisodeEpisode?.let { "E$it" },
                    ).joinToString(" ")
                    Surface(
                        color = chrome.card,
                        shape = MaterialTheme.shapes.medium,
                        modifier = Modifier.clickableNoRipple(onNextEpisode),
                    ) {
                        Row(
                            Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            if (nextEpisodePosterUrl != null) {
                                CatalogImage(
                                    url = nextEpisodePosterUrl,
                                    contentDescription = null,
                                    modifier = Modifier.size(56.dp, 32.dp),
                                )
                                Spacer(Modifier.width(10.dp))
                            }
                            Column {
                                Text(
                                    stringResource(R.string.player_up_next),
                                    color = Color.White.copy(alpha = 0.6f),
                                    fontSize = brandSp(12),
                                )
                                Text(
                                    text = listOfNotNull(
                                        number.ifBlank { null },
                                        nextEpisodeTitle,
                                    ).joinToString(" · "),
                                    color = Color.White,
                                    fontSize = brandSp(14),
                                    maxLines = 2,
                                    overflow = TextOverflow.Ellipsis,
                                )
                            }
                        }
                    }
                }
                Surface(
                    color = chrome.card,
                    shape = MaterialTheme.shapes.medium,
                    modifier = Modifier.clickableNoRipple(onNextEpisode),
                ) {
                    Row(
                        Modifier.padding(horizontal = 20.dp, vertical = 12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(Icons.Default.SkipNext, null, tint = Color.White)
                        Spacer(Modifier.width(8.dp))
                        Text(stringResource(R.string.player_next_episode), color = Color.White, fontSize = brandSp(14))
                    }
                }
            }
        }
    }
}

/**
 * The autoplay-next countdown (Session 123, PL-1): what the viewer sees for
 * the ten seconds between an episode's end and the advance. One line stating
 * the wait, one Cancel that stops it — the same card language as the ended
 * buttons, so it reads as part of the player, not a popup.
 *
 * Session 126 (PL-12): the countdown names the episode it is counting toward,
 * and Play now skips the wait — the countdown is a convenience, not a hold.
 */
@Composable
private fun AutoplayCountdownCard(
    chrome: PlayerChromeTheme,
    secondsLeft: Int,
    onCancel: () -> Unit,
    nextEpisodeTitle: String? = null,
    onPlayNow: (() -> Unit)? = null,
) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Surface(
                color = chrome.card,
                shape = MaterialTheme.shapes.medium,
            ) {
                Row(
                    Modifier.padding(horizontal = 20.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(Icons.Default.SkipNext, null, tint = Color.White)
                    Spacer(Modifier.width(8.dp))
                    Text(
                        stringResource(R.string.player_autoplay_countdown, secondsLeft),
                        color = Color.White,
                        fontSize = brandSp(14),
                    )
                }
            }
            if (nextEpisodeTitle != null) {
                Text(
                    text = stringResource(
                        R.string.player_up_next_title,
                        stringResource(R.string.player_up_next),
                        nextEpisodeTitle,
                    ),
                    color = Color.White.copy(alpha = 0.85f),
                    fontSize = brandSp(14),
                    textAlign = TextAlign.Center,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(horizontal = 32.dp),
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                onPlayNow?.let {
                    TextButton(onClick = it) {
                        Text(stringResource(R.string.player_autoplay_play_now), color = RaddCurrent500, fontSize = brandSp(14))
                    }
                }
                TextButton(onClick = onCancel) {
                    Text(stringResource(R.string.player_cancel), color = Color.White, fontSize = brandSp(14))
                }
            }
        }
    }
}

@Composable
private fun ConnectionErrorCard(message: String, onRetry: () -> Unit) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(
            Modifier.padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Icon(Icons.Default.Warning, null, tint = RaddCoral400, modifier = Modifier.size(40.dp))
            Spacer(Modifier.height(10.dp))
            // D-47: the two failure states share one language — the give-up
            // card's body is left-aligned, so this message is too. The icon
            // stays centred, as on the give-up card.
            Text(
                message,
                color = Color.White,
                fontSize = brandSp(14),
                textAlign = TextAlign.Start,
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(12.dp))
            OutlinedButton(onClick = onRetry) { Text(stringResource(R.string.player_retry), color = Color.White) }
        }
    }
}

// PL-3: an offline start or an offline failure shows this immediately, with
// Retry — not just the 30-second deadline card. Waiting half a minute to be
// told there is no network is not a wait, it is a lie.
@Composable
private fun OfflineCard(onRetry: () -> Unit) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(
            Modifier.padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Icon(Icons.Default.WifiOff, null, tint = RaddCoral400, modifier = Modifier.size(40.dp))
            Spacer(Modifier.height(10.dp))
            Text(
                stringResource(R.string.player_offline_title),
                color = Color.White,
                style = MaterialTheme.typography.titleMedium,
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(6.dp))
            Text(
                stringResource(R.string.player_offline_body),
                color = Color.White.copy(alpha = 0.85f),
                fontSize = brandSp(14),
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(12.dp))
            OutlinedButton(onClick = onRetry) { Text(stringResource(R.string.player_retry), color = Color.White) }
        }
    }
}

// PL-4: a locked player keeps a small time chip visible — position and
// remaining, without unlocking. Frosted glass on a capable device, solid on a
// low-RAM one (BM rule 9).
@Composable
private fun LockedTimeChip(positionMs: Long, durationMs: Long, lowRam: Boolean, modifier: Modifier = Modifier) {
    val spec = PlayerGlass.spec(lowRam)
    // GlassSpec carries alphas, not ready-made modifiers: the tint is a dark
    // chip at tintAlpha (opaque when solid), the edge is 1dp white at
    // borderAlpha (invisible when solid). Same frosted/solid split as the
    // other glass bars, built from the fields the spec actually has.
    Box(
        modifier
            .background(Color.Black.copy(alpha = spec.tintAlpha), RoundedCornerShape(8.dp))
            .border(1.dp, Color.White.copy(alpha = spec.borderAlpha), RoundedCornerShape(8.dp))
            .padding(horizontal = 10.dp, vertical = 6.dp),
    ) {
        Text(
            text = stringResource(
                R.string.player_time_of,
                positionMs.formatTime(),
                durationMs.formatTime(),
            ),
            color = Color.White,
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}

/**
 * First-run gesture coach (plan §5 step 7): the three hints the player teaches nowhere
 * else, on a dimmed scrim so they read over any frame. Any tap dismisses — the tap is
 * the lesson ending, not a control press — and the 4 s timer in [PlayerScreenContent]
 * dismisses it the same way. No icons: the words are the whole hint, and a fourth
 * visual language would be decoration on a teaching moment.
 */
@Composable
private fun PlayerCoachOverlay(onDismiss: () -> Unit) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black.copy(alpha = 0.55f))
            .clickableNoRipple(onDismiss),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier.padding(horizontal = 32.dp),
        ) {
            Text(
                stringResource(R.string.player_coach_title),
                color = Color.White,
                style = MaterialTheme.typography.titleMedium,
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(12.dp))
            Text(
                stringResource(R.string.player_coach_double_tap),
                color = Color.White.copy(alpha = 0.85f),
                style = MaterialTheme.typography.bodyMedium,
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(6.dp))
            Text(
                stringResource(R.string.player_coach_swipe),
                color = Color.White.copy(alpha = 0.85f),
                style = MaterialTheme.typography.bodyMedium,
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(6.dp))
            Text(
                stringResource(R.string.player_coach_long_press),
                color = Color.White.copy(alpha = 0.85f),
                style = MaterialTheme.typography.bodyMedium,
                textAlign = TextAlign.Center,
            )
        }
    }
}

/**
 * The player's loading indicator (Session 123, D-36): a real indeterminate
 * progress ring, not the brand mark. The three-wave mark is the logo — a
 * viewer cannot tell whether it is a spinner or a picture — so the wait
 * shows the ring the platform owns, in the action colour, with the reason
 * underneath when the caller has one. The mark stays for brand moments (the
 * splash, the start card's corner) and never stands in for progress.
 */

/**
 * F29 (Batch B): the live mark — a red dot and the word Live, in place of the
 * scrubber + time row a live stream does not have. It says what the stream
 * is; it promises no position, because a live window has none to show.
 */
@Composable
private fun LiveMark(modifier: Modifier = Modifier) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Box(
            modifier = Modifier
                .size(8.dp)
                .background(MaterialTheme.colorScheme.error, CircleShape),
        )
        Text(
            text = stringResource(R.string.player_live),
            color = Color.White,
            style = MaterialTheme.typography.labelMedium,
            fontWeight = FontWeight.SemiBold,
        )
    }
}

@Composable
private fun PlayerLoadingIndicator(
    label: String? = null,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        CircularProgressIndicator(
            modifier = Modifier.size(RaddTokens.Touch.MinTarget),
            color = MaterialTheme.colorScheme.primary,
            strokeWidth = 3.dp,
        )
        if (!label.isNullOrBlank()) {
            Spacer(Modifier.height(RaddTokens.Space.Sm))
            Text(
                label,
                color = Color.White,
                style = MaterialTheme.typography.bodyMedium,
                textAlign = TextAlign.Center,
            )
        }
    }
}

@Composable
private fun StartNoticeCard(
    phase: StartPhase,
    title: String?,
    slowHint: Boolean = false,
    rungLabel: String? = null,
    attemptLabel: String? = null,
    // P-3: milliseconds since the load was requested (Play press) — the
    // elapsed line counts from here, so the resolve wait is counted too.
    waitElapsedMs: Long = 0,
    // 26: the three-step progress story — the viewer always knows what the wait
    // is for: finding the best version, then finding the video, then buffering. When the
    // caller passes a step label it replaces the phase's generic label.
    stepLabel: String? = null,
    onRetry: (() -> Unit)? = null,
    onTryAnother: (() -> Unit)? = null,
    // App-design audit #2: the wait is never a trap — Cancel returns to
    // the detail screen at any point, even before the 8-second actions.
    onCancel: (() -> Unit)? = null,
) {
    val label = stepLabel ?: phase.label
    val spoken = if (title.isNullOrBlank()) label else stringResource(R.string.player_notice_spaced, label, title)
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        // The logo-mark (§4.7): 32 dp, top-left, only while nothing is playing.
        Icon(
            painter = painterResource(R.drawable.ic_logo_mark),
            contentDescription = null,
            tint = Color.Unspecified,
            modifier = Modifier
                .align(Alignment.TopStart)
                .padding(16.dp)
                .size(32.dp),
        )
        // LC-1: the notice floats over the live video frame, so it gets its own
        // solid plate — bare white over a bright frame was ~1:1. Robo run 7
        // flagged the notice's title at 1.06:1: the old plate was RaddHudCard,
        // black at 60% — over a bright frame it composites to mid-grey, and
        // the 65%-white title on that mid-grey is ~3.5:1, under the 4.5:1
        // floor (the old ">= 7:1 over any frame" only holds for full white).
        // The plate is now the solid stage colour and the title is full
        // white, so the reading no longer depends on the frame behind it.
        // The plate never animates with the chrome fade: it is either up, or
        // it is gone.
        Surface(
            color = RaddPlayerStage,
            shape = MaterialTheme.shapes.medium,
            modifier = Modifier.padding(horizontal = 32.dp),
        ) {
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                modifier = Modifier
                    .padding(horizontal = 16.dp, vertical = 12.dp)
                    .semantics(mergeDescendants = true) { contentDescription = spoken },
            ) {
            PlayerLoadingIndicator()
            Spacer(Modifier.height(14.dp))
            Text(
                label,
                color = Color.White,
                style = MaterialTheme.typography.bodyMedium,
                textAlign = TextAlign.Center,
            )
            if (!title.isNullOrBlank()) {
                Spacer(Modifier.height(4.dp))
                Text(
                    title,
                    // Robo run 7: the 65%-white title on the old translucent
                    // plate read 1.06:1. Full white on the solid plate.
                    color = Color.White,
                    style = MaterialTheme.typography.bodySmall,
                    textAlign = TextAlign.Center,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            // Session 121 (P-36): which copy is being tried, out of how many — the
            // wait reads as progress through the failover ladder, not a freeze.
            if (!attemptLabel.isNullOrBlank()) {
                Spacer(Modifier.height(4.dp))
                Text(
                    attemptLabel,
                    // Robo run 7: 60% white on the old plate was under the
                    // floor over a bright frame. 85% is the floor the audit
                    // allows for these sub-lines.
                    color = Color.White.copy(alpha = 0.85f),
                    style = MaterialTheme.typography.bodySmall,
                    textAlign = TextAlign.Center,
                )
            }
            // The soft hint (§5 P5, past two seconds): the wait is normal, and here is
            // which rung is being found — so a long start reads as work, not a freeze.
            if (slowHint) {
                Spacer(Modifier.height(8.dp))
                Text(
                    stringResource(R.string.player_start_slow),
                    color = Color.White.copy(alpha = 0.85f),
                    style = MaterialTheme.typography.bodySmall,
                    textAlign = TextAlign.Center,
                )
                if (!rungLabel.isNullOrBlank()) {
                    Spacer(Modifier.height(2.dp))
                    Text(
                        stringResource(R.string.player_quality_label, rungLabel),
                        // Robo run 7: same as the attempt line above — 60%
                        // white was under the floor over a bright frame.
                        color = Color.White.copy(alpha = 0.85f),
                        style = MaterialTheme.typography.bodySmall,
                        textAlign = TextAlign.Center,
                    )
                }
            }
            // P-3: the 20 s wait is narrated but showed no elapsed time. The
            // line counts from the request (Play press), so the resolve wait
            // is counted too — and it stands on its own threshold (past ten
            // seconds), not inside the slow-hint block, because the stage
            // clock starts at the URL and the resolve runs before it.
            val elapsedLine = StartDeadline.formatWaitElapsed(rungLabel, waitElapsedMs)
            if (elapsedLine != null) {
                Spacer(Modifier.height(4.dp))
                Text(
                    elapsedLine,
                    // Robo run 7: same as the attempt line above — 60%
                    // white was under the floor over a bright frame.
                    color = Color.White.copy(alpha = 0.85f),
                    style = MaterialTheme.typography.bodySmall,
                    textAlign = TextAlign.Center,
                )
            }
            // The actions (§5 P5, past eight seconds): retry the same attempt, or jump to
            // the next version now instead of waiting for the silent failover to get there.
            // D-40: real buttons, not plain green text links — a press target the
            // viewer can see is a press target the viewer will find.
            if (onRetry != null || onTryAnother != null || onCancel != null) {
                Spacer(Modifier.height(12.dp))
                Row(
                    horizontalArrangement = Arrangement.spacedBy(10.dp, Alignment.CenterHorizontally),
                ) {
                    onRetry?.let {
                        OutlinedButton(onClick = it) {
                            Text(stringResource(R.string.player_retry), color = Color.White)
                        }
                    }
                    onTryAnother?.let {
                        OutlinedButton(onClick = it) {
                            Text(stringResource(R.string.player_start_try_another), color = Color.White)
                        }
                    }
                    onCancel?.let {
                        TextButton(onClick = it) {
                            Text(stringResource(R.string.player_cancel), color = Color.White)
                        }
                    }
                }
            }
            }
        }
    }
}

/**
 * How tall the give-up card's action stack may grow before it scrolls.
 * Four and a half 48dp actions: on a ~360dp landscape screen the icon,
 * title and text above the stack leave about this much room, so the
 * fifth action ("Keep waiting") stays one scroll away instead of off
 * the bottom edge. See the confirmButton note in [GiveUpCard].
 */
private val GiveUpActionsMaxHeight = 216.dp

@Composable
private fun GiveUpCard(
    message: String,
    why: HandoffWhy,
    onRetry: () -> Unit,
    onExternal: () -> Unit,
    onDismiss: () -> Unit,
    onBackToDetails: () -> Unit,
    onTryAnother: (() -> Unit)? = null,
    // NAV-4: an expired shared link gets its own way home. Only the expired
    // card shows it — the other failures already have their own way out.
    onHomeClick: (() -> Unit)? = null,
) {
    // PL-13 (Session 114): dismissing this card must leave the player — a failed
    // play must never trap the viewer. The dialog itself never dismisses on Back
    // or on an outside tap, so the screen-level back handler owns Back (exit) and
    // the card's own Close button is the only way to keep waiting.
    AlertDialog(
        onDismissRequest = onBackToDetails,
        properties = DialogProperties(
            dismissOnBackPress = false,
            dismissOnClickOutside = false,
        ),
        // D-48: the dialog reads as a surface, not a slab on black — a 1dp
        // outline in the dialog's own shape, over the tonal container.
        modifier = Modifier.border(
            1.dp,
            MaterialTheme.colorScheme.outlineVariant,
            MaterialTheme.shapes.extraLarge,
        ),
        containerColor = RaddPlayerDialog,
        icon = {
            // Session 121 (P-34): the logo-mark is the brand loader's job, not an
            // error's — a failure gets a warning triangle in the same coral the
            // connection-error card already uses, so the two failure states agree.
            Icon(
                Icons.Default.Warning,
                contentDescription = null,
                tint = RaddCoral400,
                modifier = Modifier.size(32.dp),
            )
        },
        title = {
            // D-2: one dialog title style everywhere — display family,
            // semibold, 20sp — not the thin 16sp face this card used.
            RaddDialogTitle(
                text = when (why) {
                    HandoffWhy.DOWNLOAD_ONLY -> stringResource(R.string.player_giveup_download_only)
                    HandoffWhy.NO_CANDIDATE_LEFT -> stringResource(R.string.player_giveup_no_candidate)
                    HandoffWhy.START_TIMEOUT -> stringResource(R.string.player_giveup_timeout)
                    // NAV-4: an expired shared link is not a generic error — it
                    // says so, plainly, in the title.
                    HandoffWhy.EXPIRED_LINK -> stringResource(R.string.player_giveup_expired)
                    // Salaar: a rung the server refused is VIP-only — say so,
                    // plainly, in the title.
                    HandoffWhy.GATE_REFUSED -> stringResource(R.string.player_giveup_gate_refused)
                    // Batch C (2026-11-14, 429-storm audit): the per-IP play
                    // bucket is full — the server asked the app to wait.
                    HandoffWhy.RATE_LIMITED -> stringResource(R.string.player_giveup_rate_limited)
                },
                color = Color.White,
            )
        },
        text = {
            Column {
                Text(message, color = Color.White.copy(alpha = 0.85f), fontSize = brandSp(14))
                Spacer(Modifier.height(8.dp))
                Text(
                    when (why) {
                        HandoffWhy.DOWNLOAD_ONLY ->
                            stringResource(R.string.player_giveup_download_body)
                        HandoffWhy.NO_CANDIDATE_LEFT ->
                            stringResource(R.string.player_giveup_no_candidate_body)
                        HandoffWhy.START_TIMEOUT ->
                            stringResource(R.string.player_giveup_timeout_body)
                        HandoffWhy.EXPIRED_LINK ->
                            stringResource(R.string.player_giveup_expired_body)
                        HandoffWhy.GATE_REFUSED ->
                            stringResource(R.string.player_giveup_gate_refused_body)
                        HandoffWhy.RATE_LIMITED ->
                            stringResource(R.string.player_giveup_rate_limited_body)
                    },
                    color = Color.White.copy(alpha = 0.6f),
                    fontSize = brandSp(12),
                )
            }
        },
        // Session 120: five actions in one horizontal row overflowed a 360 dp
        // phone — AlertDialog lays its two button slots side by side, so
        // "Open with another player" wrapped onto four lines ("Open / with /
        // anothe / r") and "Close" printed over its final letter. All five
        // actions stack vertically instead, each full width, so every one is
        // fully visible and tappable no matter which subset is offered.
        // The dismiss slot stays empty: "Back to details" and "Close" are
        // actions in the same stack, not a second row fighting for width.
        // Samsung RTL retest (Issue 7): the player forces landscape, so
        // this dialog is short — up to six full-width 48dp actions plus
        // icon, title and two text blocks can exceed a ~360dp landscape
        // screen, and the lower actions ("Back to details", "Keep
        // waiting") fall off the bottom edge, where a tap hits the scrim
        // and — dismissOnClickOutside is false — does nothing at all.
        // The stack scrolls inside a cap, so every action stays reachable
        // on a short screen; on a tall one the cap never binds and the
        // list shows whole, exactly as before.
        confirmButton = {
            Column(
                Modifier
                    .fillMaxWidth()
                    .heightIn(max = GiveUpActionsMaxHeight)
                    .verticalScroll(rememberScrollState()),
            ) {
                // Session 121 (P-33): five green buttons shout at once, so the two
                // recoveries that end the failure (retry the same print, or leave
                // for the title) stay green and the two alternates read as
                // secondary white; the dismiss stays the quietest white.
                TextButton(onClick = onRetry, modifier = Modifier.fillMaxWidth()) {
                    Text(stringResource(R.string.player_retry), color = RaddCurrent500)
                }
                onTryAnother?.let {
                    TextButton(onClick = it, modifier = Modifier.fillMaxWidth()) {
                        Text(
                            stringResource(R.string.player_start_try_another),
                            color = Color.White.copy(alpha = 0.85f),
                        )
                    }
                }
                TextButton(onClick = onExternal, modifier = Modifier.fillMaxWidth()) {
                    Text(
                        stringResource(R.string.player_open_external),
                        color = Color.White.copy(alpha = 0.85f),
                    )
                }
                TextButton(onClick = onBackToDetails, modifier = Modifier.fillMaxWidth()) {
                    Text(stringResource(R.string.player_back_to_details), color = RaddCurrent500)
                }
                // NAV-4: the expired card's way home — a shared link that died
                // should not strand the viewer on a dead card.
                if (why == HandoffWhy.EXPIRED_LINK) {
                    onHomeClick?.let { goHome ->
                        TextButton(onClick = goHome, modifier = Modifier.fillMaxWidth()) {
                            Text(stringResource(R.string.player_home), color = RaddCurrent500)
                        }
                    }
                }
                // Session 121 (P-19): "Close" said nothing about what happens next
                // — this button dismisses the card and keeps waiting on the slow
                // link, so it says so.
                TextButton(onClick = onDismiss, modifier = Modifier.fillMaxWidth()) {
                    Text(stringResource(R.string.player_keep_waiting), color = Color.White.copy(alpha = 0.7f))
                }
            }
        },
        dismissButton = {},
    )
}

// ── Subtitle overlay (custom path: external SRT/VTT, delay honoured) ──────────

@Composable
private fun SubtitleOverlay(state: PlayerUiState, vm: PlayerViewModel) {
    if (state.customSubtitleLoaded == null) return
    val cues = vm.overlayCues(state.positionMs)
    if (cues.isEmpty()) return
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.BottomCenter) {
        Column(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 24.dp)
                .padding(bottom = (72 + state.subtitle.bottomFraction * 300).dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            cues.forEach { cue ->
                Text(
                    cue.text,
                    color = state.subtitle.colour.paint(),
                    fontSize = brandSp(16f * state.subtitle.sizePercent / 100f),
                    fontWeight = if (state.subtitle.bold) FontWeight.Bold else FontWeight.Normal,
                    textAlign = TextAlign.Center,
                    modifier = if (state.subtitle.textBackground) {
                        Modifier
                            .background(RaddCaptionPlate, MaterialTheme.shapes.small)
                            .padding(horizontal = 8.dp, vertical = 2.dp)
                    } else {
                        Modifier
                    },
                )
            }
        }
    }
}

// ── Subtitle colour swatch ────────────────────────────────────────────────────

/**
 * One caption colour as a tappable dot: the dot is the colour, the halo says it is chosen, and
 * the press is named for what it does — a swatch that only a sighted viewer can tell the
 * difference between is a preference half of the audience cannot set.
 */
@Composable
private fun SubtitleColourSwatch(colour: SubtitleColor, selected: Boolean, onSelect: () -> Unit) {
    val paint = colour.paint()
    val selectedSuffix = if (selected) stringResource(R.string.player_selected_suffix) else ""
    val spoken = stringResource(R.string.player_subtitles_for_colour, colour.label) + selectedSuffix
    ControlTarget(label = spoken, onClick = onSelect) {
        Box(
            modifier = Modifier
                .size(34.dp)
                .background(if (selected) paint.copy(alpha = 0.26f) else Color.Transparent, CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            Box(Modifier.size(18.dp).background(paint, CircleShape))
        }
    }
}

// ── Keep chip — the signature "watching → keeping" affordance ─────────────────

@Composable
private fun KeepChip(state: PlayerUiState, vm: PlayerViewModel) {
    val keep = state.keep
    if (keep is KeepUiState.Unavailable) return
    // App-design audit #7: pressing Play must never announce a background
    // download. The "Keeping" state is the player's automatic ahead-window
    // copy, not something the viewer asked for — it shows no chip here at
    // all (its progress lives in Downloads). A finished keep (Stored) or a
    // blocked one still says so, because those are facts about the title.
    if (keep is KeepUiState.Keeping) return
    val chrome = PlayerChromeTheme.forId(state.playerTheme)
    // E-C4: the chip sat on a 40%-alpha tint with no bar behind it — white
    // text on the Stored tint over a bright frame was 1.23:1. The surface is
    // now chrome.card (60% black); the state tint survives only as the
    // icon/ring colour, at full strength.
    val stateTint = when (keep) {
        is KeepUiState.Stored -> RaddSuccess
        is KeepUiState.Blocked -> RaddDanger
        is KeepUiState.Keeping -> RaddTideIndigo
        else -> Color.White
    }
    Surface(
        color = chrome.card,
        shape = MaterialTheme.shapes.small,
        modifier = Modifier
            .padding(end = 6.dp)
            .clickableNoRipple(onClick = { vm.keepCurrent() }),
    ) {
        Row(
            Modifier
                .heightIn(min = MinControlTarget)
                .padding(horizontal = 8.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            // SC.7: the living progress ring while keeping — real %, from the
            // pure keepingProgress, shown only when the total is known. A ring
            // at 0% with an unknown total would be the same lie Session 120
            // fixed in the chip text ("Keeping 0 B of 3.05 GB"), in a circle.
            val progress = CacheAffordance.keepingProgress(keep)
            if (progress != null) {
                CircularProgressIndicator(
                    progress = progress,
                    modifier = Modifier.size(14.dp),
                    color = stateTint,
                    strokeWidth = 2.dp,
                )
            } else {
                Icon(Icons.Default.Download, null, tint = stateTint, modifier = Modifier.size(14.dp))
            }
            Spacer(Modifier.width(4.dp))
            Text(
                CacheAffordance.chipText(keep),
                color = Color.White,
                fontSize = brandSp(11),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.widthIn(max = 160.dp),
            )
        }
    }
}

// ── Dialogs ────────────────────────────────────────────────────────────────────

@Composable
private fun ResumeDialog(state: PlayerUiState, vm: PlayerViewModel) {
    val ms = state.resumeOfferMs ?: return
    AlertDialog(
        onDismissRequest = { vm.resolveResume(false) },
        containerColor = RaddPlayerDialog,
        title = { RaddDialogTitle(stringResource(R.string.player_resume_title), color = Color.White) },
        text = {
            Text(
                stringResource(
                    R.string.player_resume_body,
                    ms.formatTime(),
                    state.pendingTitle ?: stringResource(R.string.player_this_print),
                ),
                color = Color.White.copy(alpha = 0.8f),
                fontSize = brandSp(14),
            )
        },
        confirmButton = {
            TextButton(onClick = { vm.resolveResume(true) }) { Text(stringResource(R.string.player_resume), color = RaddCurrent500) }
        },
        dismissButton = {
            TextButton(onClick = { vm.resolveResume(false) }) { Text(stringResource(R.string.player_start_over), color = Color.White.copy(alpha = 0.7f)) }
        },
    )
}

/**
 * PL-2: the sponsor break dialog is gone, with the placeholder ad it rendered.
 * Episode advance no longer gates on a fake ad — the countdown advances directly
 * — and the policy seam (AdSlotPolicy, AdSlot) stays in the player package
 * for the day a real ad is wired, with its pure tests as the proof.
 */
@Composable
private fun CalibrationDialog(
    state: CalibrationState,
    onConfirm: (Int) -> Unit,
    onDismiss: () -> Unit,
) {
    var text by remember { mutableStateOf(state.targetEpisode.coerceAtLeast(1).toString()) }
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = RaddPlayerDialog,
        title = { RaddDialogTitle(stringResource(R.string.player_calibration_title), color = Color.White) },
        text = {
            Column {
                Text(
                    state.warning ?: stringResource(R.string.player_calibration_body),
                    color = Color.White.copy(alpha = 0.8f),
                    fontSize = brandSp(14),
                )
                Spacer(Modifier.height(10.dp))
                OutlinedTextField(
                    value = text,
                    onValueChange = { text = it.filter { c -> c.isDigit() }.take(3) },
                    label = { Text(stringResource(R.string.player_episode_number), color = Color.White.copy(alpha = 0.6f)) },
                    singleLine = true,
                )
            }
        },
        confirmButton = {
            TextButton(
                onClick = { text.toIntOrNull()?.let { onConfirm(it) } ?: onDismiss() },
            ) { Text(stringResource(R.string.player_mark_position), color = RaddCurrent500) }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text(stringResource(R.string.player_cancel), color = Color.White.copy(alpha = 0.7f)) }
        },
    )
}

@Composable
private fun PlayFromDialog(
    onSubmit: (Long) -> Unit,
    onDismiss: () -> Unit,
) {
    var text by remember { mutableStateOf("0:00") }
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = RaddPlayerDialog,
        title = { RaddDialogTitle(stringResource(R.string.player_play_from_title), color = Color.White) },
        text = {
            OutlinedTextField(
                value = text,
                onValueChange = { text = it },
                label = { Text(stringResource(R.string.player_play_from_hint), color = Color.White.copy(alpha = 0.6f)) },
                singleLine = true,
            )
        },
        confirmButton = {
            TextButton(onClick = { onSubmit(parseTimeToMs(text)) }) { Text(stringResource(R.string.player_go), color = RaddCurrent500) }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text(stringResource(R.string.player_cancel), color = Color.White.copy(alpha = 0.7f)) }
        },
    )
}

/** "12:34" → 754 000 ms; "1:02:03" → ms; single number = minutes; garbage → 0. */
private fun parseTimeToMs(raw: String): Long {
    val parts = raw.trim().split(':').map { it.trim() }
    if (parts.isEmpty() || parts.any { it.isEmpty() || !it.all { c -> c.isDigit() } }) return 0L
    val nums = parts.map { it.toLong() }
    return when (nums.size) {
        1 -> nums[0] * 60_000L
        2 -> (nums[0] * 60 + nums[1]) * 1000L
        3 -> (nums[0] * 3600 + nums[1] * 60 + nums[2]) * 1000L
        else -> 0L
    }
}

// ── Sheets ─────────────────────────────────────────────────────────────────────

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SpeedSheet(state: PlayerUiState, vm: PlayerViewModel) {
    ModalBottomSheet(
        onDismissRequest = { vm.hideSpeedSheet() },
        sheetState = rememberModalBottomSheetState(),
        containerColor = RaddPlayerSheet,
    ) {
        Column(Modifier.padding(bottom = 20.dp)) {
            SheetTitle(stringResource(R.string.player_speed_title))
            Row(
                Modifier
                    .horizontalScroll(rememberScrollState())
                    .padding(horizontal = 12.dp),
            ) {
                GestureMapper.SPEED_PRESETS.forEach { preset ->
                    val selected = state.speed == preset
                    Surface(
                        color = if (selected) RaddCurrent500 else RaddHudPillIdle,
                        shape = MaterialTheme.shapes.small,
                        modifier = Modifier
                            .padding(end = 6.dp)
                            .clickableNoRipple { vm.setSpeed(preset) },
                    ) {
                        Box(
                            Modifier
                                .heightIn(min = MinControlTarget)
                                .padding(horizontal = 12.dp),
                            contentAlignment = Alignment.Center,
                        ) {
                            Text(
                                stringResource(R.string.player_speed_short, preset),
                                color = if (selected) Color.Black else Color.White,
                                fontSize = brandSp(14),
                            )
                        }
                    }
                }
            }
            Spacer(Modifier.height(12.dp))
            Text(
                stringResource(R.string.player_boost_note),
                color = Color.White.copy(alpha = 0.55f),
                fontSize = brandSp(12),
                modifier = Modifier.padding(horizontal = 16.dp),
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun QualitySheet(state: PlayerUiState, vm: PlayerViewModel) {
    ModalBottomSheet(
        onDismissRequest = { vm.hideQualitySheet() },
        sheetState = rememberModalBottomSheetState(),
        containerColor = RaddPlayerSheet,
    ) {
        Column(Modifier.padding(bottom = 20.dp)) {
            SheetTitle(stringResource(R.string.player_quality_title))
            QualityRow(
                title = stringResource(R.string.player_quality_auto),
                detail = if (state.qualityAuto) stringResource(R.string.player_quality_auto_detail) else null,
                selected = state.qualityAuto,
                onClick = { vm.selectQualityBand("auto") },
            )
            // 26: Data Saver sits next to Auto — the viewer who is on mobile data
            // caps Auto at 480p from the same sheet that picks the quality.
            Row(
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text(
                        stringResource(R.string.player_data_saver),
                        color = Color.White,
                        fontSize = brandSp(14),
                    )
                    Text(
                        stringResource(R.string.player_data_saver_detail),
                        color = Color.White.copy(alpha = 0.5f),
                        fontSize = brandSp(12),
                    )
                }
                Switch(checked = state.dataSaver, onCheckedChange = { vm.toggleDataSaver() })
            }
            state.qualityRungs.forEach { rung ->
                val selected = !state.qualityAuto && rung.band == state.qualityBand
                QualityRow(
                    title = rung.label?.takeIf { it.isNotBlank() } ?: rung.band.uppercase(),
                    // The cost shows before the tap (plan §5 step 9) — the "Playing"
                    // word only joins it when this rung is the one playing now.
                    detail = listOfNotNull(
                        qualityCostPerHour(rung.band),
                        if (selected) stringResource(R.string.player_playing) else null,
                    ).joinToString(" · ").takeIf { it.isNotEmpty() },
                    selected = selected,
                    onClick = { vm.selectQualityBand(rung.band) },
                )
            }
            Text(
                stringResource(R.string.player_quality_note),
                color = Color.White.copy(alpha = 0.55f),
                fontSize = brandSp(12),
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
            )
        }
    }
}

@Composable
private fun QualityRow(title: String, detail: String?, selected: Boolean, onClick: () -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .clickableNoRipple(onClick)
            .heightIn(min = MinControlTarget)
            // D-43: a selected rung is filled, not just green text.
            .background(
                if (selected) RaddCurrent500.copy(alpha = 0.15f) else Color.Transparent,
                MaterialTheme.shapes.small,
            )
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            title,
            color = if (selected) RaddCurrent500 else Color.White,
            fontSize = brandSp(14),
            fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
        )
        if (detail != null) {
            Spacer(Modifier.width(8.dp))
            Text(detail, color = Color.White.copy(alpha = 0.5f), fontSize = brandSp(12))
        }
        Spacer(Modifier.weight(1f))
        if (selected) Icon(Icons.Default.Check, null, tint = RaddCurrent500, modifier = Modifier.size(18.dp))
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SleepSheet(state: PlayerUiState, vm: PlayerViewModel) {
    ModalBottomSheet(
        onDismissRequest = { vm.hideSleepSheet() },
        sheetState = rememberModalBottomSheetState(),
        containerColor = RaddPlayerSheet,
    ) {
        Column(Modifier.padding(bottom = 20.dp)) {
            SheetTitle(stringResource(R.string.player_sleep_timer))
            if (state.sleep.mode == SleepMode.COUNTDOWN) {
                Text(
                    stringResource(R.string.player_sleep_fading, state.sleep.remainingMs.formatTime()),
                    color = RaddCurrent500,
                    fontSize = brandSp(14),
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp),
                )
            }
            SleepTimerState.PRESETS_MS.forEach { preset ->
                SheetRow(label = stringResource(R.string.player_sleep_minutes, preset / 60_000)) { vm.startSleepCountdown(preset) }
            }
            SheetRow(label = stringResource(R.string.player_sleep_at_end)) { vm.sleepAtVideoEnd() }
            SheetRow(label = stringResource(R.string.player_off_label)) { vm.cancelSleep() }
            Text(
                stringResource(R.string.player_sleep_note, state.sleep.fadeMs / 1000),
                color = Color.White.copy(alpha = 0.55f),
                fontSize = brandSp(12),
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp),
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SubtitleSettingsSheet(state: PlayerUiState, vm: PlayerViewModel) {
    val ctx = LocalContext.current
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri: Uri? ->
        if (uri != null) {
            val name = queryDisplayName(ctx, uri) ?: ctx.getString(R.string.player_external_subtitle)
            val hint = name.substringAfterLast('.', "srt").lowercase()
            vm.addExternalSubtitle(url = uri.toString(), label = name, formatHint = hint)
        }
    }
    ModalBottomSheet(
        onDismissRequest = { vm.hideSubtitleSheet() },
        sheetState = rememberModalBottomSheetState(),
        containerColor = RaddPlayerSheet,
    ) {
        Column(
            Modifier
                .verticalScroll(rememberScrollState())
                .padding(bottom = 24.dp),
        ) {
            SheetTitle(stringResource(R.string.player_subtitles_title))
            // App-design audit #6: a subtitle sheet with no tracks is one
            // clear action, not an empty panel with a size slider for a
            // track that does not exist. The size/position/style controls
            // below only appear once a track is loaded.
            val hasTrack = state.subtitleTracks.isNotEmpty() ||
                state.customSubtitleLoaded != null || state.nativeExternals.isNotEmpty()
            if (!hasTrack) {
                Text(
                    stringResource(R.string.player_subtitle_none),
                    color = Color.White.copy(alpha = 0.6f),
                    fontSize = brandSp(12),
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
                )
                Spacer(Modifier.height(12.dp))
                Button(
                    onClick = { picker.launch(arrayOf("*/*")) },
                    modifier = Modifier.padding(horizontal = 16.dp).fillMaxWidth().heightIn(min = 48.dp),
                ) {
                    Text(stringResource(R.string.player_subtitle_browse))
                }
                Spacer(Modifier.height(8.dp))
                return@Column
            }
            state.subtitleTracks.forEach { track ->
                SheetRow(label = track.label, selected = track.id == state.selectedSubtitleId) {
                    vm.selectSubtitleTrack(track)
                }
            }
            if (state.selectedSubtitleId != null) {
                SheetRow(label = stringResource(R.string.player_subtitle_turn_off)) { vm.selectSubtitleTrack(null) }
            }

            Spacer(Modifier.height(8.dp))
            Text(
                stringResource(R.string.player_subtitle_size, state.subtitle.sizePercent),
                color = Color.White,
                fontSize = brandSp(14),
                modifier = Modifier.padding(horizontal = 16.dp),
            )
            Slider(
                value = state.subtitle.sizePercent.toFloat(),
                onValueChange = { vm.setSubtitleSettings(state.subtitle.copy(sizePercent = it.toInt())) },
                valueRange = 50f..200f,
                modifier = Modifier.padding(horizontal = 16.dp),
            )

            Text(
                stringResource(R.string.player_subtitle_position, (state.subtitle.bottomFraction * 100).toInt()),
                color = Color.White,
                fontSize = brandSp(14),
                modifier = Modifier.padding(horizontal = 16.dp),
            )
            Slider(
                value = state.subtitle.bottomFraction,
                onValueChange = { vm.setSubtitleSettings(state.subtitle.copy(bottomFraction = it)) },
                valueRange = 0f..0.3f,
                modifier = Modifier.padding(horizontal = 16.dp),
            )

            // One control owns the offset: this row hands over to the sheet with the live
            // slider and the ±0.1s/±0.5s buttons, so the two can never disagree.
            SheetRow(label = stringResource(R.string.player_subtitle_sync, SubtitleOffset.format(state.subtitle.delayMs))) {
                vm.showSubtitleOffsetSheet()
            }

            Row(Modifier.padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(stringResource(R.string.player_subtitle_bold), color = Color.White, fontSize = brandSp(14), modifier = Modifier.weight(1f))
                Switch(
                    checked = state.subtitle.bold,
                    onCheckedChange = { vm.setSubtitleSettings(state.subtitle.copy(bold = it)) },
                )
            }
            Row(Modifier.padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(stringResource(R.string.player_subtitle_background), color = Color.White, fontSize = brandSp(14), modifier = Modifier.weight(1f))
                Switch(
                    checked = state.subtitle.textBackground,
                    onCheckedChange = { vm.setSubtitleSettings(state.subtitle.copy(textBackground = it)) },
                )
            }

            Text(
                stringResource(R.string.player_subtitle_colour),
                color = Color.White,
                fontSize = brandSp(14),
                modifier = Modifier.padding(horizontal = 16.dp),
            )
            Row(
                Modifier.padding(horizontal = 16.dp),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                SubtitleColor.entries.forEach { colour ->
                    SubtitleColourSwatch(
                        colour = colour,
                        selected = colour == state.subtitle.colour,
                        onSelect = { vm.setSubtitleSettings(state.subtitle.copy(colour = colour)) },
                    )
                }
            }

            Spacer(Modifier.height(8.dp))
            SheetRow(label = stringResource(R.string.player_subtitle_load)) {
                picker.launch(arrayOf("*/*"))
            }
            if (state.customSubtitleLoaded != null) {
                SheetRow(label = stringResource(R.string.player_subtitle_remove, state.customSubtitleLoaded ?: "")) { vm.removeCustomSubtitle() }
                Text(
                    stringResource(R.string.player_subtitle_sync_note),
                    color = Color.White.copy(alpha = 0.55f),
                    fontSize = brandSp(11),
                    modifier = Modifier.padding(horizontal = 16.dp),
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun TracksSheet(state: PlayerUiState, vm: PlayerViewModel) {
    ModalBottomSheet(
        onDismissRequest = { vm.hideTracksSheet() },
        sheetState = rememberModalBottomSheetState(),
        containerColor = RaddPlayerSheet,
    ) {
        Column(
            Modifier
                .verticalScroll(rememberScrollState())
                .padding(bottom = 24.dp),
        ) {
            SheetTitle(stringResource(R.string.player_audio_tracks))
            if (state.audioTracks.isEmpty()) {
                Text(
                    stringResource(R.string.player_track_none),
                    color = Color.White.copy(alpha = 0.6f),
                    fontSize = brandSp(12),
                    modifier = Modifier.padding(horizontal = 16.dp),
                )
            }
            state.audioTracks.forEach { track ->
                SheetRow(
                    label = track.language
                        ?.let { stringResource(R.string.player_track_with_language, track.label, it) }
                        ?: track.label,
                    selected = track.id == state.selectedAudioId || track.selected,
                ) { vm.selectAudioTrack(track) }
            }
            if (state.audioTracks.isNotEmpty()) {
                SheetRow(label = stringResource(R.string.player_cycle_audio), enabled = state.canCycleAudio) {
                    vm.cycleAudioTrack()
                }
                if (state.preferredAudioLanguage != null) {
                    Text(
                        stringResource(
                            R.string.player_preferred_audio,
                            AudioTrackPolicy.nameFor(state.preferredAudioLanguage)
                                ?: state.preferredAudioLanguage,
                        ),
                        color = Color.White.copy(alpha = 0.55f),
                        fontSize = brandSp(11),
                        modifier = Modifier.padding(horizontal = 16.dp),
                    )
                }
            }
            Spacer(Modifier.height(10.dp))
            SheetRow(
                label = if (state.stereoOnly) stringResource(R.string.player_stereo_on) else stringResource(R.string.player_stereo_off),
            ) { vm.toggleStereoOnly() }
            Text(
                stringResource(R.string.player_stereo_note),
                color = Color.White.copy(alpha = 0.55f),
                fontSize = brandSp(11),
                modifier = Modifier.padding(horizontal = 16.dp),
            )
            SheetRow(
                label = if (state.audioOnly) stringResource(R.string.player_audio_only_on) else stringResource(R.string.player_audio_only_off),
            ) { vm.toggleAudioOnly() }

            // ── Audio level. Media3's setVolume contract stops at 100% and this build adds no
            //    software gain, so the slider stops there too: a thumb the viewer can drag into a
            //    range nothing can act on is a promise broken on every drag, caption or no caption.
            //    A build that grows a DynamicsProcessing stage widens this from AudioBoostUi alone.
            Spacer(Modifier.height(14.dp))
            SheetTitle(stringResource(R.string.player_audio_level))
            Row(
                Modifier.padding(horizontal = 16.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Text(
                    AudioBoost.labelFor(state.audioBoostLevel),
                    color = RaddCurrent500,
                    fontSize = brandSp(14),
                    fontWeight = FontWeight.SemiBold,
                )
                Slider(
                    value = state.audioBoostLevel.coerceIn(0f, AudioBoostUi.MAX_OFFERED_LEVEL),
                    onValueChange = { vm.setAudioBoostLevel(it) },
                    valueRange = 0f..AudioBoostUi.MAX_OFFERED_LEVEL,
                    modifier = Modifier.weight(1f),
                )
            }
            Text(
                AudioBoostUi.honestSummary(state.audioBoostLevel, state.userVolume),
                color = Color.White.copy(alpha = 0.55f),
                fontSize = brandSp(11),
                modifier = Modifier.padding(horizontal = 16.dp),
            )
        }
    }
}

/**
 * The More sheet (plan §4.3): every control that is not one of the six primaries,
 * grouped exactly like MX's overflow — Playback / Subtitle / Audio / Tools. Nothing
 * was deleted in step 3, only moved here from the bottom row; every row below calls
 * the same ViewModel function its button used to call. A row that opens another
 * sheet or dialog hides More first (the PrintLogSheet pattern), so two sheets never
 * stack; a row that acts directly closes More too, so the viewer sees the picture,
 * not the menu, after the tap. Lock is not here — it lives in the top bar already.
 * The audio-level slider lives inside the TracksSheet the Audio tracks row opens.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun MoreSheet(state: PlayerUiState, vm: PlayerViewModel, onEnterPip: () -> Unit) {
    ModalBottomSheet(
        onDismissRequest = { vm.hideMoreSheet() },
        sheetState = rememberModalBottomSheetState(),
        containerColor = RaddPlayerSheet,
    ) {
        Column(
            Modifier
                .verticalScroll(rememberScrollState())
                .padding(bottom = 24.dp),
        ) {
            SheetTitle(stringResource(R.string.player_more_playback))
            SheetRow(label = stringResource(R.string.player_speed_label, state.speed)) {
                vm.hideMoreSheet()
                vm.showSpeedSheet()
            }
            SheetRow(label = stringResource(R.string.player_sleep_timer)) {
                vm.hideMoreSheet()
                vm.showSleepSheet()
            }
            SheetRow(label = stringResource(R.string.player_frame_back)) {
                vm.hideMoreSheet()
                vm.stepFrame(-1)
            }
            SheetRow(label = stringResource(R.string.player_frame_forward)) {
                vm.hideMoreSheet()
                vm.stepFrame(1)
            }
            // A-B repeat (§5 P14): set the two points of the loop. The sheet stays
            // open for both taps — setting A then B is one visit, not two — and the
            // row labels show the points once they are set, so the segment is visible.
            SheetRow(
                label = state.abRepeat.aMs?.let {
                    stringResource(R.string.player_ab_point, "A", it.formatTime())
                } ?: stringResource(R.string.player_ab_set_a),
            ) {
                vm.setAbPointA()
            }
            SheetRow(
                label = state.abRepeat.bMs?.let {
                    stringResource(R.string.player_ab_point, "B", it.formatTime())
                } ?: stringResource(R.string.player_ab_set_b),
            ) {
                vm.setAbPointB()
            }
            if (state.abRepeat.hasA || state.abRepeat.hasB) {
                SheetRow(label = stringResource(R.string.player_ab_clear)) {
                    vm.clearAbRepeat()
                }
            }
            SheetRow(label = stringResource(R.string.player_rewind_10)) {
                vm.hideMoreSheet()
                vm.seekBy(-10_000)
            }
            SheetRow(label = stringResource(R.string.player_forward_10)) {
                vm.hideMoreSheet()
                vm.seekBy(10_000)
            }
            SheetRow(label = stringResource(R.string.player_aspect_label, state.aspect.label)) {
                vm.hideMoreSheet()
                vm.cycleAspect()
            }
            SheetRow(label = stringResource(R.string.player_orientation_label, state.orientation.label)) {
                vm.hideMoreSheet()
                vm.toggleOrientation()
            }
            if (state.pureCinemaAllowed) {
                SheetRow(label = stringResource(R.string.player_cinema_mode)) {
                    vm.hideMoreSheet()
                    vm.toggleViewMode()
                }
            }
            SheetTitle(stringResource(R.string.player_subtitles_title))
            SheetRow(
                label = stringResource(
                    R.string.player_subtitles_label,
                    subtitleStatusLabel(state, stringResource(R.string.player_off)),
                ),
            ) {
                vm.hideMoreSheet()
                vm.showSubtitleSheet()
            }
            SheetRow(
                label = stringResource(
                    R.string.player_subtitle_sync,
                    SubtitleOffset.format(state.subtitle.delayMs),
                ),
            ) {
                vm.hideMoreSheet()
                vm.showSubtitleOffsetSheet()
            }
            SheetTitle(stringResource(R.string.player_audio_title))
            SheetRow(label = stringResource(R.string.player_audio_tracks)) {
                vm.hideMoreSheet()
                vm.showTracksSheet()
            }
            SheetRow(label = stringResource(R.string.player_cycle_audio), enabled = state.canCycleAudio) {
                vm.hideMoreSheet()
                vm.cycleAudioTrack()
            }
            SheetRow(label = stringResource(R.string.player_audio_only_toggle)) {
                vm.hideMoreSheet()
                vm.toggleAudioOnly()
            }
            SheetRow(label = stringResource(R.string.player_stereo_only_toggle)) {
                vm.hideMoreSheet()
                vm.toggleStereoOnly()
            }
            SheetTitle(stringResource(R.string.player_more_tools))
            // PL-11: "Next episode" and "Calibrate" are series rows — a movie or
            // a local file has no next episode to play and nothing to calibrate.
            if (state.isSeriesScope) {
                SheetRow(label = stringResource(R.string.player_next_episode)) {
                    vm.hideMoreSheet()
                    vm.requestNextEpisode()
                }
            }
            SheetRow(label = stringResource(R.string.player_play_from_row)) {
                vm.hideMoreSheet()
                vm.showPlayFromDialog()
            }
            if (state.isSeriesScope) {
                SheetRow(label = stringResource(R.string.player_calibrate_row)) {
                    vm.hideMoreSheet()
                    vm.openCalibration()
                }
            }
            SheetRow(label = stringResource(R.string.player_prints_title)) {
                vm.hideMoreSheet()
                vm.showPrintSheet()
            }
            // SC.24: share a moment — title, timestamp, deep link — from the
            // More sheet. The VM hides the row's effect for local bundles (no
            // handle to link to); the row itself stays, and the tap is a no-op.
            SheetRow(label = stringResource(R.string.player_share_moment)) {
                vm.hideMoreSheet()
                vm.shareMoment()
            }
            SheetRow(label = stringResource(R.string.player_retry_row)) {
                vm.hideMoreSheet()
                vm.retryCurrentCandidates()
            }
            SheetRow(label = stringResource(R.string.player_open_external_row)) {
                vm.hideMoreSheet()
                vm.openWithExternalPlayer()
            }
            SheetRow(label = stringResource(R.string.player_pip)) {
                vm.hideMoreSheet()
                onEnterPip()
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
private fun PrintLogSheet(state: PlayerUiState, vm: PlayerViewModel) {
    // PL-6: the ranks, the failover log and the failover policy are debug, not
    // viewer-facing — they sit behind a long-press on the "Prints" title. The
    // sheet itself shows only quality, format and which print is playing.
    var debugVisible by remember { mutableStateOf(false) }
    ModalBottomSheet(
        onDismissRequest = { vm.hidePrintSheet() },
        sheetState = rememberModalBottomSheetState(),
        containerColor = RaddPlayerSheet,
    ) {
        Column(
            Modifier
                .verticalScroll(rememberScrollState())
                .padding(bottom = 24.dp),
        ) {
            SheetTitle(
                stringResource(R.string.player_prints_title),
                modifier = Modifier.combinedClickable(
                    onClick = {},
                    onLongClick = { debugVisible = !debugVisible },
                ),
            )
            Text(
                stringResource(R.string.player_prints_note),
                color = Color.White.copy(alpha = 0.6f),
                fontSize = brandSp(12),
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
            )
            // The start budget's proof (§5 P5): route-open → first-frame, measured on this
            // device. Absent until the first start lands — a switch mid-scene must not
            // overwrite it, so the ViewModel only records genuine starts.
            state.lastFirstFrameMs?.let { firstFrameMs ->
                Text(
                    stringResource(
                        R.string.player_first_frame,
                        StartDeadline.formatSeconds(firstFrameMs),
                    ),
                    color = Color.White.copy(alpha = 0.6f),
                    fontSize = brandSp(12),
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
                )
            }
            state.bundle?.renditions?.forEach { r ->
                val active = r.rank == state.activeRendition?.rank
                val hlsTag = stringResource(R.string.player_tag_hls)
                val playingTag = stringResource(R.string.player_rune_playing)
                // PL-6: the row names the quality and the format, and marks the
                // print that is playing. The rank is debug — it shows only
                // behind the long-press above.
                val rowText = buildString {
                    append(r.displayLabel())
                    if (r.playback.isHls()) append("  ·  ").append(hlsTag)
                    if (active) append("   ← ").append(playingTag)
                    if (debugVisible) append("  ·  #").append(r.rank)
                }
                Text(
                    rowText,
                    color = if (active) RaddCurrent500 else Color.White.copy(alpha = 0.8f),
                    fontSize = brandSp(14),
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 3.dp),
                )
            }
            // Chapters (plan §5 step 11): the pack's episode boundaries as rows that
            // seek on tap. Absent for a single-episode file — no boundaries, no list.
            // The ticks come from the same pure function the scrubber draws, so the
            // two can never disagree about where a chapter starts.
            val chapters = remember(state.activeRendition?.coverage?.episodes, state.durationMs) {
                chapterTicks(state.activeRendition?.coverage?.episodes.orEmpty(), state.durationMs)
            }
            if (chapters.isNotEmpty()) {
                Spacer(Modifier.height(10.dp))
                SheetTitle(stringResource(R.string.player_chapters_title))
                chapters.forEach { tick ->
                    SheetRow(label = stringResource(R.string.player_chapter_row, tick.title, tick.offsetMs.formatTime())) {
                        vm.hidePrintSheet()
                        vm.seekTo(tick.offsetMs)
                    }
                }
            }
            // PL-6: the failover log and the policy are debug — a viewer needs to
            // know which print is playing, not the ladder it climbed. They show
            // only behind the long-press on the "Prints" title.
            if (debugVisible && state.failoverLog.isNotEmpty()) {
                Spacer(Modifier.height(10.dp))
                SheetTitle(stringResource(R.string.player_failover_log))
                state.failoverLog.forEach { record ->
                    Text(
                        stringResource(
                            R.string.player_failover_record,
                            record.rank,
                            record.label,
                            record.reason,
                            record.action,
                        ),
                        color = Color.White.copy(alpha = 0.7f),
                        fontSize = brandSp(12),
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 2.dp),
                    )
                }
            }
            if (debugVisible) {
                state.bundle?.failurePolicy?.let { p ->
                    Text(
                        stringResource(R.string.player_failover_policy, p.retrySame, p.backoffMs, p.maxRanks),
                        color = Color.White.copy(alpha = 0.5f),
                        fontSize = brandSp(11),
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp),
                    )
                }
            }
            Spacer(Modifier.height(6.dp))
            SheetRow(label = stringResource(R.string.player_play_from_row)) { vm.showPlayFromDialog() }
            if (state.canSwitchQuality) {
                SheetRow(label = stringResource(R.string.player_change_quality, state.qualityLabel)) {
                    vm.hidePrintSheet()
                    vm.showQualitySheet()
                }
            }
            SheetRow(label = stringResource(R.string.player_calibrate_row)) { vm.openCalibration() }
            SheetRow(label = stringResource(R.string.player_retry_row)) { vm.retryCurrentCandidates() }
            SheetRow(label = stringResource(R.string.player_open_external_row)) { vm.openWithExternalPlayer() }
        }
    }
}

@Composable
private fun SheetTitle(text: String, modifier: Modifier = Modifier) {
    Text(
        text,
        color = Color.White,
        fontSize = brandSp(16),
        fontWeight = FontWeight.SemiBold,
        modifier = modifier.padding(horizontal = 16.dp, vertical = 10.dp),
    )
}

@Composable
private fun SheetRow(label: String, selected: Boolean = false, enabled: Boolean = true, onClick: () -> Unit) {
    ListItem(
        headlineContent = {
            Text(
                label,
                color = when {
                    selected -> RaddCurrent500
                    !enabled -> Color.White.copy(alpha = 0.4f)
                    else -> Color.White
                },
                fontSize = brandSp(14),
            )
        },
        leadingContent = if (selected) {
            { Icon(Icons.Default.Check, null, tint = RaddCurrent500) }
        } else {
            null
        },
        // A disabled row stays visible and simply does not consume the press: hiding the
        // affordance would leave the viewer hunting for a button that has nothing to do.
        // D-43: a selected row is filled, not just green text — the state is visible
        // at a glance, not only when the viewer reads the check mark.
        modifier = Modifier
            .padding(horizontal = 4.dp)
            .background(
                if (selected) RaddCurrent500.copy(alpha = 0.15f) else Color.Transparent,
                MaterialTheme.shapes.small,
            )
            .then(if (enabled) Modifier.clickableNoRipple(onClick) else Modifier),
    )
}

// ── Event routing ──────────────────────────────────────────────────────────────

/**
 * Routes ViewModel events: messages become the on-screen snackbar via [onMessage]; the
 * external-player event fires a real intent carrying OUR OWN address; next-episode events
 * are delegated to the app (the NavGraph agent wires the PlayBundle-per-episode route —
 * see HANDOFF_appplayer.md).
 */
@Composable
private fun PlayerEventWatcher(
    vm: PlayerViewModel,
    context: Context,
    onPlayNextEpisode: (workKey: String?, postId: Int?, season: Int, episode: Int) -> Unit,
    onMessage: (String) -> Unit,
) {
    LaunchedEffect(vm) {
        vm.events.collect { event ->
            when (event) {
                is PlayerEvent.Message -> onMessage(event.text)
                is PlayerEvent.PlayNextEpisode ->
                    onPlayNextEpisode(event.workKey, event.postId, event.season, event.episode)
                is PlayerEvent.OpenExternalPlayer -> openExternally(context, event.url)
                // SC.24: share a moment — the VM built the text (title, time,
                // deep link); the screen only opens the system chooser for it.
                is PlayerEvent.ShareMoment -> shareMoment(context, event.text)
            }
        }
    }
}

// SC.24: the share chooser for a moment. No try/catch: the chooser is a system
// activity, so unlike a video player intent it always resolves.
private fun shareMoment(context: Context, text: String) {
    val intent = Intent(Intent.ACTION_SEND).apply {
        type = "text/plain"
        putExtra(Intent.EXTRA_TEXT, text)
    }
    context.startActivity(Intent.createChooser(intent, context.getString(R.string.player_share_moment)))
}

/** PiP needs Android 8+; older devices get an honest toast. */
@Composable
private fun rememberPipLauncher(aspectRatio: Float? = null, sourceRect: androidx.compose.ui.geometry.Rect? = null): () -> Unit {
    val context = LocalContext.current
    val activity = remember(context) { context.findActivity() }
    return {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && activity != null) {
            try {
                // PL-10: the PiP window follows the video's own shape, and the
                // source rect is the surface's own bounds — the window grows
                // out of the picture, not out of a corner.
                val params = android.app.PictureInPictureParams.Builder().apply {
                    if (aspectRatio != null && aspectRatio > 0f) {
                        val width = 1000
                        val height = (1000f / aspectRatio).roundToInt().coerceAtLeast(1)
                        setAspectRatio(android.util.Rational(width, height))
                    }
                    sourceRect?.let {
                        setSourceRectHint(
                            android.graphics.Rect(
                                it.left.roundToInt(),
                                it.top.roundToInt(),
                                it.right.roundToInt(),
                                it.bottom.roundToInt(),
                            ),
                        )
                    }
                }.build()
                activity.enterPictureInPictureMode(params)
            } catch (t: Throwable) {
                Toast.makeText(context, context.getString(R.string.player_pip_refused, t.message), Toast.LENGTH_SHORT).show()
            }
        } else {
            Toast.makeText(context, context.getString(R.string.player_pip_unsupported), Toast.LENGTH_SHORT).show()
        }
    }
}

private fun openExternally(context: Context, url: String) {
    try {
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(Uri.parse(url), "video/*")
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(Intent.createChooser(intent, context.getString(R.string.player_chooser)))
    } catch (_: ActivityNotFoundException) {
        Toast.makeText(context, context.getString(R.string.player_no_external_player), Toast.LENGTH_SHORT).show()
    }
}

private fun queryDisplayName(context: Context, uri: Uri): String? {
    return try {
        context.contentResolver.query(
            uri,
            arrayOf(android.provider.OpenableColumns.DISPLAY_NAME),
            null,
            null,
            null,
        )?.use { c -> if (c.moveToFirst()) c.getString(0) else null }
    } catch (_: Exception) {
        null
    }
}

private fun Context.findActivity(): Activity? {
    var currentContext: Context = this
    while (currentContext is ContextWrapper) {
        if (currentContext is Activity) return currentContext
        currentContext = currentContext.baseContext
    }
    return null
}

/**
 * Borderless press — the overlay standard for the chrome in this file.
 *
 * It used to be a raw tap detector, which is invisible to an accessibility service: nothing
 * downstream of `pointerInput` publishes a click action, so every sheet row, quality rung,
 * keep chip and play-again button in this screen could be seen by TalkBack but not pressed.
 * This is a real clickable with a Button role and no indication, so the borderless look is
 * exactly what it was and the press is now an action a screen reader can take.
 */
@Composable
private fun Modifier.clickableNoRipple(onClick: () -> Unit): Modifier =
    this.then(
        Modifier.clickable(
            interactionSource = remember { MutableInteractionSource() },
            indication = null,
            role = Role.Button,
            onClick = onClick,
        ),
    )
