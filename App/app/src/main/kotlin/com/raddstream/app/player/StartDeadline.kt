package com.raddstream.app.player

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

    fun stage(elapsedMs: Long, firstFrame: Boolean): StartDeadlineStage = when {
        firstFrame -> StartDeadlineStage.SILENT
        elapsedMs < HINT_AFTER_MS -> StartDeadlineStage.SILENT
        elapsedMs < ACTIONS_AFTER_MS -> StartDeadlineStage.HINT
        elapsedMs < GIVE_UP_AFTER_MS -> StartDeadlineStage.ACTIONS
        else -> StartDeadlineStage.GIVE_UP
    }

    /**
     * The print sheet's proof of the budget — "1.4 s", one decimal, never negative. The
     * owner reads the real start off his own phone from this line.
     */
    fun formatSeconds(elapsedMs: Long): String =
        "%.1f s".format((elapsedMs / 1_000.0).coerceAtLeast(0.0))
}
