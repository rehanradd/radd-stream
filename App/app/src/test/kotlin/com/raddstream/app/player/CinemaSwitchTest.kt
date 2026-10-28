package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Ghost mode is the one display preference a server can veto: `feature_flags.pure_cinema` off
 * must mean this app never hides its controls, whatever the device has stored.
 *
 * The rule lives in [PlayerUiState.pureCinema] as a derivation rather than a rewrite of
 * [PlayerUiState.viewMode], and these tests pin the difference: the viewer's own choice is
 * still there when the operator switches the feature back on.
 */
class CinemaSwitchTest {

    @Test
    fun `a viewer who chose cinema gets cinema while the board allows it`() {
        val state = PlayerUiState(viewMode = ViewMode.PURE_CINEMA, pureCinemaAllowed = true)
        assertTrue(state.pureCinema)
    }

    @Test
    fun `the operators switch outranks a stored cinema choice`() {
        val state = PlayerUiState(viewMode = ViewMode.PURE_CINEMA, pureCinemaAllowed = false)
        assertFalse("a switched-off frame must still show its controls", state.pureCinema)
    }

    @Test
    fun `the refused choice is kept, not overwritten`() {
        val refused = PlayerUiState(viewMode = ViewMode.PURE_CINEMA, pureCinemaAllowed = false)
        assertEquals(
            "sanitising viewMode would silently discard what the viewer last asked for",
            ViewMode.PURE_CINEMA,
            refused.viewMode,
        )
        assertTrue(refused.copy(pureCinemaAllowed = true).pureCinema)
    }

    @Test
    fun `full chrome is full chrome under both answers`() {
        assertFalse(PlayerUiState(viewMode = ViewMode.STANDARD).pureCinema)
        assertFalse(PlayerUiState(viewMode = ViewMode.STANDARD, pureCinemaAllowed = false).pureCinema)
    }

    @Test
    fun `a board that has not answered yet allows the mode`() {
        assertTrue(PlayerUiState().pureCinemaAllowed)
    }
}
