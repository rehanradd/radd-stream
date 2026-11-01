package com.raddstream.app.player

/**
 * Which controls the player paints, and where.
 *
 * The spec's player is an MX-Player-shaped surface: back and title and quality at the top,
 * play/pause in the middle, seek bar and time and the two ten-second jumps and fullscreen at the
 * bottom, subtitles only when there are subtitles, audio only when there is more than one track,
 * the bar gone after about three seconds — and everything else behind one "More" button. The word
 * the spec is careful about is MOVED, not deleted: the app already has a sleep timer, a frame
 * stepper, aspect and orientation switches, an audio-only mode, cinema mode, picture-in-picture,
 * a subtitle delay, a failover log. They stay reachable; they stop being the surface a first-time
 * viewer has to interpret.
 *
 * That split is a table of booleans, and a table is exactly the thing that goes quietly wrong in a
 * composable — an `if` copied into a second place, one branch updated, and a button appears for a
 * title with no subtitles. So the table is here, where a JVM test can walk it. The screen reads
 * [Plan.bar] and [Plan.more] and paints what it is told; it decides nothing.
 */
object PlayerChromePlan {

    /** How long the bar stays up once the viewer stops touching it. The spec says about three seconds. */
    const val AUTO_HIDE_MS = 3000L

    /** Every control the player owns. The bar set and the More set are chosen from these. */
    enum class Control {
        BACK,
        TITLE,
        QUALITY,
        PLAY_PAUSE,
        SEEK,
        ELAPSED,
        SKIP_BACK,
        SKIP_FORWARD,
        FULLSCREEN,
        SUBTITLES,
        AUDIO_TRACKS,
        NEXT_EPISODE,
        MORE,
        SPEED,
        SUBTITLE_DELAY,
        LOCK,
        FRAME_BACK,
        FRAME_FORWARD,
        SLEEP_TIMER,
        ASPECT,
        ORIENTATION,
        AUDIO_ONLY,
        STEREO_ONLY,
        CINEMA_MODE,
        PICTURE_IN_PICTURE,
        SOURCE_LOG,
        OPEN_EXTERNALLY,
    }

    /**
     * What the player knows about this title and this moment — the only inputs the table reads.
     * Each one is a fact the player already has: [subtitleCount] and [audioTrackCount] come from
     * the tracks Media3 reported, [qualityCount] from the ladder's rungs
     * ([PlayerUiState.qualityRungs]), [hasNextEpisode] from the session scope's own numbering.
     */
    data class Inputs(
        val subtitleCount: Int,
        val audioTrackCount: Int,
        val qualityCount: Int,
        val hasNextEpisode: Boolean,
        val canEnterPictureInPicture: Boolean,
        val isLockedOutByEntitlement: Boolean = false,
    )

    /** The two lists the screen paints. Nothing else may be on the surface. */
    data class Plan(
        val bar: List<Control>,
        val more: List<Control>,
        val autoHideMs: Long = AUTO_HIDE_MS,
    )

    private val BAR_ALWAYS = listOf(
        Control.BACK,
        Control.TITLE,
        Control.PLAY_PAUSE,
        Control.SEEK,
        Control.ELAPSED,
        Control.SKIP_BACK,
        Control.SKIP_FORWARD,
        Control.FULLSCREEN,
    )

    /**
     * The visible surface, and what is behind More.
     *
     * Subtitles appear only when the title has subtitle tracks and audio only when it has more
     * than one track — a button that can only ever say "none" is the fake affordance the spec bans.
     * Quality is on the bar for the same reason the spec puts it there, and disappears with its own
     * list: a title with one band has nothing to switch to.
     *
     * [Inputs.isLockedOutByEntitlement] takes the whole surface down to play/pause plus fullscreen:
     * under a VIP lock that gates this quality there is nothing to seek through yet and nothing to
     * switch, so the honest screen is the prompt, not a bar of controls that all answer "no".
     */
    fun plan(inputs: Inputs): Plan {
        if (inputs.isLockedOutByEntitlement) {
            return Plan(
                bar = listOf(Control.TITLE, Control.PLAY_PAUSE, Control.FULLSCREEN),
                more = emptyList(),
            )
        }
        val bar = BAR_ALWAYS.toMutableList()
        if (inputs.qualityCount > 1) bar += Control.QUALITY
        if (inputs.subtitleCount > 0) bar += Control.SUBTITLES
        if (inputs.audioTrackCount > 1) bar += Control.AUDIO_TRACKS
        bar += Control.MORE
        val more = mutableListOf(
            Control.SPEED,
            Control.SUBTITLE_DELAY,
            Control.LOCK,
            Control.FRAME_BACK,
            Control.FRAME_FORWARD,
            Control.SLEEP_TIMER,
            Control.ASPECT,
            Control.ORIENTATION,
            Control.AUDIO_ONLY,
            Control.STEREO_ONLY,
            Control.CINEMA_MODE,
            Control.SOURCE_LOG,
            Control.OPEN_EXTERNALLY,
        )
        if (inputs.hasNextEpisode) more += Control.NEXT_EPISODE
        if (inputs.canEnterPictureInPicture) more += Control.PICTURE_IN_PICTURE
        return Plan(bar = bar, more = more)
    }
}
