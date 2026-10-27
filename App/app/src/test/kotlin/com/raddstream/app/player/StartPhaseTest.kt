package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The player used to paint a black frame from the moment its route opened until Media3
 * decoded a first picture, with nothing on screen saying why. These rules decide that
 * narration from fields the listener already publishes, so they are testable without a
 * player, a surface, or a device.
 */
class StartPhaseTest {

    @Test
    fun `a player with no controller yet says it is connecting`() {
        assertEquals(StartPhase.CONNECTING_PLAYER, PlayerUiState().startPhase)
    }

    @Test
    fun `a connected player with nothing loaded yet says it is starting`() {
        val state = PlayerUiState(connected = true)
        assertEquals(StartPhase.STARTING, state.startPhase)
    }

    @Test
    fun `a frame on screen ends the narration`() {
        val playing = PlayerUiState(connected = true, isPlaying = true, durationMs = 90_000)
        assertEquals(StartPhase.NONE, playing.startPhase)
    }

    @Test
    fun `a stall inside a loaded file is buffering, not a start`() {
        val stalled = PlayerUiState(
            connected = true,
            isPlaying = false,
            isBuffering = true,
            durationMs = 90_000,
            positionMs = 42_000,
        )
        assertEquals(StartPhase.NONE, stalled.startPhase)
    }

    @Test
    fun `the viewers own pause is never described as starting`() {
        val paused = PlayerUiState(connected = true, durationMs = 90_000, positionMs = 42_000)
        assertEquals(StartPhase.NONE, paused.startPhase)
    }

    @Test
    fun `a card that already explains itself outranks the notice`() {
        val givenUp = PlayerUiState(
            connected = true,
            giveUp = "Every option failed" to HandoffWhy.NO_CANDIDATE_LEFT,
        )
        assertEquals(StartPhase.NONE, givenUp.startPhase)

        val serviceDead = PlayerUiState(connectionError = "Playback service unavailable")
        assertEquals(StartPhase.NONE, serviceDead.startPhase)

        val resumeAsked = PlayerUiState(connected = true, resumeOfferMs = 500_000)
        assertEquals(StartPhase.NONE, resumeAsked.startPhase)
    }

    @Test
    fun `an ended title is not waiting for a picture`() {
        val ended = PlayerUiState(connected = true, isEnded = true, durationMs = 90_000)
        assertEquals(StartPhase.NONE, ended.startPhase)
    }

    @Test
    fun `every phase the screen may show has words to say`() {
        val spoken = StartPhase.entries.filter { it != StartPhase.NONE }
        assertTrue("a notice the viewer cannot read is not a notice", spoken.isNotEmpty())
        spoken.forEach { phase ->
            assertTrue("${phase.name} carries no label", phase.label.isNotBlank())
        }
    }
}
