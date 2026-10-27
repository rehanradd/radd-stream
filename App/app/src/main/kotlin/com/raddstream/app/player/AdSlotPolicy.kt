package com.raddstream.app.player

/**
 * The only two moments a free-tier sponsor break may be raised
 * (`docs/OPENROUTER_PURE_CODE_AUDIT.md` §3, `docs/MASTER_ADMIN_MONETIZATION_SPEC.md` §6):
 * before playback starts, and between episodes. There is deliberately no mid-roll value —
 * a break during a running movie is not a placement choice this app can make.
 */
enum class AdSlot {
    NONE,
    PRE_ROLL,
    BETWEEN_EPISODES,
}

/** The facts the policy reads. All of them already exist in [PlayerUiState] and the bundle. */
data class AdSlotState(
    val isSeriesEpisode: Boolean,
    val isEnded: Boolean,
    val isPlaying: Boolean,
    val positionMs: Long,
    val durationMs: Long,
    /** Whether a successor exists; a break that leads nowhere is worse than no break. */
    val hasNextEpisode: Boolean,
)

/**
 * Pure guard between "a sponsor wants a slot" and "the viewer sees it".
 *
 * The rule is structural, not a matter of callers behaving: pre-roll requires that playback
 * has not started (nothing is interrupted), and the between-episodes slot requires the file
 * to have actually ended AND a successor to exist (including a packed file's in-file
 * successor, which the service seeks within). A movie that has ended has no between-episodes
 * slot, so a finished film is never followed by a break.
 *
 * The app currently ships no ad SDK or creative, so nothing raises a break on its own. When
 * one is wired, it must ask [decide] first; [AdSlot.NONE] is the only honest answer for a
 * running title.
 */
object AdSlotPolicy {

    /** A start is still "before playback" only within this window after the file loads. */
    const val PRE_ROLL_GRACE_MS = 2_000L

    fun decide(state: AdSlotState): AdSlot {
        if (state.isEnded) {
            return if (state.isSeriesEpisode && state.hasNextEpisode) {
                AdSlot.BETWEEN_EPISODES
            } else {
                AdSlot.NONE
            }
        }
        // A title that is actually running is never interrupted, at any position.
        if (state.isPlaying) return AdSlot.NONE
        if (state.durationMs <= 0L) return AdSlot.NONE
        return if (state.positionMs.coerceAtLeast(0L) <= PRE_ROLL_GRACE_MS) {
            AdSlot.PRE_ROLL
        } else {
            AdSlot.NONE
        }
    }

    /** The one-line invariant a caller can assert in a test or an ad SDK callback. */
    fun isLegalMidPlayback(slot: AdSlot, positionMs: Long, durationMs: Long): Boolean =
        slot == AdSlot.NONE || positionMs <= 0L || (durationMs > 0L && positionMs >= durationMs)
}
