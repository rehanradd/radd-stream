package com.raddstream.app.player

import com.raddstream.app.player.DetailSelection.Scope
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * What the detail screen's two buttons point at. The screen has exactly one Play and one Download
 * now, so this decides the case nobody can demo on a phone: a series opened cold, with nothing
 * tapped, with and without a resume point.
 */
class DetailSelectionTest {

    private val season = listOf(Scope(1, 1), Scope(1, 2), Scope(1, 3), Scope(2, 1))

    /** The two named scopes the rule documents, spelled once. */
    private val FIRST = Scope.FIRST
    private val MOVIE = Scope.MOVIE

    @Test
    fun `a tap wins, and wins over the resume point`() {
        assertEquals(
            Scope(2, 1),
            DetailSelection.resolve(tapped = Scope(2, 1), resume = Scope(1, 3), available = season),
        )
    }

    @Test
    fun `with nothing tapped the resume point is the target`() {
        assertEquals(
            Scope(1, 3),
            DetailSelection.resolve(tapped = null, resume = Scope(1, 3), available = season),
        )
    }

    @Test
    fun `with nothing tapped and nothing half-watched it is the first episode`() {
        // Shuffled input: the rule is S01E01, not "whatever the server listed first".
        val shuffled = listOf(Scope(2, 4), Scope(1, 3), Scope(1, 1), Scope(1, 2))
        assertEquals(FIRST, DetailSelection.resolve(tapped = null, resume = null, available = shuffled))
    }

    @Test
    fun `a resume point in a season this title does not have is not honoured`() {
        // A pointer from another device, or from before a catalog merge, must not aim Play at an
        // episode the ladder cannot serve. Fall through to the first real one.
        assertEquals(
            Scope(1, 1),
            DetailSelection.resolve(tapped = null, resume = Scope(7, 2), available = season),
        )
    }

    @Test
    fun `a tap the title cannot serve leaves the buttons with no target`() {
        assertNull(DetailSelection.resolve(tapped = Scope(9, 9), resume = FIRST, available = season))
    }

    @Test
    fun `a whole-season pack is the default target for its season`() {
        val packed = listOf(Scope(1, 1), Scope(1, null), Scope(2, 1))
        assertEquals(
            Scope(1, null),
            DetailSelection.resolve(tapped = null, resume = null, available = packed),
        )
    }

    @Test
    fun `a movie needs no tap`() {
        assertEquals(MOVIE, DetailSelection.resolve(tapped = null, resume = null, available = listOf(MOVIE)))
    }

    @Test
    fun `an empty title has no target`() {
        assertNull(DetailSelection.resolve(tapped = null, resume = null, available = emptyList()))
        assertFalse(DetailSelection.canAct(selection = null, ladderEmpty = true))
    }

    @Test
    fun `tapping the row that is already selected keeps it selected`() {
        // Toggling off would leave two buttons pointing at nothing, right after the viewer tapped.
        assertEquals(Scope(1, 2), DetailSelection.onTap(current = Scope(1, 2), tapped = Scope(1, 2)))
    }

    @Test
    fun `the buttons act on a selection with something to play`() {
        assertTrue(DetailSelection.canAct(FIRST, ladderEmpty = false))
        assertFalse("a scope with no ladder yet is a fake affordance", DetailSelection.canAct(FIRST, ladderEmpty = true))
    }

    @Test
    fun `one row can claim to be selected only if the buttons agree`() {
        assertTrue(DetailSelection.isSelected(FIRST, FIRST))
        assertFalse(DetailSelection.isSelected(FIRST, Scope(1, 2)))
        assertFalse(DetailSelection.isSelected(null, FIRST))
    }

    /**
     * The screen has no else-branch on the two buttons today, so a title with nothing selectable
     * shows no Play / Download AND no reason — which reads as a broken page. The explanation and the
     * buttons are mutually exclusive, both keyed on the same [DetailSelection.canAct] predicate, so
     * the rule that decides "say nothing" must never be able to disagree with "show the buttons".
     * This pins both no-action cases: a title with no target at all, and a target whose ladder the
     * server has not filled yet.
     */
    @Test
    fun `the no-ladder explanation shows exactly when the buttons cannot act`() {
        // Nothing selectable → the screen paints the plain-word notice, never a disabled button.
        assertFalse(
            "a title with no target must fall to the explanation branch",
            DetailSelection.canAct(selection = null, ladderEmpty = false),
        )
        // A real target but an empty ladder (the server has no picture for it) → same.
        assertFalse(
            "a scope the server cannot picture yet must fall to the explanation branch",
            DetailSelection.canAct(FIRST, ladderEmpty = true),
        )
        // Only when there is both a target and a picture do the buttons act and the notice stay away.
        assertTrue(
            "with a target and a ladder the buttons act, so no explanation is painted",
            DetailSelection.canAct(FIRST, ladderEmpty = false),
        )
    }
}
