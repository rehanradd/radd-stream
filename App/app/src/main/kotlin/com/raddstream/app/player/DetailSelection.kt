package com.raddstream.app.player

/**
 * Which one thing the detail screen's two buttons act on.
 *
 * The spec's core rule is "2 buttons only on detail page": one Play, one Download, and an episode
 * tap only SELECTS — the buttons then act on the selection. Before this file the answer was
 * structural rather than decided: every rung card, every episode row and every print card carried
 * its own play and download icons, so the screen had roughly forty buttons and no notion of a
 * selection at all. Once the screen has exactly two, SOMETHING has to hold "what they point at",
 * including before the viewer taps anything. That something is a rule with three branches
 * (tapped, else resume, else the first episode), so it lives here where a test can pin it instead
 * of in a composable where only a phone could.
 *
 * It works in [Scope]s — a season and an episode number, no Android and no wire types — because
 * the ladder is already keyed that way ([QualityLadder.forNumberedScope]) and the resume pointer
 * arrives from [com.raddstream.app.player.PlayerSessionStore] as the same two numbers. The screen
 * maps its rows into Scopes and hands them over.
 */
object DetailSelection {

    /**
     * The scope of one play/download target. Both halves null is a MOVIE: one work, no episode
     * grid, and the two buttons point at the work itself. One half null on a series is a season
     * pack, which is a real thing the catalog sends and must survive round-tripping.
     */
    data class Scope(val season: Int?, val episode: Int?) {
        companion object {
            /** A work with no episode grid. */
            val MOVIE = Scope(null, null)

            /** S01E01 in the numbering every catalog row starts from. */
            val FIRST = Scope(1, 1)
        }
    }

    /**
     * What the two buttons point at, given what has been tapped, what the viewer left half-watched
     * and what this title actually has.
     *
     * Order is the spec's: a tap wins, because that is the viewer speaking; then the resume point,
     * because "Continue watching" is the reason the page exists; then the first episode, because
     * "Play" on a series with nothing tapped has to land somewhere and S01E01 is the only honest
     * answer. A candidate is only honoured when it is in [available] — pointing Play at an episode
     * the ladder cannot serve is how a green button ends up producing an error toast.
     *
     * An empty [available] answers `null`, and the screen then disables both buttons rather than
     * pointing them at nothing.
     */
    fun resolve(tapped: Scope?, resume: Scope?, available: List<Scope>): Scope? {
        tapped?.let { return if (it in available) it else null }
        resume?.let { if (it in available) return it }
        return available.minWithOrNull(SCOPE_ORDER)
    }

    /**
     * A tap on an episode row selects it — and selecting the row that is already selected keeps it
     * selected. Toggling OFF would leave the two buttons pointing at nothing after a tap, which is
     * the opposite of what a tap is for.
     */
    fun onTap(current: Scope?, tapped: Scope): Scope = tapped

    /**
     * Whether the two buttons may act. They need a selection AND that selection needs a ladder:
     * an empty [ladderEmpty] means the server has no picture for this scope yet, and a button that
     * cannot do anything is the "fake affordance" the spec forbids. A null selection means the
     * title has nothing selectable at all.
     */
    fun canAct(selection: Scope?, ladderEmpty: Boolean): Boolean = selection != null && !ladderEmpty

    /**
     * Whether a row is the one the buttons are pointing at. Kept here so a row's highlight and the
     * buttons' target cannot be computed twice and disagree.
     */
    fun isSelected(selection: Scope?, row: Scope): Boolean = selection == row

    /**
     * Lowest season first, then lowest episode; a null episode sorts before a numbered one so a
     * whole-season pack beats its own episode list as the default target (a pack IS the season).
     * A null season — a movie — is the smallest of all, which is why an all-movie list resolves to
     * [Scope.MOVIE] without a special case.
     */
    private val SCOPE_ORDER: Comparator<Scope> =
        compareBy({ it.season ?: Int.MIN_VALUE }, { it.episode ?: Int.MIN_VALUE })
}
