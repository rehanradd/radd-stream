package com.raddstream.app.player

import androidx.media3.common.Player
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The start budget (research rule 4.1): under two seconds the picture is the narration, past
 * two the viewer deserves a hint, past eight something to press, past thirty the attempt
 * itself is the problem. These are the policy's own boundaries, proved here with a fake
 * clock — no player, no surface, no device.
 */
class StartDeadlineTest {

    @Test
    fun `a fresh start is silent`() {
        assertEquals(StartDeadlineStage.SILENT, StartDeadline.stage(0, firstFrame = false))
        assertEquals(StartDeadlineStage.SILENT, StartDeadline.stage(1_999, firstFrame = false))
    }

    @Test
    fun `two seconds earns the soft hint`() {
        assertEquals(StartDeadlineStage.HINT, StartDeadline.stage(2_000, firstFrame = false))
        assertEquals(StartDeadlineStage.HINT, StartDeadline.stage(7_999, firstFrame = false))
    }

    @Test
    fun `eight seconds earns the actions`() {
        assertEquals(StartDeadlineStage.ACTIONS, StartDeadline.stage(8_000, firstFrame = false))
        assertEquals(StartDeadlineStage.ACTIONS, StartDeadline.stage(29_999, firstFrame = false))
    }

    @Test
    fun `thirty seconds with no frame gives up`() {
        assertEquals(StartDeadlineStage.GIVE_UP, StartDeadline.stage(30_000, firstFrame = false))
        assertEquals(StartDeadlineStage.GIVE_UP, StartDeadline.stage(120_000, firstFrame = false))
    }

    @Test
    fun `a first frame disarms the deadline at any age`() {
        assertEquals(StartDeadlineStage.SILENT, StartDeadline.stage(60_000, firstFrame = true))
        assertEquals(StartDeadlineStage.SILENT, StartDeadline.stage(0, firstFrame = true))
    }

    @Test
    fun `only a ready player counts as a first frame`() {
        // Session 99: the ticker used to disarm on a known duration, and a
        // stalled copy knows its duration from the playlist or file header
        // while the picture is still black — the deadline never fired and
        // the player buffered forever. READY is the only state that proves
        // the pipeline can render; buffering, idle and ended do not.
        assertFalse(StartDeadline.hasFirstFrame(Player.STATE_IDLE))
        assertFalse(StartDeadline.hasFirstFrame(Player.STATE_BUFFERING))
        assertFalse(StartDeadline.hasFirstFrame(Player.STATE_ENDED))
        assertTrue(StartDeadline.hasFirstFrame(Player.STATE_READY))
    }

    @Test
    fun `the stage the screen shows follows the phase and the elapsed time`() {
        val starting = PlayerUiState(connected = true, startElapsedMs = 5_000)
        assertEquals(StartDeadlineStage.HINT, starting.startDeadlineStage)

        val acting = PlayerUiState(connected = true, startElapsedMs = 10_000)
        assertEquals(StartDeadlineStage.ACTIONS, acting.startDeadlineStage)

        val late = PlayerUiState(connected = true, startElapsedMs = 45_000)
        assertEquals(StartDeadlineStage.GIVE_UP, late.startDeadlineStage)

        val playing = PlayerUiState(connected = true, isPlaying = true, startElapsedMs = 45_000)
        assertEquals(StartDeadlineStage.SILENT, playing.startDeadlineStage)

        val givenUp = PlayerUiState(connected = true, deadlineGiveUp = true, startElapsedMs = 45_000)
        assertEquals(StartDeadlineStage.GIVE_UP, givenUp.startDeadlineStage)
    }

    @Test
    fun `try another print walks the ranks after the one being tried`() {
        val bundle = PlaybackBundle(
            renditions = listOf(
                PlaybackRendition(rank = 1, playback = PlaybackInfo(playUrl = "https://example.invalid/h1", streamId = "h1")),
                PlaybackRendition(rank = 2, playback = PlaybackInfo(playUrl = "https://example.invalid/h2", streamId = "h2")),
                PlaybackRendition(rank = 3, playback = PlaybackInfo(playUrl = "https://example.invalid/h3", streamId = "h3")),
            ),
        )
        val first = bundle.renditions[0]
        val state = PlayerUiState(bundle = bundle, activeRendition = first)
        assertEquals("h2", state.nextPrintHandle)
        assertTrue(state.canTryAnotherPrint)

        val last = PlayerUiState(bundle = bundle, activeRendition = bundle.renditions[2])
        assertNull("the last rank has nothing ahead of it", last.nextPrintHandle)
    }

    @Test
    fun `a single print falls back to its own runner-ups`() {
        val bundle = PlaybackBundle(
            renditions = listOf(
                PlaybackRendition(
                    rank = 1,
                    playback = PlaybackInfo(playUrl = "https://example.invalid/h1", streamId = "h1", backupStreamIds = listOf("b1", "b2")),
                ),
            ),
        )
        val state = PlayerUiState(bundle = bundle, activeRendition = bundle.renditions[0])
        assertEquals("b1", state.nextPrintHandle)
    }

    @Test
    fun `no other print anywhere means no try-another button`() {
        val bundle = PlaybackBundle(
            renditions = listOf(
                PlaybackRendition(rank = 1, playback = PlaybackInfo(playUrl = "https://example.invalid/h1", streamId = "h1")),
            ),
        )
        val state = PlayerUiState(bundle = bundle, activeRendition = bundle.renditions[0])
        assertNull(state.nextPrintHandle)
        assertEquals(false, state.canTryAnotherPrint)

        val empty = PlayerUiState()
        assertNull(empty.nextPrintHandle)
    }

    @Test
    fun `the print sheet timing reads as seconds with one decimal`() {
        assertEquals("1.4 s", StartDeadline.formatSeconds(1_400))
        assertEquals("0.0 s", StartDeadline.formatSeconds(0))
        assertEquals("30.0 s", StartDeadline.formatSeconds(30_000))
    }
}
