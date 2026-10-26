@file:OptIn(UnstableApi::class)

package com.raddstream.app.player

import androidx.media3.common.TrackGroup
import androidx.media3.common.util.UnstableApi
import androidx.media3.ui.AspectRatioFrameLayout

/**
 * Immutable value types the player screen renders. Kept in the `player` package (Android
 * types only in [TrackUiOption.group]) so `PlayerViewModel` stays a thin driver and the
 * screen stays a thin renderer.
 */

/**
 * Video sizing, mapped 1:1 to Media3's [AspectRatioFrameLayout] resize modes (constants
 * verified in 1.3.1 source: FIT=0, FIXED_WIDTH=1, FIXED_HEIGHT=2, FILL=3, ZOOM=4).
 * MX's cycle is fit → stretch → zoom; ours cycles through all five real modes.
 */
enum class AspectMode(val label: String, val resizeMode: Int) {
    FIT("Fit", AspectRatioFrameLayout.RESIZE_MODE_FIT),
    FILL("Stretch", AspectRatioFrameLayout.RESIZE_MODE_FILL),
    ZOOM("Zoom", AspectRatioFrameLayout.RESIZE_MODE_ZOOM),
    FIXED_WIDTH("Width", AspectRatioFrameLayout.RESIZE_MODE_FIXED_WIDTH),
    FIXED_HEIGHT("Height", AspectRatioFrameLayout.RESIZE_MODE_FIXED_HEIGHT),
    ;

    companion object {
        fun nextOf(mode: AspectMode): AspectMode = entries[(mode.ordinal + 1) % entries.size]
    }
}

/** Manual video rotation (MX rotation button cycles these). The screen maps degrees to
 * `Activity.requestedOrientation`; [degrees] also drives the fallback graphics rotation. */
enum class RotationMode(val label: String, val degrees: Int) {
    NONE("Auto", 0),
    CLOCKWISE("90°", 90),
    UPSIDE_DOWN("180°", 180),
    COUNTER_CLOCKWISE("270°", 270),
    ;

    companion object {
        fun nextOf(mode: RotationMode): RotationMode = entries[(mode.ordinal + 1) % entries.size]
    }
}

/**
 * Subtitle presentation. [delayMs] is fully honoured for the custom-rendered SRT/VTT overlay;
 * for native (embedded / Media3-parsed) tracks 1.3.1 exposes no audio-sync subtitle delay —
 * size/position/style ARE applied to `SubtitleView` (PLAYER_SPEC §2.3, honest limitation).
 */
data class SubtitleUiSettings(
    /** 50..200 %; applied as fractional text size for native and sp scale for the overlay. */
    val sizePercent: Int = 100,
    /** Positive = subtitles appear later (MX "subtitle sync"). Custom path only. */
    val delayMs: Long = 0,
    /** Vertical gap from the bottom edge, fraction of video height (native + overlay). */
    val bottomFraction: Float = 0.05f,
    val bold: Boolean = false,
    val textBackground: Boolean = true,
) {
    fun clamped(): SubtitleUiSettings = copy(
        sizePercent = sizePercent.coerceIn(50, 200),
        delayMs = delayMs.coerceIn(-60_000, 60_000),
        bottomFraction = bottomFraction.coerceIn(0f, 0.4f),
    )
}

/** One selectable audio/text track row in the track sheets. */
data class TrackUiOption(
    val id: String,
    val group: TrackGroup,
    val trackIndex: Int,
    val label: String,
    val language: String?,
    val supported: Boolean,
    val selected: Boolean,
)

/** Double-tap ripple feedback: which side, which delta, and a nonce to retrigger animation. */
data class RippleState(val zone: ScreenZone, val deltaMs: Long, val nonce: Long)

/** Transient "calibrate this pack" dialog state (cat_offsets learning). */
data class CalibrationState(val targetEpisode: Int, val warning: String?)

/**
 * Everything [com.raddstream.app.ui.screens.PlayerScreen] renders, in one snapshot.
 * Defaults describe the pre-connection state so the composable never needs null games.
 */
data class PlayerUiState(
    // service connection
    val connected: Boolean = false,
    val connectionError: String? = null,
    // transport
    val isPlaying: Boolean = false,
    val isBuffering: Boolean = false,
    val isEnded: Boolean = false,
    val positionMs: Long = 0,
    val bufferedMs: Long = 0,
    val durationMs: Long = 0,
    val speed: Float = 1f,
    val boosting: Boolean = false,
    /** User's own volume; the sleep fade multiplies it (see [SleepTimer.volumeFactorFor]). */
    val userVolume: Float = 1f,
    /**
     * The persisted audio level, 0..2 ([AudioBoost]'s unit), multiplied into [userVolume]
     * by [AudioBoostUi.effectivePlayerGain]. Above 1.0 the excess is a request, not a
     * promise — see [AudioBoostUi.honestSummary].
     */
    val audioBoostLevel: Float = AudioBoost.BASELINE,
    /** The user's preferred audio language, as they spelled it; null = the player's own pick. */
    val preferredAudioLanguage: String? = null,
    /**
     * The user's preferred subtitle language, as they spelled it. Null is not "no opinion":
     * the Settings row stores the absence of a value for "Off", so null means no subtitles.
     */
    val preferredSubtitleLanguage: String? = null,
    /** The rung Auto is playing now; null when Auto is not armed (manual band or no ladder). */
    val autoQualityBand: String? = null,
    val frameRate: Float? = null,
    // lock + display
    val locked: Boolean = false,
    val aspect: AspectMode = AspectMode.FIT,
    val rotation: RotationMode = RotationMode.NONE,
    val audioOnly: Boolean = false,
    val stereoOnly: Boolean = false,
    // failover narration (§5: which print settled, why the others died)
    val bundle: PlaybackBundle? = null,
    val activeRendition: PlaybackRendition? = null,
    val failoverLog: List<FailoverRecord> = emptyList(),
    val settledBanner: String? = null,
    val giveUp: Pair<String, HandoffWhy>? = null,
    // resume prompt ("Playback interrupted! Resume from …?" MX dialog)
    val resumeOfferMs: Long? = null,
    val pendingResumeKey: String? = null,
    val pendingTitle: String? = null,
    // tracks
    val audioTracks: List<TrackUiOption> = emptyList(),
    val subtitleTracks: List<TrackUiOption> = emptyList(),
    val selectedAudioId: String? = null,
    val selectedSubtitleId: String? = null,
    val subtitle: SubtitleUiSettings = SubtitleUiSettings(),
    /** Label of the external SRT/VTT file currently rendered by the Compose overlay. */
    val customSubtitleLoaded: String? = null,
    /** External subtitles handed to Media3 natively (exotic formats). */
    val nativeExternals: List<ExternalSubtitle> = emptyList(),
    // tools
    val sleep: SleepTimerState = SleepTimerState(),
    val calibration: CalibrationState? = null,
    val ripple: RippleState? = null,
    // sheet visibility flags (kept here so every entry point funnels through the VM)
    val speedSheetVisible: Boolean = false,
    val tracksSheetVisible: Boolean = false,
    val subtitleSheetVisible: Boolean = false,
    val printSheetVisible: Boolean = false,
    val sleepSheetVisible: Boolean = false,
    val playFromDialogVisible: Boolean = false,
    val qualitySheetVisible: Boolean = false,
    /**
     * The rungs the CURRENT scope offers, staged by the detail screen and read back through
     * [PlayerSessionStore.peekAutoLadder]: band + handle + caption only. Empty for a
     * deep-linked playback, which honestly has no ladder to offer.
     */
    val qualityRungs: List<LadderRung> = emptyList(),
    /** The rung playback was launched on; null until a ladder is armed. */
    val qualityBand: String? = null,
    /** True while Auto owns the choice; a hand-picked rung sets this false. */
    val qualityAuto: Boolean = false,
    // signature feature (watching → keeping)
    val keep: KeepUiState = KeepUiState.Unavailable,
    val keepRequested: Boolean = false,
) {
    /** MX behaviour: the lock button also disables every seek path. */
    val seekEnabled: Boolean get() = !locked

    /** True when something is loaded enough to show transport controls. */
    val hasActivePrint: Boolean get() = activeRendition != null

    /**
     * This snapshot as the audio-language policy needs it: the same rows without the
     * Media3 `TrackGroup`, so the decision is a plain Kotlin list a JVM test can build.
     */
    fun audioTrackRows(): List<AudioTrackRow> =
        audioTracks.map { AudioTrackRow(it.id, it.language, it.label, it.selected, it.supported) }

    /**
     * The text tracks in the shape the subtitle-language policy consumes — the same row type
     * as [audioTrackRows], because what a language decision reads is a tag and a label, not
     * a renderer.
     */
    fun subtitleTrackRows(): List<AudioTrackRow> =
        subtitleTracks.map { AudioTrackRow(it.id, it.language, it.label, it.selected, it.supported) }

    /** Whether the cycle-audio affordance would change the sound (two playable tracks). */
    val canCycleAudio: Boolean get() = AudioTrackPolicy.canCycle(audioTrackRows())

    /**
     * The band to print on the quality control: while Auto is armed the director's live rung
     * is the truth (it may have moved on throughput), a hand-picked rung is the user's own
     * decision and never gets second-guessed by an estimate.
     */
    val qualityLabel: String
        get() = (if (qualityAuto) autoQualityBand ?: qualityBand else qualityBand)
            ?.uppercase() ?: "Auto"

    /** A switch is only honest when the scope actually offers more than one rung. */
    val canSwitchQuality: Boolean get() = qualityRungs.size > 1
}
