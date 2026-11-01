package com.raddstream.app.player

/**
 * The one step DOWN a viewer can take when the picture they are on refuses.
 *
 * The player's plain-word error card has exactly two buttons, and the second is the owner's:
 * "Try lower quality". That is a band decision, and this app already owns one owner of band
 * decisions — [QualityChoice] (first-run default, which bands a title has, nearest lower then
 * nearest higher, what a band word means). So this file does not rank bands, does not know the
 * height list and does not fold a synonym: it asks [QualityChoice.fallbackFrom] for the band it
 * would move to when the current band is taken away, and keeps the answer only if that move is
 * genuinely LOWER.
 *
 * Why the "only if LOWER" half matters: the same call asked with the current band removed will,
 * when nothing lower exists, offer the nearest HIGHER band instead. A "Try lower quality" button
 * that stepped the picture UP would be the one control on this screen that does the opposite of
 * what its own label says. So the higher answer is refused here, and the button simply is not
 * painted when [nextLower] answers null — no dead affordance, no silent jump.
 */
object LowerQualityStep {

    /**
     * The band to move to from [current], out of the bands this scope actually has ([present]),
     * or null when there is nowhere lower to go.
     *
     * The word returned is the one the ladder itself carried, not a folded spelling, so a caller
     * can find the rung by the same equality [QualityLadder.optionFor] uses. `null` [current] is
     * null: with no picture on screen there is no step down from it, and inventing one would be a
     * guess about a band the viewer never chose.
     */
    fun nextLower(current: String?, present: List<String>): String? {
        val wanted = QualityChoice.canonical(current) ?: return null
        val rest = present.filterNot { QualityChoice.canonical(it) == wanted }
        if (rest.isEmpty()) return null
        val plan = QualityChoice.fallbackFrom(wanted, rest)
        if (plan.step != QualityChoice.Step.LOWER) return null
        val band = plan.band ?: return null
        return rest.firstOrNull { QualityChoice.canonical(it) == band }
    }

    /** Whether the "Try lower quality" button may be painted at all. */
    fun available(current: String?, present: List<String>): Boolean = nextLower(current, present) != null
}
