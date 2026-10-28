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

/**
 * How much chrome the player paints over the picture.
 *
 * [STANDARD] is the MX-style three-zone chrome every control lives in. [PURE_CINEMA] is the
 * Ghost mode: no pause scrim, no giant centre play button, no full-width top and bottom
 * bars — the whole frame is picture, and the only chrome left is a translucent strip at the
 * edges that fades out with the same timer the normal bars use. Entering it is a deliberate
 * choice (a button in the standard bottom row), leaving it is one tap of that same edge
 * strip, so a viewer can never be trapped in a chrome-less frame they cannot escape.
 *
 * Ghost mode does not remove feedback, only furniture: buffering, the seek acknowledgements,
 * the failover cards and the give-up card all still show, because a viewer who cannot find
 * the pause button is worse off than one who sees a spinner.
 */
enum class ViewMode(val label: String) {
    STANDARD("Full chrome"),
    PURE_CINEMA("Ghost"),
    ;

    companion object {
        fun nextOf(mode: ViewMode): ViewMode = entries[(mode.ordinal + 1) % entries.size]

        /** Storage contract: an unknown or absent name is the mode nobody opted into. */
        fun fromName(name: String?): ViewMode = entries.firstOrNull { it.name == name } ?: STANDARD
    }
}

/**
 * What the player owes the viewer while the picture they asked for is not on screen yet.
 *
 * The screen used to paint nothing at all in that window: a black frame from the moment the
 * route opened until Media3 decoded its first frame, which on a slow resolver or a cold
 * service start is indistinguishable from a crash. The phase is DERIVED, never stored — the
 * fields below are the ones the listener already publishes — so no second source of truth
 * can disagree with the player about whether it is still coming.
 *
 * [CONNECTING_PLAYER] is the window before the `MediaController` exists; [STARTING] is every
 * moment after that where no file has been loaded yet. A stall once the file IS loaded is not
 * a start at all, so it is [NONE] and the plain buffering spinner owns it; a viewer's own
 * pause is neither.
 */
enum class StartPhase(val label: String) {
    NONE(""),
    CONNECTING_PLAYER("Connecting to the player…"),
    STARTING("Starting playback…"),
    ;
}

/**
 * Screen orientation while the player is open. Playback entry locks to sensor landscape;
 * the Rotate control flips between the two so a viewer can watch portrait in one tap.
 */
enum class PlayerOrientation(val label: String) {
    LANDSCAPE("Landscape"),
    PORTRAIT("Portrait"),
    ;

    fun toggled(): PlayerOrientation = if (this == LANDSCAPE) PORTRAIT else LANDSCAPE
}

/**
 * The caption colours the subtitle sheet offers, in the order it shows them.
 *
 * WHY CHANNELS AND NOT A PAINT: one stored value has to reach two renderers that speak
 * different types — Media3's `CaptionStyleCompat` wants an `android.graphics.Color` int, the
 * Compose overlay wants a [androidx.compose.ui.graphics.Color] — and neither may invent the
 * value at the call site. The channels stay plain 0..255 integers so this file keeps no
 * dependency on a UI toolkit; `ui/theme/Color.kt` owns the single Compose conversion.
 *
 * WHY EXACTLY THESE FOUR: every one is bright enough to read against a busy picture with no
 * plate behind it, and the `textBackground` switch lets a viewer remove that plate. That is a
 * rule, not taste — `SubtitleStylePersistenceTest` fails if a colour dim enough to need a
 * plate is added.
 */
enum class SubtitleColor(val wireName: String, val label: String, val red: Int, val green: Int, val blue: Int) {
    WHITE("white", "White", 255, 255, 255),
    YELLOW("yellow", "Yellow", 255, 238, 122),
    CYAN("cyan", "Cyan", 137, 232, 255),
    PINK("pink", "Pink", 255, 154, 203),
    ;

    /** The same colour packed the way `CaptionStyleCompat` and `android.graphics.Color` take it. */
    val argb: Int get() = (OPAQUE shl 24) or (red shl 16) or (green shl 8) or blue

    companion object {
        private const val OPAQUE = 0xFF

        /**
         * A stored name back to a colour. Unknown, blank, or never-stored is the shipped
         * default, never a guess: a build that renames a chip leaves every viewer with readable
         * text rather than a half-applied style.
         */
        fun fromWire(name: String?): SubtitleColor =
            entries.firstOrNull { it.wireName == name?.trim()?.lowercase() } ?: WHITE
    }
}

/**
 * Subtitle presentation. [delayMs] is honoured on both render paths: the custom SRT/VTT
 * overlay reads it directly, and native (embedded / Media3-parsed) tracks are retimed by
 * the decoder wrapper the playback service installs. Size/position/style reach the native
 * `SubtitleView` as before (PLAYER_SPEC §2.3).
 *
 * Everything here except [delayMs] is the viewer's own look and is persisted; the offset is
 * a correction made to one viewing, and [withDelay] is what keeps a stored reload from
 * wiping it mid-film.
 */
data class SubtitleUiSettings(
    /** 50..200 %; applied as fractional text size for native and sp scale for the overlay. */
    val sizePercent: Int = 100,
    /** Positive = subtitles appear later (MX "subtitle sync"); both render paths. */
    val delayMs: Long = 0,
    /** Vertical gap from the bottom edge, fraction of video height (native + overlay). */
    val bottomFraction: Float = 0.05f,
    val bold: Boolean = false,
    val textBackground: Boolean = true,
    val colour: SubtitleColor = SubtitleColor.WHITE,
) {
    fun clamped(): SubtitleUiSettings = copy(
        sizePercent = sizePercent.coerceIn(50, 200),
        delayMs = delayMs.coerceIn(-60_000, 60_000),
        bottomFraction = bottomFraction.coerceIn(0f, 0.4f),
    )

    /** This look wearing the offset the current viewing already dialled in. */
    fun withDelay(delay: Long): SubtitleUiSettings = copy(delayMs = delay)
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
    val orientation: PlayerOrientation = PlayerOrientation.LANDSCAPE,
    /** Ghost mode or the full MX chrome. Persisted, because nobody wants it reset per episode. */
    val viewMode: ViewMode = ViewMode.STANDARD,
    /**
     * Whether the operator's `feature_flags.pure_cinema` currently allows Ghost mode at all.
     * Mirrors the server board; the viewer's saved [viewMode] is left alone, so a switch that
     * comes back on restores the frame they last asked for instead of having overwritten it.
     */
    val pureCinemaAllowed: Boolean = true,
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
    val subtitleOffsetSheetVisible: Boolean = false,
    val printSheetVisible: Boolean = false,
    val sleepSheetVisible: Boolean = false,
    val playFromDialogVisible: Boolean = false,
    val qualitySheetVisible: Boolean = false,
    /**
     * The sponsor slot currently on screen, if any. Only [AdSlotPolicy.decide] can raise it,
     * and that policy has no value for a title that is playing — so this field can never be
     * the reason a scene is interrupted.
     */
    val adBreak: AdSlot = AdSlot.NONE,
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

    /**
     * Ghost mode. Every chrome decision in the screen asks this one question instead of
     * comparing the enum at four call sites — the pause scrim, the centre play button and
     * the full-width bars are the three things it switches off, and the edge strip plus the
     * two-finger rewind are the two things it switches on.
     *
     * The answer is the viewer's choice ANDed with the operator's switch: with
     * `pure_cinema` off, no frame of this app hides its controls, whatever a stale DataStore
     * value says. Deriving it here rather than sanitising [viewMode] is what keeps the
     * viewer's own preference intact for the moment the switch flips back.
     */
    val pureCinema: Boolean get() = pureCinemaAllowed && viewMode == ViewMode.PURE_CINEMA

    /** True when something is loaded enough to show transport controls. */
    val hasActivePrint: Boolean get() = activeRendition != null

    /**
     * The one question the screen asks to decide whether it owes the viewer a "coming right
     * up" notice. Every card that already explains itself wins over this, and once the file
     * is loaded (`durationMs` known) the notice has nothing left to say — a stall then is
     * buffering, and a silence is the viewer's own pause.
     */
    val startPhase: StartPhase
        get() = when {
            connectionError != null -> StartPhase.NONE
            giveUp != null -> StartPhase.NONE
            resumeOfferMs != null -> StartPhase.NONE
            isPlaying -> StartPhase.NONE
            isEnded -> StartPhase.NONE
            !connected -> StartPhase.CONNECTING_PLAYER
            durationMs == 0L -> StartPhase.STARTING
            else -> StartPhase.NONE
        }

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
