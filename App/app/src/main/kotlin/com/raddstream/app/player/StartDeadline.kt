package com.raddstream.app.player

import androidx.media3.common.Player

/**
 * The four moments of a start attempt, in the order a viewer meets them.
 *
 * A start that lands in under two seconds needs no narration at all — the picture is the
 * narration. Past two seconds the viewer deserves to know the wait is normal; past eight
 * they deserve something to press; past thirty the attempt itself is the problem, and the
 * player stops pretending otherwise.
 */
enum class StartDeadlineStage {
    /** Under two seconds, or a frame already on screen: say nothing. */
    SILENT,

    /** Two to eight seconds: one extra line, no panic. */
    HINT,

    /** Eight to thirty seconds: Retry and Try another print. */
    ACTIONS,

    /** Thirty seconds with no frame: stop trying, hand the viewer the choice. */
    GIVE_UP,
}

/**
 * The start budget (research rule 4.1), as a pure policy: elapsed milliseconds since the
 * load was requested, and whether a first frame has rendered. No clock, no thread, no
 * player — the ViewModel feeds it the elapsed time its ticker already measures, and the
 * screen reads the stage off [PlayerUiState.startDeadlineStage].
 *
 * The numbers are the plan's defaults (D5: 30 s): our own live probe measured ~6 s for a
 * stream resolve, so thirty seconds is generous, not tight. A first frame disarms the
 * deadline at any age — a start that lands late is a start, not a failure.
 */
object StartDeadline {

    /** The soft hint appears here: two seconds, the research abandonment knee. */
    const val HINT_AFTER_MS = 2_000L

    /** The actions appear here: eight seconds, long enough that Retry is honest. */
    const val ACTIONS_AFTER_MS = 8_000L

    /** The hard give-up: thirty seconds with no frame. */
    const val GIVE_UP_AFTER_MS = 30_000L

    /**
     * The service-side stall watchdog (2026-11-12 rework): eight seconds with
     * no first frame and the player fails the attempt over to the next
     * candidate on its own — the same moment the screen starts offering
     * Retry / Try another print. A load that errors fails over at once
     * through the player-error path; a load that never errors and never
     * renders — a hung resolve, a stalled CDN, a playlist that never
     * arrives — used to sit on the "Warming the link" notice until the
     * thirty-second card, and nothing ever advanced it. Eight seconds is
     * the audit #1 budget: the warm resolve answers in ~0.02 s and a cold
     * one in 5–11 s, so a first frame that has not arrived by eight
     * seconds is a dead attempt, not a slow one — and the retry-same
     * budget still gives the same rung one more chance before the rank
     * moves. Must stay below [GIVE_UP_AFTER_MS]: the watchdog is the
     * automatic failover, the thirty-second card is the last resort.
     */
    const val START_WATCHDOG_MS = 8_000L

    fun stage(elapsedMs: Long, firstFrame: Boolean): StartDeadlineStage = when {
        firstFrame -> StartDeadlineStage.SILENT
        elapsedMs < HINT_AFTER_MS -> StartDeadlineStage.SILENT
        elapsedMs < ACTIONS_AFTER_MS -> StartDeadlineStage.HINT
        elapsedMs < GIVE_UP_AFTER_MS -> StartDeadlineStage.ACTIONS
        else -> StartDeadlineStage.GIVE_UP
    }

    /**
     * What counts as a first frame, from the player's own state — READY only.
     * A known duration is NOT a frame: ExoPlayer learns the duration from the
     * playlist or the file header while the picture is still black, so a
     * stalled copy can sit at a known duration for minutes and never render.
     * The ticker used to disarm the deadline on `isPlaying || duration > 0`,
     * which is how a dead copy buffered forever with no error (Pushpa 2, APK
     * 270 retest: the playlist loaded, the duration was known, the screen
     * stayed black with the spinner until the session expired). READY means
     * the pipeline can render; a paused player still reaches READY, so
     * pausing before the first frame does not trip the deadline either.
     */
    fun hasFirstFrame(playbackState: Int): Boolean =
        playbackState == Player.STATE_READY

    /**
     * The print sheet's proof of the budget — "1.4 s", one decimal, never negative. The
     * owner reads the real start off his own phone from this line.
     */
    fun formatSeconds(elapsedMs: Long): String =
        "%.1f s".format((elapsedMs / 1_000.0).coerceAtLeast(0.0))
}
