package com.raddstream.app.ui.screens

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.content.pm.ActivityInfo
import android.graphics.Typeface
import android.net.Uri
import android.os.Build
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.media3.common.util.UnstableApi
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.CaptionStyleCompat
import androidx.media3.ui.PlayerView
import androidx.media3.ui.SubtitleView
import com.raddstream.app.R
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
import com.raddstream.app.player.SubtitleColor
import com.raddstream.app.player.TapCommand
import com.raddstream.app.player.subtitles.SubtitleOffset
import com.raddstream.app.player.subtitles.SubtitleOffsetSheet
import com.raddstream.app.player.dragHalfZone
import com.raddstream.app.player.dominantAxis
import com.raddstream.app.ui.theme.AccentOrange
import com.raddstream.app.ui.theme.AccentOrangeToast
import com.raddstream.app.ui.theme.RaddCaptionPlate
import com.raddstream.app.ui.theme.RaddCaptionPlateArgb
import com.raddstream.app.ui.theme.RaddHudBar
import com.raddstream.app.ui.theme.RaddHudCard
import com.raddstream.app.ui.theme.RaddHudChip
import com.raddstream.app.ui.theme.RaddHudPillIdle
import com.raddstream.app.ui.theme.RaddHudToast
import com.raddstream.app.ui.theme.RaddHudTrack
import com.raddstream.app.ui.theme.RaddKeepBlocked
import com.raddstream.app.ui.theme.RaddKeepKeeping
import com.raddstream.app.ui.theme.RaddKeepStored
import com.raddstream.app.ui.theme.RaddNarrationCheck
import com.raddstream.app.ui.theme.RaddNarrationPlate
import com.raddstream.app.ui.theme.RaddPlayerDialog
import com.raddstream.app.ui.theme.RaddPlayerSheet
import com.raddstream.app.ui.theme.RaddPlayerSnackbarPlate
import com.raddstream.app.ui.theme.RaddPlayerStage
import com.raddstream.app.ui.theme.brandSp
import com.raddstream.app.ui.theme.paint
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
                title = state.pendingTitle ?: state.activeRendition?.displayLabel() ?: stringResource(R.string.player_audio_title),
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
                        Text(banner, color = Color.White, fontSize = brandSp(13), maxLines = 2, overflow = TextOverflow.Ellipsis)
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
                    color = RaddPlayerSnackbarPlate,
                    shape = MaterialTheme.shapes.small,
                    modifier = Modifier
                        .padding(horizontal = 24.dp)
                        .padding(bottom = 100.dp),
                ) {
                    Text(msg, color = Color.White, fontSize = brandSp(13), modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp))
                }
            }
        }
    }
}

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

// Fully qualified on purpose: this file also uses Kotlin's `@OptIn` for
// ExperimentalMaterial3Api, and the two annotations answer different checkers. Media3's
// `UnsafeOptInUsageError` is a *lint* check that reads `androidx.annotation.OptIn` only, so the
// Kotlin form here compiled clean and left 20 lint errors.
@androidx.annotation.OptIn(UnstableApi::class)
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
    sv.setApplyEmbeddedStyles(true)
}

@Composable
private fun AudioOnlySurface(title: String, isPlaying: Boolean) {
    Box(Modifier.fillMaxSize().background(RaddPlayerStage), contentAlignment = Alignment.Center) {
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
            color = RaddHudCard,
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
                Text(label, color = Color.White, fontSize = brandSp(15), fontWeight = FontWeight.Bold)
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
        Surface(color = RaddHudCard, shape = MaterialTheme.shapes.medium) {
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
private fun ScrubToast(target: Long, durationMs: Long) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.BottomCenter) {
        Surface(
            color = RaddHudToast,
            shape = MaterialTheme.shapes.small,
            modifier = Modifier.padding(bottom = 130.dp),
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

@Composable
private fun BoostBadge() {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.TopCenter) {
        Surface(
            color = AccentOrangeToast,
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
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(RaddHudBar)
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
                fontSize = brandSp(15),
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            if (print != null) {
                val hlsTag = stringResource(R.string.player_tag_hls)
                val expiringTag = stringResource(R.string.player_tag_expiring)
                val autoTag = state.autoQualityBand?.let { band -> stringResource(R.string.player_tag_auto, band) }
                Text(
                buildString {
                    append(print.displayLabel())
                    if (print.playback.isHls()) append(" · ").append(hlsTag)
                    if (print.playback.ephemeral) append(" · ").append(expiringTag)
                    // Says out loud that the rung shown is Auto's current choice, so a
                    // quality that moves on its own is never mistaken for a hand-picked one.
                    autoTag?.let { append(" · ").append(it) }
                },
                    color = Color.White.copy(alpha = 0.72f),
                    fontSize = brandSp(11),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        if (state.sleep.mode == SleepMode.COUNTDOWN) {
            Icon(
                Icons.Default.Bedtime,
                stringResource(R.string.player_sleep_remaining, state.sleep.remainingMs.formatTime()),
                tint = AccentOrange,
                modifier = Modifier
                    .size(16.dp)
                    .padding(end = 6.dp),
            )
        }
        if (state.speed != 1f && !state.boosting) {
            Text(
                stringResource(R.string.player_speed_short, state.speed),
                color = AccentOrange,
                fontSize = brandSp(13),
                fontWeight = FontWeight.Bold,
                modifier = Modifier.padding(end = 6.dp),
            )
        }
        KeepChip(state, vm)
        IconButton(onClick = { vm.showPrintSheet() }) {
            Icon(Icons.Default.ListAlt, stringResource(R.string.player_prints_tools), tint = Color.White)
        }
    }
}

@Composable
private fun CenterControls(state: PlayerUiState, vm: PlayerViewModel) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        if (!state.isBuffering) {
            Surface(color = RaddHudChip, shape = CircleShape) {
                IconButton(onClick = { vm.togglePlayPause() }, modifier = Modifier.size(72.dp)) {
                    Icon(
                        if (state.isPlaying) Icons.Default.Pause else Icons.Default.PlayArrow,
                        if (state.isPlaying) stringResource(R.string.player_pause) else stringResource(R.string.player_play),
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
                .background(RaddHudTrack),
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
                .background(RaddHudChip, CircleShape)
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
                .background(RaddHudChip, CircleShape)
                .padding(horizontal = 6.dp, vertical = 2.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            ControlTarget(
                label = if (state.isPlaying) stringResource(R.string.player_pause) else stringResource(R.string.player_play),
                onClick = { if (state.isEnded) vm.playFrom(0) else vm.togglePlayPause() },
            ) {
                Icon(
                    if (state.isPlaying && !state.isBuffering) Icons.Default.Pause else Icons.Default.PlayArrow,
                    null,
                    tint = Color.White,
                    modifier = Modifier.size(20.dp),
                )
            }
            Text(
                text = if (state.durationMs > 0) {
                    stringResource(
                        R.string.player_time_of,
                        state.positionMs.formatTime(),
                        state.durationMs.formatTime(),
                    )
                } else {
                    stringResource(R.string.player_time_of_unknown, state.positionMs.formatTime())
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
                .background(RaddHudChip, CircleShape)
                .padding(horizontal = 4.dp, vertical = 2.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            ControlTarget(label = stringResource(R.string.player_leave_cinema), onClick = { vm.toggleViewMode() }) {
                Icon(
                    Icons.Default.LocalMovies,
                    null,
                    tint = AccentOrange,
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
) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.BottomCenter) {
        Column(
            Modifier
                .fillMaxWidth()
                .background(RaddHudBar),
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
                Text(state.positionMs.formatTime(), color = Color.White, fontSize = brandSp(12))
                Spacer(Modifier.weight(1f))
                Text(
                    if (state.durationMs > 0) state.durationMs.formatTime() else "--:--",
                    color = Color.White.copy(alpha = 0.75f),
                    fontSize = brandSp(12),
                )
            }
            Row(
                Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState())
                    .padding(horizontal = 4.dp, vertical = 2.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                val subtitleWord = subtitleStatusLabel(state, stringResource(R.string.player_off))
                if (state.canSwitchQuality) {
                    PlayerControlButton({ vm.showQualitySheet() }, stringResource(R.string.player_quality_label, state.qualityLabel)) {
                        Icon(
                            Icons.Default.HighQuality,
                            null,
                            tint = if (state.qualityAuto) Color.White else AccentOrange,
                        )
                    }
                }
                PlayerControlButton({ vm.showSubtitleSheet() }, stringResource(R.string.player_subtitles_label, subtitleWord)) {
                    Icon(Icons.Default.Subtitles, null, tint = if (subtitleActive(state)) AccentOrange else Color.White)
                }
                PlayerControlButton(
                    { vm.showSubtitleOffsetSheet() },
                    stringResource(R.string.player_subtitle_sync, SubtitleOffset.format(state.subtitle.delayMs)),
                ) {
                    Icon(
                        Icons.Default.Sync,
                        null,
                        tint = if (state.subtitle.delayMs != 0L) AccentOrange else Color.White,
                    )
                }
                PlayerControlButton({ vm.showTracksSheet() }, stringResource(R.string.player_audio_tracks)) {
                    Icon(
                        Icons.Default.MusicNote,
                        null,
                        tint = if (state.selectedAudioId != null) AccentOrange else Color.White,
                    )
                }
                PlayerControlButton({ vm.showSpeedSheet() }, stringResource(R.string.player_speed_label, state.speed)) {
                    Icon(Icons.Default.Speed, null, tint = if (state.speed != 1f) AccentOrange else Color.White)
                }
                PlayerControlButton({ vm.setLocked(true) }, stringResource(R.string.player_lock)) {
                    Icon(Icons.Default.Lock, null, tint = Color.White)
                }
                PlayerControlButton({ vm.seekBy(-10_000); onActivity() }, stringResource(R.string.player_rewind_10)) {
                    Icon(Icons.Default.Replay10, null, tint = Color.White)
                }
                PlayerControlButton({ vm.seekBy(10_000); onActivity() }, stringResource(R.string.player_forward_10)) {
                    Icon(Icons.Default.Forward10, null, tint = Color.White)
                }
                PlayerControlButton({ vm.stepFrame(-1) }, stringResource(R.string.player_frame_back)) {
                    Icon(Icons.Default.KeyboardArrowLeft, null, tint = Color.White)
                }
                PlayerControlButton({ vm.stepFrame(1) }, stringResource(R.string.player_frame_forward)) {
                    Icon(Icons.Default.KeyboardArrowRight, null, tint = Color.White)
                }
                PlayerControlButton({ vm.requestNextEpisode() }, stringResource(R.string.player_next_episode)) {
                    Icon(Icons.Default.SkipNext, null, tint = Color.White)
                }
                PlayerControlButton({ vm.showSleepSheet() }, stringResource(R.string.player_sleep_timer)) {
                    Icon(Icons.Default.Bedtime, null, tint = if (state.sleep.mode != SleepMode.OFF) AccentOrange else Color.White)
                }
                PlayerControlButton({ vm.cycleAspect(); onActivity() }, stringResource(R.string.player_aspect_label, state.aspect.label)) {
                    Icon(Icons.Default.AspectRatio, null, tint = if (state.aspect != AspectMode.FIT) AccentOrange else Color.White)
                }
                PlayerControlButton({ vm.toggleOrientation(); onActivity() }, stringResource(R.string.player_orientation_label, state.orientation.label)) {
                    Icon(Icons.Default.RotateRight, null, tint = if (state.orientation == PlayerOrientation.PORTRAIT) AccentOrange else Color.White)
                }
                PlayerControlButton({ vm.toggleAudioOnly() }, stringResource(R.string.player_audio_only_toggle)) {
                    Icon(Icons.Default.MusicNote, null, tint = if (state.audioOnly) AccentOrange else Color.White)
                }
                PlayerControlButton({ vm.toggleStereoOnly() }, stringResource(R.string.player_stereo_only_toggle)) {
                    Icon(Icons.Default.VolumeUp, null, tint = if (state.stereoOnly) AccentOrange else Color.White)
                }
                // Enters Ghost mode; the edge HUD's own chip is the only way back out, so
                // this button is deliberately last-ish and clearly labelled, not a bare icon.
                // Hidden entirely when the operator's `pure_cinema` switch is off — an entry
                // point to a frame this build refuses to paint is only a button that lies.
                if (state.pureCinemaAllowed) {
                    PlayerControlButton({ vm.toggleViewMode(); onActivity() }, stringResource(R.string.player_cinema_mode)) {
                        Icon(Icons.Default.LocalMovies, null, tint = Color.White)
                    }
                }
                PlayerControlButton(onEnterPip, stringResource(R.string.player_pip)) {
                    Icon(Icons.Default.PictureInPicture, null, tint = Color.White)
                }
            }
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
@Composable
private fun ControlTarget(
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    val spoken = label
    Box(
        modifier = modifier
            .size(MinControlTarget)
            .clip(CircleShape)
            .clickable(onClick = onClick, role = Role.Button)
            .semantics { contentDescription = spoken },
        contentAlignment = Alignment.Center,
    ) { content() }
}

@Composable
private fun PlayerControlButton(
    onClick: () -> Unit,
    label: String,
    content: @Composable () -> Unit,
) {
    ControlTarget(label = label, onClick = onClick) {
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
            color = RaddHudBar,
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
private fun PlayAgainButton(onPlayAgain: () -> Unit) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Surface(
            color = RaddHudCard,
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
            Text(message, color = Color.White, fontSize = brandSp(13), textAlign = TextAlign.Center)
            Spacer(Modifier.height(12.dp))
            OutlinedButton(onClick = onRetry) { Text(stringResource(R.string.player_retry), color = Color.White) }
        }
    }
}

// ── Give-up card (§5 handoff reasons) ──────────────────────────────────────────

@Composable
private fun StartNoticeCard(phase: StartPhase, title: String?) {
    val label = phase.label
    val spoken = if (title.isNullOrBlank()) label else stringResource(R.string.player_notice_spaced, label, title)
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
        containerColor = RaddPlayerDialog,
        title = {
            Text(
                when (why) {
                    HandoffWhy.DOWNLOAD_ONLY -> stringResource(R.string.player_giveup_download_only)
                    HandoffWhy.NO_CANDIDATE_LEFT -> stringResource(R.string.player_giveup_no_candidate)
                },
                color = Color.White,
                fontSize = brandSp(16),
            )
        },
        text = {
            Column {
                Text(message, color = Color.White.copy(alpha = 0.85f), fontSize = brandSp(13))
                Spacer(Modifier.height(8.dp))
                Text(
                    when (why) {
                        HandoffWhy.DOWNLOAD_ONLY ->
                            stringResource(R.string.player_giveup_download_body)
                        HandoffWhy.NO_CANDIDATE_LEFT ->
                            stringResource(R.string.player_giveup_no_candidate_body)
                    },
                    color = Color.White.copy(alpha = 0.6f),
                    fontSize = brandSp(12),
                )
            }
        },
        confirmButton = {
            Row {
                TextButton(onClick = onRetry) { Text(stringResource(R.string.player_retry), color = AccentOrange) }
                TextButton(onClick = onExternal) { Text(stringResource(R.string.player_open_external), color = AccentOrange) }
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text(stringResource(R.string.player_close), color = Color.White.copy(alpha = 0.7f)) }
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
    Surface(
        color = when (keep) {
            is KeepUiState.Stored -> RaddKeepStored
            is KeepUiState.Blocked -> RaddKeepBlocked
            is KeepUiState.Keeping -> RaddKeepKeeping
            else -> RaddHudBar
        },
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
            Icon(Icons.Default.Download, null, tint = Color.White, modifier = Modifier.size(14.dp))
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
        title = { Text(stringResource(R.string.player_resume_title), color = Color.White, fontSize = brandSp(16)) },
        text = {
            Text(
                stringResource(
                    R.string.player_resume_body,
                    ms.formatTime(),
                    state.pendingTitle ?: stringResource(R.string.player_this_print),
                ),
                color = Color.White.copy(alpha = 0.8f),
                fontSize = brandSp(13),
            )
        },
        confirmButton = {
            TextButton(onClick = { vm.resolveResume(true) }) { Text(stringResource(R.string.player_resume), color = AccentOrange) }
        },
        dismissButton = {
            TextButton(onClick = { vm.resolveResume(false) }) { Text(stringResource(R.string.player_start_over), color = Color.White.copy(alpha = 0.7f)) }
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
        AdSlot.PRE_ROLL -> stringResource(R.string.player_slot_pre_roll)
        AdSlot.BETWEEN_EPISODES -> stringResource(R.string.player_slot_between)
        AdSlot.NONE -> return
    }
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = RaddPlayerDialog,
        title = { Text(stringResource(R.string.player_ad_title), color = Color.White, fontSize = brandSp(16)) },
        text = {
            Text(
                stringResource(R.string.player_ad_body, moment),
                color = Color.White.copy(alpha = 0.8f),
                fontSize = brandSp(13),
            )
        },
        confirmButton = {
            TextButton(onClick = onDismiss) { Text(stringResource(R.string.player_continue), color = AccentOrange) }
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
        containerColor = RaddPlayerDialog,
        title = { Text(stringResource(R.string.player_calibration_title), color = Color.White, fontSize = brandSp(16)) },
        text = {
            Column {
                Text(
                    state.warning ?: stringResource(R.string.player_calibration_body),
                    color = Color.White.copy(alpha = 0.8f),
                    fontSize = brandSp(13),
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
            ) { Text(stringResource(R.string.player_mark_position), color = AccentOrange) }
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
        title = { Text(stringResource(R.string.player_play_from_title), color = Color.White, fontSize = brandSp(16)) },
        text = {
            OutlinedTextField(
                value = text,
                onValueChange = { text = it },
                label = { Text(stringResource(R.string.player_play_from_hint), color = Color.White.copy(alpha = 0.6f)) },
                singleLine = true,
            )
        },
        confirmButton = {
            TextButton(onClick = { onSubmit(parseTimeToMs(text)) }) { Text(stringResource(R.string.player_go), color = AccentOrange) }
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
                        color = if (selected) AccentOrange else RaddHudPillIdle,
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
                                fontSize = brandSp(13),
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
            state.qualityRungs.forEach { rung ->
                val selected = !state.qualityAuto && rung.band == state.qualityBand
                QualityRow(
                    title = rung.label?.takeIf { it.isNotBlank() } ?: rung.band.uppercase(),
                    detail = if (selected) stringResource(R.string.player_playing) else null,
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
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            title,
            color = if (selected) AccentOrange else Color.White,
            fontSize = brandSp(14),
            fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
        )
        if (detail != null) {
            Spacer(Modifier.width(8.dp))
            Text(detail, color = Color.White.copy(alpha = 0.5f), fontSize = brandSp(12))
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
        containerColor = RaddPlayerSheet,
    ) {
        Column(Modifier.padding(bottom = 20.dp)) {
            SheetTitle(stringResource(R.string.player_sleep_timer))
            if (state.sleep.mode == SleepMode.COUNTDOWN) {
                Text(
                    stringResource(R.string.player_sleep_fading, state.sleep.remainingMs.formatTime()),
                    color = AccentOrange,
                    fontSize = brandSp(13),
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
            if (state.subtitleTracks.isEmpty() && state.customSubtitleLoaded == null &&
                state.nativeExternals.isEmpty()
            ) {
                Text(
                    stringResource(R.string.player_subtitle_none),
                    color = Color.White.copy(alpha = 0.6f),
                    fontSize = brandSp(12),
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
                )
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
                fontSize = brandSp(13),
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
                fontSize = brandSp(13),
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
                Text(stringResource(R.string.player_subtitle_bold), color = Color.White, fontSize = brandSp(13), modifier = Modifier.weight(1f))
                Switch(
                    checked = state.subtitle.bold,
                    onCheckedChange = { vm.setSubtitleSettings(state.subtitle.copy(bold = it)) },
                )
            }
            Row(Modifier.padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(stringResource(R.string.player_subtitle_background), color = Color.White, fontSize = brandSp(13), modifier = Modifier.weight(1f))
                Switch(
                    checked = state.subtitle.textBackground,
                    onCheckedChange = { vm.setSubtitleSettings(state.subtitle.copy(textBackground = it)) },
                )
            }

            Text(
                stringResource(R.string.player_subtitle_colour),
                color = Color.White,
                fontSize = brandSp(13),
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
                    color = AccentOrange,
                    fontSize = brandSp(13),
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

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun PrintLogSheet(state: PlayerUiState, vm: PlayerViewModel) {
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
            SheetTitle(stringResource(R.string.player_prints_title))
            Text(
                stringResource(R.string.player_prints_note),
                color = Color.White.copy(alpha = 0.6f),
                fontSize = brandSp(12),
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
            )
            state.bundle?.renditions?.forEach { r ->
                val active = r.rank == state.activeRendition?.rank
                val rankText = stringResource(R.string.player_rune_rank, r.rank, r.displayLabel())
                val hlsTag = stringResource(R.string.player_tag_hls)
                val playingTag = stringResource(R.string.player_rune_playing)
                Text(
                    buildString {
                        append(rankText)
                        if (r.playback.isHls()) append("  ·  ").append(hlsTag)
                        if (active) append("   ← ").append(playingTag)
                    },
                    color = if (active) AccentOrange else Color.White.copy(alpha = 0.8f),
                    fontSize = brandSp(13),
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 3.dp),
                )
            }
            if (state.failoverLog.isNotEmpty()) {
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
            state.bundle?.failurePolicy?.let { p ->
                Text(
                    stringResource(R.string.player_failover_policy, p.retrySame, p.backoffMs, p.maxRanks),
                    color = Color.White.copy(alpha = 0.5f),
                    fontSize = brandSp(11),
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp),
                )
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
private fun SheetTitle(text: String) {
    Text(
        text,
        color = Color.White,
        fontSize = brandSp(15),
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
                fontSize = brandSp(14),
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
