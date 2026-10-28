package com.raddstream.app.ui.screens

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.content.pm.ActivityInfo
import android.net.Uri
import android.os.Build
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.AspectRatio
import androidx.compose.material.icons.filled.Bedtime
import androidx.compose.material.icons.filled.BrightnessHigh
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.FastForward
import androidx.compose.material.icons.filled.HighQuality
import androidx.compose.material.icons.filled.Forward10
import androidx.compose.material.icons.filled.KeyboardArrowLeft
import androidx.compose.material.icons.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.ListAlt
import androidx.compose.material.icons.filled.LocalMovies
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.LockOpen
import androidx.compose.material.icons.filled.MusicNote
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PictureInPicture
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Replay10
import androidx.compose.material.icons.filled.RotateRight
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.Speed
import androidx.compose.material.icons.filled.Subtitles
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material.icons.filled.VolumeMute
import androidx.compose.material.icons.filled.VolumeUp
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
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
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.media3.common.util.UnstableApi
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.CaptionStyleCompat
import androidx.media3.ui.PlayerView
import androidx.media3.ui.SubtitleView
import com.raddstream.app.brand.Brand
import com.raddstream.app.player.AdSlot
import com.raddstream.app.player.AspectMode
import com.raddstream.app.player.AudioBoost
import com.raddstream.app.player.AudioBoostUi
import com.raddstream.app.player.AudioTrackPolicy
import com.raddstream.app.player.CacheAffordance
import com.raddstream.app.player.CalibrationState
import com.raddstream.app.player.DominantAxis
import com.raddstream.app.player.DragCommand
import com.raddstream.app.player.GestureMapper
import com.raddstream.app.player.GestureSettings
import com.raddstream.app.player.HandoffWhy
import com.raddstream.app.player.KeepUiState
import com.raddstream.app.player.PinchCommand
import com.raddstream.app.player.PlayerOrientation
import com.raddstream.app.player.PlayerUiState
import com.raddstream.app.player.ScreenZone
import com.raddstream.app.player.SleepMode
import com.raddstream.app.player.SleepTimerState
import com.raddstream.app.player.StartPhase
import com.raddstream.app.player.TapCommand
import com.raddstream.app.player.subtitles.SubtitleOffset
import com.raddstream.app.player.subtitles.SubtitleOffsetSheet
import com.raddstream.app.player.dragHalfZone
import com.raddstream.app.player.dominantAxis
import com.raddstream.app.viewmodel.PlayerEvent
import com.raddstream.app.viewmodel.PlayerViewModel
import com.raddstream.app.viewmodel.formatTime
import kotlinx.coroutines.delay

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
    PlayerScreenContent(state, viewModel, onBackClick, onPlayNextEpisode)
}

/** Bundle-driven entry (PlayBundle already installed into the session store by the caller). */
@Composable
fun PlayerScreen(
    title: String,
    onBackClick: () -> Unit,
    onPlayNextEpisode: (workKey: String?, postId: Int?, season: Int, episode: Int) -> Unit = { _, _, _, _ -> },
    viewModel: PlayerViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()
    PlayerScreenContent(state, viewModel, onBackClick, onPlayNextEpisode)
}

// ── Root ───────────────────────────────────────────────────────────────────────

@OptIn(UnstableApi::class, ExperimentalMaterial3Api::class)
@Composable
private fun PlayerScreenContent(
    state: PlayerUiState,
    vm: PlayerViewModel,
    onBackClick: () -> Unit,
    onPlayNextEpisode: (workKey: String?, postId: Int?, season: Int, episode: Int) -> Unit,
) {
    val context = LocalContext.current
    val activity = remember(context) { context.findActivity() }

    var controlsVisible by remember { mutableStateOf(true) }
    var interactTick by remember { mutableStateOf(0L) }
    var brightness by remember { mutableFloatStateOf(-1f) } // -1 → follow system
    var hud by remember { mutableStateOf<Hud?>(null) }
    var snackbar by remember { mutableStateOf<String?>(null) }
    var scrubPreviewMs by remember { mutableStateOf<Long?>(null) }

    val launchPip = rememberPipLauncher()
    PlayerEventWatcher(vm, context, onPlayNextEpisode) { snackbar = it }

    // Immersive fullscreen + keep-screen-on while the player exists (MX behaviour).
    DisposableEffect(activity) {
        val window = activity?.window
        window?.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val insets = window?.let { WindowInsetsControllerCompat(it, it.decorView) }
        insets?.systemBarsBehavior =
            WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        insets?.hide(WindowInsetsCompat.Type.systemBars())
        val originalBrightness = window?.attributes?.screenBrightness
        activity?.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
        onDispose {
            window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            insets?.show(WindowInsetsCompat.Type.systemBars())
            window?.let {
                val attrs = it.attributes
                attrs.screenBrightness =
                    originalBrightness ?: WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE
                it.attributes = attrs
            }
            activity?.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
        }
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
    LaunchedEffect(state.orientation) {
        activity?.requestedOrientation = when (state.orientation) {
            PlayerOrientation.LANDSCAPE -> ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
            PlayerOrientation.PORTRAIT -> ActivityInfo.SCREEN_ORIENTATION_SENSOR_PORTRAIT
        }
    }

    // Auto-hide the chrome 3.8 s into uninterrupted playback.
    LaunchedEffect(controlsVisible, state.isPlaying, interactTick, state.dialogBlocking) {
        if (controlsVisible && state.isPlaying && !state.dialogBlocking) {
            delay(3800)
            if (state.isPlaying) controlsVisible = false
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

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black),
    ) {
        // 1 — video surface or audio-only placeholder
        if (state.audioOnly) {
            AudioOnlySurface(
                title = state.pendingTitle ?: state.activeRendition?.displayLabel() ?: "Audio",
                isPlaying = state.isPlaying,
            )
        } else {
            PlayerSurface(vm, state)
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
                brightness = ((if (brightness < 0f) 0.5f else brightness) + frac).coerceIn(0f, 1f)
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
        hud?.let { HudToast(it) }
        scrubPreviewMs?.let { ScrubToast(target = it, durationMs = state.durationMs) }
        if (state.boosting) BoostBadge()

        // 5 — chrome. Ghost mode paints only the edge strip; everything else keeps the
        // three-zone MX bars, the pause scrim and the big centre button.
        if (controlsVisible && !state.locked) {
            if (state.pureCinema) {
                EdgeHud(state = state, vm = vm, onBack = onBackClick)
            } else {
                TopBar(vm = vm, state = state, onBack = onBackClick)
                CenterControls(state, vm)
                BottomControls(
                    state = state,
                    vm = vm,
                    onEnterPip = launchPip,
                    onActivity = { interactTick = System.nanoTime() },
                )
            }
        }
        if (state.locked) {
            UnlockFab(onUnlock = { vm.setLocked(false) })
        }

        // 6 — narration cards
        state.settledBanner?.let { banner ->
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.TopCenter) {
                Surface(
                    color = Color(0xCC1F2937),
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
                        Icon(Icons.Default.Check, null, tint = Color(0xFF8FD14F), modifier = Modifier.size(16.dp))
                        Spacer(Modifier.width(8.dp))
                        Text(banner, color = Color.White, fontSize = 13.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    }
                }
            }
        }

        state.giveUp?.let { (message, why) ->
            GiveUpCard(
                message = message,
                why = why,
                onRetry = { vm.retryCurrentCandidates() },
                onExternal = { vm.openWithExternalPlayer() },
                onDismiss = { vm.dismissGiveUp() },
            )
        }

        state.connectionError?.let { err ->
            ConnectionErrorCard(err, onRetry = { vm.retryCurrentCandidates() })
        }

        if (state.isBuffering && !state.isPlaying && state.giveUp == null &&
            state.startPhase == StartPhase.NONE
        ) {
            CircularProgressIndicator(
                modifier = Modifier
                    .align(Alignment.Center)
                    .size(46.dp),
                color = AccentOrange,
                strokeWidth = 3.dp,
            )
        }

        // The window before the first frame is the one a viewer cannot tell apart from a
        // crash, so it is the one window the player narrates out loud. It survives the lock
        // and Ghost mode for the same reason the buffering spinner does: feedback is not
        // furniture.
        state.startPhase.takeIf { it != StartPhase.NONE }?.let { phase ->
            StartNoticeCard(phase = phase, title = state.pendingTitle)
        }

        if (state.isEnded && controlsVisible && !state.locked && !state.pureCinema) {
            PlayAgainButton(onPlayAgain = { vm.playFrom(0) })
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
        if (state.adBreak != AdSlot.NONE) {
            SponsorBreakDialog(slot = state.adBreak, onDismiss = { vm.dismissAdBreak() })
        }

        // 8 — lightweight snackbar
        snackbar?.let { msg ->
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.BottomCenter) {
                Surface(
                    color = Color(0xE6323232),
                    shape = MaterialTheme.shapes.small,
                    modifier = Modifier
                        .padding(horizontal = 24.dp)
                        .padding(bottom = 100.dp),
                ) {
                    Text(msg, color = Color.White, fontSize = 13.sp, modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp))
                }
            }
        }
    }
}

private val AccentOrange = Color(0xFFFF8552)

/**
 * How long after a two-finger rewind the single-tap chrome toggle stays suppressed. The
 * two lanes see the same up event in different passes, so this is a safety margin for the
 * one that wins by a hair — not a debounce a user can feel.
 */
private const val TWO_FINGER_TAP_GUARD_NS = 250_000_000L

/** True when any blocking dialog/sheet is up — pauses the controls auto-hide. */
private val PlayerUiState.dialogBlocking: Boolean
    get() = resumeOfferMs != null || calibration != null || giveUp != null ||
        speedSheetVisible || tracksSheetVisible || subtitleSheetVisible ||
        subtitleOffsetSheetVisible || printSheetVisible || sleepSheetVisible ||
        playFromDialogVisible || qualitySheetVisible || adBreak != AdSlot.NONE

// ── 1. Surface ─────────────────────────────────────────────────────────────────

@OptIn(UnstableApi::class)
@Composable
private fun PlayerSurface(vm: PlayerViewModel, state: PlayerUiState) {
    val player by vm.player.collectAsState()
    AndroidView(
        modifier = Modifier.fillMaxSize(),
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
 */
@OptIn(UnstableApi::class)
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
            android.graphics.Color.WHITE,
            if (s.textBackground) 0xB3000000.toInt() else android.graphics.Color.TRANSPARENT,
            android.graphics.Color.TRANSPARENT,
            CaptionStyleCompat.EDGE_TYPE_NONE,
            android.graphics.Color.BLACK,
            null, // typeFace = null → platform default (CaptionStyleCompat has no 5-arg overload)
        ),
    )
    sv.setApplyEmbeddedStyles(true)
}

@Composable
private fun AudioOnlySurface(title: String, isPlaying: Boolean) {
    Box(Modifier.fillMaxSize().background(Color(0xFF0B0E14)), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Icon(Icons.Default.MusicNote, null, tint = AccentOrange, modifier = Modifier.size(72.dp))
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
                if (isPlaying) "Audio only — video decoder off" else "Audio only — paused",
                color = Color.White.copy(alpha = 0.6f),
                fontSize = 12.sp,
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
    val ripple = state.ripple ?: return
    val forward = ripple.deltaMs >= 0
    val label = (if (forward) "+" else "−") + (kotlin.math.abs(ripple.deltaMs) / 1000L) + "s"
    val alignment = when (ripple.zone) {
        ScreenZone.LEFT -> Alignment.CenterStart
        ScreenZone.RIGHT -> Alignment.CenterEnd
        ScreenZone.CENTER -> Alignment.Center
    }
    Box(Modifier.fillMaxSize(), contentAlignment = alignment) {
        Surface(
            color = Color(0x99000000),
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
                Text(label, color = Color.White, fontSize = 15.sp, fontWeight = FontWeight.Bold)
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
private fun HudToast(hud: Hud) {
    val icon = when (hud) {
        is Hud.Brightness -> Icons.Default.BrightnessHigh
        is Hud.Volume -> if (hud.value <= 0.01f) Icons.Default.VolumeMute else Icons.Default.VolumeUp
        is Hud.Boost -> Icons.Default.FastForward
    }
    val label = when (hud) {
        is Hud.Brightness -> "Brightness ${(hud.value * 100).toInt()}%"
        is Hud.Volume -> "Volume ${(hud.value * 100).toInt()}%"
        is Hud.Boost -> "Boosting — release to restore"
    }
    val fraction = when (hud) {
        is Hud.Brightness -> hud.value
        is Hud.Volume -> hud.value
        is Hud.Boost -> -1f
    }
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Surface(color = Color(0x99000000), shape = MaterialTheme.shapes.medium) {
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
                Text(label, color = Color.White, fontSize = 12.sp)
            }
        }
    }
}

@Composable
private fun ScrubToast(target: Long, durationMs: Long) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.BottomCenter) {
        Surface(
            color = Color(0xCC000000),
            shape = MaterialTheme.shapes.small,
            modifier = Modifier.padding(bottom = 130.dp),
        ) {
            Text(
                "${target.formatTime()} / ${durationMs.formatTime()}",
                color = Color.White,
                fontSize = 14.sp,
                modifier = Modifier.padding(horizontal = 14.dp, vertical = 6.dp),
            )
        }
    }
}

@Composable
private fun BoostBadge() {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.TopCenter) {
        Surface(
            color = Color(0xCCFF8552),
            shape = MaterialTheme.shapes.small,
            modifier = Modifier.padding(top = 92.dp),
        ) {
            Row(Modifier.padding(horizontal = 10.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Default.FastForward, null, tint = Color.Black, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(4.dp))
                Text("Boosting speed", color = Color.Black, fontSize = 12.sp, fontWeight = FontWeight.Bold)
            }
        }
    }
}

// ── 5. Chrome bars ─────────────────────────────────────────────────────────────

@Composable
private fun TopBar(vm: PlayerViewModel, state: PlayerUiState, onBack: () -> Unit) {
    val print = state.activeRendition
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(Color(0x88000000))
            .padding(start = 4.dp, end = 4.dp, top = 6.dp, bottom = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconButton(onClick = onBack) {
            Icon(Icons.Default.ArrowBack, "Back", tint = Color.White)
        }
        Spacer(Modifier.width(6.dp))
        Column(Modifier.weight(1f)) {
            Text(
                state.pendingTitle ?: print?.displayLabel() ?: Brand.name,
                color = Color.White,
                fontSize = 15.sp,
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            if (print != null) {
                Text(
                buildString {
                    append(print.displayLabel())
                    if (print.playback.isHls()) append(" · HLS")
                    if (print.playback.ephemeral) append(" · expiring link")
                    // Says out loud that the rung shown is Auto's current choice, so a
                    // quality that moves on its own is never mistaken for a hand-picked one.
                    state.autoQualityBand?.let { band -> append(" · Auto: $band") }
                },
                    color = Color.White.copy(alpha = 0.72f),
                    fontSize = 11.sp,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        if (state.sleep.mode == SleepMode.COUNTDOWN) {
            Icon(
                Icons.Default.Bedtime,
                "Sleep in ${state.sleep.remainingMs.formatTime()}",
                tint = AccentOrange,
                modifier = Modifier
                    .size(16.dp)
                    .padding(end = 6.dp),
            )
        }
        if (state.speed != 1f && !state.boosting) {
            Text(
                "${state.speed}×",
                color = AccentOrange,
                fontSize = 13.sp,
                fontWeight = FontWeight.Bold,
                modifier = Modifier.padding(end = 6.dp),
            )
        }
        KeepChip(state, vm)
        IconButton(onClick = { vm.showPrintSheet() }) {
            Icon(Icons.Default.ListAlt, "Prints & tools", tint = Color.White)
        }
    }
}

@Composable
private fun CenterControls(state: PlayerUiState, vm: PlayerViewModel) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        if (!state.isBuffering) {
            Surface(color = Color(0x66000000), shape = CircleShape) {
                IconButton(onClick = { vm.togglePlayPause() }, modifier = Modifier.size(72.dp)) {
                    Icon(
                        if (state.isPlaying) Icons.Default.Pause else Icons.Default.PlayArrow,
                        if (state.isPlaying) "Pause" else "Play",
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
    Box(Modifier.fillMaxSize()) {
        // Progress, painted on the edge of the frame rather than across the image.
        Box(
            Modifier
                .fillMaxWidth()
                .align(Alignment.TopStart)
                .height(2.dp)
                .background(Color(0x33FFFFFF)),
        ) {
            Box(
                Modifier
                    .fillMaxWidth(played)
                    .height(2.dp)
                    .background(AccentOrange),
            )
        }

        // Top-left: leave, and what is playing.
        Row(
            modifier = Modifier
                .align(Alignment.TopStart)
                .padding(start = 6.dp, top = 6.dp)
                .background(Color(0x66000000), CircleShape)
                .padding(horizontal = 6.dp, vertical = 2.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack, modifier = Modifier.size(38.dp)) {
                Icon(Icons.Default.ArrowBack, "Back", tint = Color.White, modifier = Modifier.size(20.dp))
            }
            Text(
                text = state.pendingTitle ?: state.activeRendition?.displayLabel() ?: Brand.name,
                color = Color.White.copy(alpha = 0.85f),
                fontSize = 12.sp,
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
                .background(Color(0x66000000), CircleShape)
                .padding(horizontal = 6.dp, vertical = 2.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(
                onClick = { if (state.isEnded) vm.playFrom(0) else vm.togglePlayPause() },
                modifier = Modifier.size(38.dp),
            ) {
                Icon(
                    if (state.isPlaying && !state.isBuffering) Icons.Default.Pause else Icons.Default.PlayArrow,
                    if (state.isPlaying) "Pause" else "Play",
                    tint = Color.White,
                    modifier = Modifier.size(20.dp),
                )
            }
            Text(
                text = buildString {
                    append(state.positionMs.formatTime())
                    append(if (state.durationMs > 0) " / ${state.durationMs.formatTime()}" else " / --:--")
                },
                color = Color.White.copy(alpha = 0.8f),
                fontSize = 11.sp,
                modifier = Modifier.padding(end = 8.dp),
            )
        }

        // Bottom-right: the way back to the full chrome, plus the lock.
        Row(
            modifier = Modifier
                .align(Alignment.BottomEnd)
                .padding(end = 6.dp, bottom = 10.dp)
                .background(Color(0x66000000), CircleShape)
                .padding(horizontal = 4.dp, vertical = 2.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = { vm.toggleViewMode() }, modifier = Modifier.size(38.dp)) {
                Icon(
                    Icons.Default.LocalMovies,
                    "Leave cinema mode",
                    tint = AccentOrange,
                    modifier = Modifier.size(20.dp),
                )
            }
            IconButton(onClick = { vm.setLocked(true) }, modifier = Modifier.size(38.dp)) {
                Icon(Icons.Default.Lock, "Lock controls", tint = Color.White, modifier = Modifier.size(18.dp))
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
) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.BottomCenter) {
        Column(
            Modifier
                .fillMaxWidth()
                .background(Color(0x88000000)),
        ) {
            Scrubber(
                positionMs = state.positionMs,
                bufferedMs = state.bufferedMs,
                durationMs = state.durationMs,
                enabled = state.seekEnabled,
                onSeek = { vm.seekTo(it) },
                onActivity = onActivity,
            )
            Row(
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(state.positionMs.formatTime(), color = Color.White, fontSize = 12.sp)
                Spacer(Modifier.weight(1f))
                Text(
                    if (state.durationMs > 0) state.durationMs.formatTime() else "--:--",
                    color = Color.White.copy(alpha = 0.75f),
                    fontSize = 12.sp,
                )
            }
            Row(
                Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState())
                    .padding(horizontal = 4.dp, vertical = 2.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                if (state.canSwitchQuality) {
                    PlayerControlButton({ vm.showQualitySheet() }, "Quality: ${state.qualityLabel}") {
                        Icon(
                            Icons.Default.HighQuality,
                            null,
                            tint = if (state.qualityAuto) Color.White else AccentOrange,
                        )
                    }
                }
                PlayerControlButton({ vm.showSubtitleSheet() }, "Subtitles: ${subtitleStatusLabel(state)}") {
                    Icon(Icons.Default.Subtitles, null, tint = if (subtitleActive(state)) AccentOrange else Color.White)
                }
                PlayerControlButton(
                    { vm.showSubtitleOffsetSheet() },
                    "Subtitle sync: ${SubtitleOffset.format(state.subtitle.delayMs)}",
                ) {
                    Icon(
                        Icons.Default.Sync,
                        null,
                        tint = if (state.subtitle.delayMs != 0L) AccentOrange else Color.White,
                    )
                }
                PlayerControlButton({ vm.showTracksSheet() }, "Audio tracks") {
                    Icon(
                        Icons.Default.MusicNote,
                        null,
                        tint = if (state.selectedAudioId != null) AccentOrange else Color.White,
                    )
                }
                PlayerControlButton({ vm.showSpeedSheet() }, "Speed ${state.speed}×") {
                    Icon(Icons.Default.Speed, null, tint = if (state.speed != 1f) AccentOrange else Color.White)
                }
                PlayerControlButton({ vm.setLocked(true) }, "Lock controls") {
                    Icon(Icons.Default.Lock, null, tint = Color.White)
                }
                PlayerControlButton({ vm.seekBy(-10_000); onActivity() }, "Rewind 10 seconds") {
                    Icon(Icons.Default.Replay10, null, tint = Color.White)
                }
                PlayerControlButton({ vm.seekBy(10_000); onActivity() }, "Forward 10 seconds") {
                    Icon(Icons.Default.Forward10, null, tint = Color.White)
                }
                PlayerControlButton({ vm.stepFrame(-1) }, "Step back one frame") {
                    Icon(Icons.Default.KeyboardArrowLeft, null, tint = Color.White)
                }
                PlayerControlButton({ vm.stepFrame(1) }, "Step forward one frame") {
                    Icon(Icons.Default.KeyboardArrowRight, null, tint = Color.White)
                }
                PlayerControlButton({ vm.requestNextEpisode() }, "Next episode") {
                    Icon(Icons.Default.SkipNext, null, tint = Color.White)
                }
                PlayerControlButton({ vm.showSleepSheet() }, "Sleep timer") {
                    Icon(Icons.Default.Bedtime, null, tint = if (state.sleep.mode != SleepMode.OFF) AccentOrange else Color.White)
                }
                PlayerControlButton({ vm.cycleAspect(); onActivity() }, "Aspect: ${state.aspect.label}") {
                    Icon(Icons.Default.AspectRatio, null, tint = if (state.aspect != AspectMode.FIT) AccentOrange else Color.White)
                }
                PlayerControlButton({ vm.toggleOrientation(); onActivity() }, "Orientation: ${state.orientation.label}") {
                    Icon(Icons.Default.RotateRight, null, tint = if (state.orientation == PlayerOrientation.PORTRAIT) AccentOrange else Color.White)
                }
                PlayerControlButton({ vm.toggleAudioOnly() }, "Audio-only playback") {
                    Icon(Icons.Default.MusicNote, null, tint = if (state.audioOnly) AccentOrange else Color.White)
                }
                PlayerControlButton({ vm.toggleStereoOnly() }, "Stereo-only track selection") {
                    Icon(Icons.Default.VolumeUp, null, tint = if (state.stereoOnly) AccentOrange else Color.White)
                }
                // Enters Ghost mode; the edge HUD's own chip is the only way back out, so
                // this button is deliberately last-ish and clearly labelled, not a bare icon.
                // Hidden entirely when the operator's `pure_cinema` switch is off — an entry
                // point to a frame this build refuses to paint is only a button that lies.
                if (state.pureCinemaAllowed) {
                    PlayerControlButton({ vm.toggleViewMode(); onActivity() }, "Cinema mode — hide every control") {
                        Icon(Icons.Default.LocalMovies, null, tint = Color.White)
                    }
                }
                PlayerControlButton(onEnterPip, "Picture-in-picture") {
                    Icon(Icons.Default.PictureInPicture, null, tint = Color.White)
                }
            }
        }
    }
}

private fun subtitleActive(state: PlayerUiState) =
    state.selectedSubtitleId != null || state.customSubtitleLoaded != null ||
        state.nativeExternals.isNotEmpty()

private fun subtitleStatusLabel(state: PlayerUiState): String =
    state.customSubtitleLoaded
        ?: state.selectedSubtitleId?.let { id -> state.subtitleTracks.firstOrNull { it.id == id }?.label }
        ?: "off"

@Composable
private fun PlayerControlButton(
    onClick: () -> Unit,
    contentDescription: String,
    content: @Composable () -> Unit,
) {
    IconButton(onClick = onClick, modifier = Modifier.size(42.dp)) {
        Box(Modifier.size(26.dp), contentAlignment = Alignment.Center) { content() }
    }
}

/** Thin MX scrubber: grey track, brighter buffered segment, orange played segment + thumb. */
@Composable
private fun Scrubber(
    positionMs: Long,
    bufferedMs: Long,
    durationMs: Long,
    enabled: Boolean,
    onSeek: (Long) -> Unit,
    onActivity: () -> Unit,
) {
    BoxWithConstraints(
        Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 10.dp)
            .height(20.dp),
    ) {
        val trackWidthPx = constraints.maxWidth.toFloat().coerceAtLeast(1f)
        val duration = durationMs.coerceAtLeast(1L)
        val posFraction = (positionMs.toFloat() / duration).coerceIn(0f, 1f)
        val bufFraction = (bufferedMs.toFloat() / duration).coerceIn(0f, 1f)

        Box(
            Modifier
                .align(Alignment.CenterStart)
                .fillMaxWidth()
                .height(3.dp)
                .background(Color.White.copy(alpha = 0.28f)),
        )
        Box(
            Modifier
                .align(Alignment.CenterStart)
                .fillMaxWidth(bufFraction)
                .height(3.dp)
                .background(Color.White.copy(alpha = 0.5f)),
        )
        Box(
            Modifier
                .align(Alignment.CenterStart)
                .fillMaxWidth(posFraction)
                .height(3.dp)
                .background(AccentOrange),
        )
        Box(
            Modifier
                .align(Alignment.CenterStart)
                .offset(x = maxWidth * posFraction.coerceIn(0f, 0.98f))
                .size(13.dp)
                .background(AccentOrange, shape = CircleShape),
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
private fun UnlockFab(onUnlock: () -> Unit) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.CenterEnd) {
        Surface(
            color = Color(0x88000000),
            shape = MaterialTheme.shapes.small,
            modifier = Modifier.padding(16.dp),
        ) {
            IconButton(onClick = onUnlock) {
                Icon(Icons.Default.LockOpen, "Unlock", tint = Color.White)
            }
        }
    }
}

@Composable
private fun PlayAgainButton(onPlayAgain: () -> Unit) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Surface(
            color = Color(0x99000000),
            shape = MaterialTheme.shapes.medium,
            modifier = Modifier.clickableNoRipple(onPlayAgain),
        ) {
            Row(
                Modifier.padding(horizontal = 20.dp, vertical = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(Icons.Default.Replay10, null, tint = Color.White)
                Spacer(Modifier.width(8.dp))
                Text("Play again from 0:00", color = Color.White, fontSize = 14.sp)
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
            Icon(Icons.Default.Warning, null, tint = AccentOrange, modifier = Modifier.size(40.dp))
            Spacer(Modifier.height(10.dp))
            Text(message, color = Color.White, fontSize = 13.sp, textAlign = TextAlign.Center)
            Spacer(Modifier.height(12.dp))
            OutlinedButton(onClick = onRetry) { Text("Retry", color = Color.White) }
        }
    }
}

// ── Give-up card (§5 handoff reasons) ──────────────────────────────────────────

@Composable
private fun StartNoticeCard(phase: StartPhase, title: String?) {
    val label = phase.label
    val spoken = if (title.isNullOrBlank()) label else "$label $title"
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier
                .padding(horizontal = 32.dp)
                .semantics(mergeDescendants = true) { contentDescription = spoken },
        ) {
            CircularProgressIndicator(
                modifier = Modifier.size(46.dp),
                color = AccentOrange,
                strokeWidth = 3.dp,
            )
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
                    color = Color.White.copy(alpha = 0.65f),
                    style = MaterialTheme.typography.bodySmall,
                    textAlign = TextAlign.Center,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

@Composable
private fun GiveUpCard(
    message: String,
    why: HandoffWhy,
    onRetry: () -> Unit,
    onExternal: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = Color(0xFF151A23),
        title = {
            Text(
                when (why) {
                    HandoffWhy.DOWNLOAD_ONLY -> "Download only"
                    HandoffWhy.NO_CANDIDATE_LEFT -> "Nothing playable here right now"
                },
                color = Color.White,
                fontSize = 16.sp,
            )
        },
        text = {
            Column {
                Text(message, color = Color.White.copy(alpha = 0.85f), fontSize = 13.sp)
                Spacer(Modifier.height(8.dp))
                Text(
                    when (why) {
                        HandoffWhy.DOWNLOAD_ONLY ->
                            "This quality can be kept for offline viewing, but it cannot stream here."
                        HandoffWhy.NO_CANDIDATE_LEFT ->
                            "Every option for this print failed. Retry, keep it for offline, or open it " +
                                "in another player."
                    },
                    color = Color.White.copy(alpha = 0.6f),
                    fontSize = 12.sp,
                )
            }
        },
        confirmButton = {
            Row {
                TextButton(onClick = onRetry) { Text("Retry", color = AccentOrange) }
                TextButton(onClick = onExternal) { Text("Open with another player", color = AccentOrange) }
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Close", color = Color.White.copy(alpha = 0.7f)) }
        },
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
                    color = Color.White,
                    fontSize = (16f * state.subtitle.sizePercent / 100f).sp,
                    fontWeight = if (state.subtitle.bold) FontWeight.Bold else FontWeight.Normal,
                    textAlign = TextAlign.Center,
                    modifier = if (state.subtitle.textBackground) {
                        Modifier
                            .background(Color(0xB3000000), MaterialTheme.shapes.small)
                            .padding(horizontal = 8.dp, vertical = 2.dp)
                    } else {
                        Modifier
                    },
                )
            }
        }
    }
}

// ── Keep chip — the signature "watching → keeping" affordance ─────────────────

@Composable
private fun KeepChip(state: PlayerUiState, vm: PlayerViewModel) {
    val keep = state.keep
    if (keep is KeepUiState.Unavailable) return
    Surface(
        color = when (keep) {
            is KeepUiState.Stored -> Color(0x662E7D32)
            is KeepUiState.Blocked -> Color(0x668B3A3A)
            is KeepUiState.Keeping -> Color(0x661565C0)
            else -> Color(0x88000000)
        },
        shape = MaterialTheme.shapes.small,
        modifier = Modifier
            .padding(end = 6.dp)
            .clickableNoRipple(onClick = { vm.keepCurrent() }),
    ) {
        Row(
            Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.Default.Download, null, tint = Color.White, modifier = Modifier.size(14.dp))
            Spacer(Modifier.width(4.dp))
            Text(
                CacheAffordance.chipText(keep),
                color = Color.White,
                fontSize = 11.sp,
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
        containerColor = Color(0xFF151A23),
        title = { Text("Resume playback?", color = Color.White, fontSize = 16.sp) },
        text = {
            Text(
                "You stopped at ${ms.formatTime()} on “${state.pendingTitle ?: "this print"}”.",
                color = Color.White.copy(alpha = 0.8f),
                fontSize = 13.sp,
            )
        },
        confirmButton = {
            TextButton(onClick = { vm.resolveResume(true) }) { Text("Resume", color = AccentOrange) }
        },
        dismissButton = {
            TextButton(onClick = { vm.resolveResume(false) }) { Text("Start over", color = Color.White.copy(alpha = 0.7f)) }
        },
    )
}

/**
 * A break rendered only in the two slots [AdSlot] permits. The copy states the placement
 * rule instead of inventing an ad that the app does not yet serve.
 */
@Composable
private fun SponsorBreakDialog(slot: AdSlot, onDismiss: () -> Unit) {
    val moment = when (slot) {
        AdSlot.PRE_ROLL -> "before playback starts"
        AdSlot.BETWEEN_EPISODES -> "between two episodes"
        AdSlot.NONE -> return
    }
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = Color(0xFF151A23),
        title = { Text("Sponsor break", color = Color.White, fontSize = 16.sp) },
        text = {
            Text(
                "A free-tier break can only appear $moment — never in the middle of a title. " +
                    "Continue whenever you are ready.",
                color = Color.White.copy(alpha = 0.8f),
                fontSize = 13.sp,
            )
        },
        confirmButton = {
            TextButton(onClick = onDismiss) { Text("Continue", color = AccentOrange) }
        },
    )
}

@Composable
private fun CalibrationDialog(
    state: CalibrationState,
    onConfirm: (Int) -> Unit,
    onDismiss: () -> Unit,
) {
    var text by remember { mutableStateOf(state.targetEpisode.coerceAtLeast(1).toString()) }
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = Color(0xFF151A23),
        title = { Text("Calibrate episode start", color = Color.White, fontSize = 16.sp) },
        text = {
            Column {
                Text(
                    state.warning
                        ?: "This file packs several episodes. Pause exactly where the target episode starts, then confirm.",
                    color = Color.White.copy(alpha = 0.8f),
                    fontSize = 13.sp,
                )
                Spacer(Modifier.height(10.dp))
                OutlinedTextField(
                    value = text,
                    onValueChange = { text = it.filter { c -> c.isDigit() }.take(3) },
                    label = { Text("Episode number", color = Color.White.copy(alpha = 0.6f)) },
                    singleLine = true,
                )
            }
        },
        confirmButton = {
            TextButton(
                onClick = { text.toIntOrNull()?.let { onConfirm(it) } ?: onDismiss() },
            ) { Text("Mark current position", color = AccentOrange) }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel", color = Color.White.copy(alpha = 0.7f)) }
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
        containerColor = Color(0xFF151A23),
        title = { Text("Play from", color = Color.White, fontSize = 16.sp) },
        text = {
            OutlinedTextField(
                value = text,
                onValueChange = { text = it },
                label = { Text("mm:ss or h:mm:ss", color = Color.White.copy(alpha = 0.6f)) },
                singleLine = true,
            )
        },
        confirmButton = {
            TextButton(onClick = { onSubmit(parseTimeToMs(text)) }) { Text("Go", color = AccentOrange) }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel", color = Color.White.copy(alpha = 0.7f)) }
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
        containerColor = Color(0xFF12161F),
    ) {
        Column(Modifier.padding(bottom = 20.dp)) {
            SheetTitle("Playback speed (pitch preserved)")
            Row(
                Modifier
                    .horizontalScroll(rememberScrollState())
                    .padding(horizontal = 12.dp),
            ) {
                GestureMapper.SPEED_PRESETS.forEach { preset ->
                    val selected = state.speed == preset
                    Surface(
                        color = if (selected) AccentOrange else Color(0x22FFFFFF),
                        shape = MaterialTheme.shapes.small,
                        modifier = Modifier
                            .padding(end = 6.dp)
                            .clickableNoRipple { vm.setSpeed(preset) },
                    ) {
                        Text(
                            "${preset}×",
                            color = if (selected) Color.Black else Color.White,
                            fontSize = 13.sp,
                            modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                        )
                    }
                }
            }
            Spacer(Modifier.height(12.dp))
            Text(
                "Long-press the video any time for a 2× boost — releasing restores this speed.",
                color = Color.White.copy(alpha = 0.55f),
                fontSize = 12.sp,
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
        containerColor = Color(0xFF12161F),
    ) {
        Column(Modifier.padding(bottom = 20.dp)) {
            SheetTitle("Quality")
            QualityRow(
                title = "Auto (recommended)",
                detail = if (state.qualityAuto) "Chosen from what your connection is actually moving" else null,
                selected = state.qualityAuto,
                onClick = { vm.selectQualityBand("auto") },
            )
            state.qualityRungs.forEach { rung ->
                val selected = !state.qualityAuto && rung.band == state.qualityBand
                QualityRow(
                    title = rung.label?.takeIf { it.isNotBlank() } ?: rung.band.uppercase(),
                    detail = if (selected) "Playing" else null,
                    selected = selected,
                    onClick = { vm.selectQualityBand(rung.band) },
                )
            }
            Text(
                "Switching keeps your position. Auto follows your connection and may move " +
                    "between these on its own.",
                color = Color.White.copy(alpha = 0.55f),
                fontSize = 12.sp,
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
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            title,
            color = if (selected) AccentOrange else Color.White,
            fontSize = 14.sp,
            fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
        )
        if (detail != null) {
            Spacer(Modifier.width(8.dp))
            Text(detail, color = Color.White.copy(alpha = 0.5f), fontSize = 12.sp)
        }
        Spacer(Modifier.weight(1f))
        if (selected) Icon(Icons.Default.Check, null, tint = AccentOrange, modifier = Modifier.size(18.dp))
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SleepSheet(state: PlayerUiState, vm: PlayerViewModel) {
    ModalBottomSheet(
        onDismissRequest = { vm.hideSleepSheet() },
        sheetState = rememberModalBottomSheetState(),
        containerColor = Color(0xFF12161F),
    ) {
        Column(Modifier.padding(bottom = 20.dp)) {
            SheetTitle("Sleep timer")
            if (state.sleep.mode == SleepMode.COUNTDOWN) {
                Text(
                    "Fading out — ${state.sleep.remainingMs.formatTime()} left",
                    color = AccentOrange,
                    fontSize = 13.sp,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp),
                )
            }
            SleepTimerState.PRESETS_MS.forEach { preset ->
                SheetRow(label = "${preset / 60_000} minutes") { vm.startSleepCountdown(preset) }
            }
            SheetRow(label = "At end of this video") { vm.sleepAtVideoEnd() }
            SheetRow(label = "Off") { vm.cancelSleep() }
            Text(
                "Volume fades down over the last ${state.sleep.fadeMs / 1000}s, then playback pauses (MX behaviour).",
                color = Color.White.copy(alpha = 0.55f),
                fontSize = 12.sp,
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
            val name = queryDisplayName(ctx, uri) ?: "external subtitle"
            val hint = name.substringAfterLast('.', "srt").lowercase()
            vm.addExternalSubtitle(url = uri.toString(), label = name, formatHint = hint)
        }
    }
    ModalBottomSheet(
        onDismissRequest = { vm.hideSubtitleSheet() },
        sheetState = rememberModalBottomSheetState(),
        containerColor = Color(0xFF12161F),
    ) {
        Column(
            Modifier
                .verticalScroll(rememberScrollState())
                .padding(bottom = 24.dp),
        ) {
            SheetTitle("Subtitles")
            if (state.subtitleTracks.isEmpty() && state.customSubtitleLoaded == null &&
                state.nativeExternals.isEmpty()
            ) {
                Text(
                    "No embedded subtitle tracks in this print — load an external file below.",
                    color = Color.White.copy(alpha = 0.6f),
                    fontSize = 12.sp,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
                )
            }
            state.subtitleTracks.forEach { track ->
                SheetRow(label = track.label, selected = track.id == state.selectedSubtitleId) {
                    vm.selectSubtitleTrack(track)
                }
            }
            if (state.selectedSubtitleId != null) {
                SheetRow(label = "Turn subtitles off") { vm.selectSubtitleTrack(null) }
            }

            Spacer(Modifier.height(8.dp))
            Text(
                "Size ${state.subtitle.sizePercent}%",
                color = Color.White,
                fontSize = 13.sp,
                modifier = Modifier.padding(horizontal = 16.dp),
            )
            Slider(
                value = state.subtitle.sizePercent.toFloat(),
                onValueChange = { vm.setSubtitleSettings(state.subtitle.copy(sizePercent = it.toInt())) },
                valueRange = 50f..200f,
                modifier = Modifier.padding(horizontal = 16.dp),
            )

            Text(
                "Bottom position ${(state.subtitle.bottomFraction * 100).toInt()}%",
                color = Color.White,
                fontSize = 13.sp,
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
            SheetRow(label = "Subtitle sync: ${SubtitleOffset.format(state.subtitle.delayMs)}") {
                vm.showSubtitleOffsetSheet()
            }

            Row(Modifier.padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("Bold", color = Color.White, fontSize = 13.sp, modifier = Modifier.weight(1f))
                Switch(
                    checked = state.subtitle.bold,
                    onCheckedChange = { vm.setSubtitleSettings(state.subtitle.copy(bold = it)) },
                )
            }
            Row(Modifier.padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("Text background", color = Color.White, fontSize = 13.sp, modifier = Modifier.weight(1f))
                Switch(
                    checked = state.subtitle.textBackground,
                    onCheckedChange = { vm.setSubtitleSettings(state.subtitle.copy(textBackground = it)) },
                )
            }

            Spacer(Modifier.height(8.dp))
            SheetRow(label = "Load external subtitle file (SRT / VTT / ASS)…") {
                picker.launch(arrayOf("*/*"))
            }
            if (state.customSubtitleLoaded != null) {
                SheetRow(label = "Remove “${state.customSubtitleLoaded}”") { vm.removeCustomSubtitle() }
                Text(
                    "Subtitle sync applies to this overlay and to every embedded track. " +
                        "Size, position and colour styling still come from the controls above.",
                    color = Color.White.copy(alpha = 0.55f),
                    fontSize = 11.sp,
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
        containerColor = Color(0xFF12161F),
    ) {
        Column(
            Modifier
                .verticalScroll(rememberScrollState())
                .padding(bottom = 24.dp),
        ) {
            SheetTitle("Audio tracks")
            if (state.audioTracks.isEmpty()) {
                Text(
                    "No track info for this print yet.",
                    color = Color.White.copy(alpha = 0.6f),
                    fontSize = 12.sp,
                    modifier = Modifier.padding(horizontal = 16.dp),
                )
            }
            state.audioTracks.forEach { track ->
                SheetRow(
                    label = track.label + (track.language?.let { " · $it" } ?: ""),
                    selected = track.id == state.selectedAudioId || track.selected,
                ) { vm.selectAudioTrack(track) }
            }
            if (state.audioTracks.isNotEmpty()) {
                SheetRow(label = "Cycle audio track", enabled = state.canCycleAudio) {
                    vm.cycleAudioTrack()
                }
                if (state.preferredAudioLanguage != null) {
                    Text(
                        "Preferring ${AudioTrackPolicy.nameFor(state.preferredAudioLanguage)
                            ?: state.preferredAudioLanguage} — set on the Settings screen.",
                        color = Color.White.copy(alpha = 0.55f),
                        fontSize = 11.sp,
                        modifier = Modifier.padding(horizontal = 16.dp),
                    )
                }
            }
            Spacer(Modifier.height(10.dp))
            SheetRow(
                label = if (state.stereoOnly) "Stereo-only selection: ON" else "Stereo-only selection: off",
            ) { vm.toggleStereoOnly() }
            Text(
                "Note: this restricts track SELECTION to ≤2-channel tracks; 1.3.1 cannot downmix " +
                    "5.1/Atmos to stereo.",
                color = Color.White.copy(alpha = 0.55f),
                fontSize = 11.sp,
                modifier = Modifier.padding(horizontal = 16.dp),
            )
            SheetRow(
                label = if (state.audioOnly) "Audio-only mode: ON (screen decoder off)" else "Audio-only mode: off",
            ) { vm.toggleAudioOnly() }

            // ── Audio level. The caption is the applied value, not the requested one:
            //    Media3's setVolume contract stops at 100% and this build adds no software
            //    gain, so a request above it is reported as capped. See AudioBoostUi.
            Spacer(Modifier.height(14.dp))
            SheetTitle("Audio level")
            Row(
                Modifier.padding(horizontal = 16.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Text(
                    AudioBoost.labelFor(state.audioBoostLevel),
                    color = AccentOrange,
                    fontSize = 13.sp,
                    fontWeight = FontWeight.SemiBold,
                )
                Slider(
                    value = state.audioBoostLevel.coerceIn(0f, AudioBoost.MAX),
                    onValueChange = { vm.setAudioBoostLevel(it) },
                    valueRange = 0f..AudioBoost.MAX,
                    modifier = Modifier.weight(1f),
                )
            }
            Text(
                AudioBoostUi.honestSummary(state.audioBoostLevel, state.userVolume),
                color = Color.White.copy(alpha = 0.55f),
                fontSize = 11.sp,
                modifier = Modifier.padding(horizontal = 16.dp),
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun PrintLogSheet(state: PlayerUiState, vm: PlayerViewModel) {
    ModalBottomSheet(
        onDismissRequest = { vm.hidePrintSheet() },
        sheetState = rememberModalBottomSheetState(),
        containerColor = Color(0xFF12161F),
    ) {
        Column(
            Modifier
                .verticalScroll(rememberScrollState())
                .padding(bottom = 24.dp),
        ) {
            SheetTitle("Prints & failover")
            Text(
                "Ranked candidates — the first playable one wins; switches happen automatically " +
                    "on playback errors, preserving position.",
                color = Color.White.copy(alpha = 0.6f),
                fontSize = 12.sp,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
            )
            state.bundle?.renditions?.forEach { r ->
                val active = r.rank == state.activeRendition?.rank
                Text(
                    buildString {
                        append("#${r.rank}  ${r.displayLabel()}")
                        if (r.playback.isHls()) append("  ·  HLS")
                        if (active) append("   ← playing")
                    },
                    color = if (active) AccentOrange else Color.White.copy(alpha = 0.8f),
                    fontSize = 13.sp,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 3.dp),
                )
            }
            if (state.failoverLog.isNotEmpty()) {
                Spacer(Modifier.height(10.dp))
                SheetTitle("Failover log")
                state.failoverLog.forEach { record ->
                    Text(
                        "#${record.rank} ${record.label}: ${record.reason} → ${record.action}",
                        color = Color.White.copy(alpha = 0.7f),
                        fontSize = 12.sp,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 2.dp),
                    )
                }
            }
            state.bundle?.failurePolicy?.let { p ->
                Text(
                    "Policy: retry same ×${p.retrySame}, backoff ${p.backoffMs} ms, then next rank, " +
                        "max ${p.maxRanks} ranks.",
                    color = Color.White.copy(alpha = 0.5f),
                    fontSize = 11.sp,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp),
                )
            }
            Spacer(Modifier.height(6.dp))
            SheetRow(label = "Play from a position…") { vm.showPlayFromDialog() }
            if (state.canSwitchQuality) {
                SheetRow(label = "Change quality (${state.qualityLabel})") {
                    vm.hidePrintSheet()
                    vm.showQualitySheet()
                }
            }
            SheetRow(label = "Mark current position as an episode start…") { vm.openCalibration() }
            SheetRow(label = "Retry current candidates") { vm.retryCurrentCandidates() }
            SheetRow(label = "Open in external player") { vm.openWithExternalPlayer() }
        }
    }
}

@Composable
private fun SheetTitle(text: String) {
    Text(
        text,
        color = Color.White,
        fontSize = 15.sp,
        fontWeight = FontWeight.SemiBold,
        modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
    )
}

@Composable
private fun SheetRow(label: String, selected: Boolean = false, enabled: Boolean = true, onClick: () -> Unit) {
    ListItem(
        headlineContent = {
            Text(
                label,
                color = when {
                    selected -> AccentOrange
                    !enabled -> Color.White.copy(alpha = 0.4f)
                    else -> Color.White
                },
                fontSize = 14.sp,
            )
        },
        leadingContent = if (selected) {
            { Icon(Icons.Default.Check, null, tint = AccentOrange) }
        } else {
            null
        },
        // A disabled row stays visible and simply does not consume the press: hiding the
        // affordance would leave the viewer hunting for a button that has nothing to do.
        modifier = if (enabled) {
            Modifier.clickableNoRipple(onClick).padding(horizontal = 4.dp)
        } else {
            Modifier.padding(horizontal = 4.dp)
        },
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
            }
        }
    }
}

/** PiP needs Android 8+; older devices get an honest toast. */
@Composable
private fun rememberPipLauncher(): () -> Unit {
    val context = LocalContext.current
    val activity = remember(context) { context.findActivity() }
    return {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && activity != null) {
            try {
                val params = android.app.PictureInPictureParams.Builder().build()
                activity.enterPictureInPictureMode(params)
            } catch (t: Throwable) {
                Toast.makeText(context, "PiP refused by the system: ${t.message}", Toast.LENGTH_SHORT).show()
            }
        } else {
            Toast.makeText(context, "Picture-in-picture needs Android 8.0+", Toast.LENGTH_SHORT).show()
        }
    }
}

private fun openExternally(context: Context, url: String) {
    try {
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(Uri.parse(url), "video/*")
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(Intent.createChooser(intent, "Play with…"))
    } catch (_: ActivityNotFoundException) {
        Toast.makeText(context, "No external video player found", Toast.LENGTH_SHORT).show()
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

/** Borderless press — the overlay standard for the chrome in this file. */
private fun Modifier.clickableNoRipple(onClick: () -> Unit): Modifier =
    this.then(Modifier.pointerInput(onClick) { detectTapGestures { onClick() } })
