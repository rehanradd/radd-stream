package com.raddstream.app.player

import com.raddstream.app.network.models.Playability
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Session 121 (P-6): a viewer cannot act on an ExoPlayer constant name. The failover
 * machine translates the raw `ERROR_CODE_…` summary into human words before the
 * give-up card or the failover log shows it; the raw code stays in logcat, written
 * by `PlaybackService` before it calls `onFailure`.
 */
class FailoverHumanMessageTest {

    @Test
    fun `known ExoPlayer codes become human sentences`() {
        assertEquals(
            "The connection timed out. Check your connection and try again.",
            humanizeErrorSummary("ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT Read timed out"),
        )
        assertEquals(
            "Could not reach the server. Check your connection and try again.",
            humanizeErrorSummary("ERROR_CODE_IO_NETWORK_CONNECTION_FAILED Connection refused"),
        )
        assertEquals(
            "The server sent something that is not a video.",
            humanizeErrorSummary("ERROR_CODE_IO_INVALID_HTTP_CONTENT_TYPE text/html"),
        )
        assertEquals(
            "This copy is no longer on the server.",
            humanizeErrorSummary("ERROR_CODE_IO_FILE_NOT_FOUND 404"),
        )
        assertEquals(
            "This device could not play this video.",
            humanizeErrorSummary("ERROR_CODE_DECODER_INIT_FAILED something"),
        )
    }

    @Test
    fun `already-human messages pass through untouched`() {
        assertEquals("link expired before load", humanizeErrorSummary("link expired before load"))
        assertEquals(
            "Reached max_ranks=3 without stable playback",
            humanizeErrorSummary("Reached max_ranks=3 without stable playback"),
        )
        assertEquals(
            "No directly playable link in this bundle",
            humanizeErrorSummary("No directly playable link in this bundle"),
        )
        assertEquals("Playback stopped", humanizeErrorSummary("Playback stopped"))
    }

    @Test
    fun `an unknown code still never shows the code`() {
        val human = humanizeErrorSummary("ERROR_CODE_SOMETHING_NEW unexpected")
        assertEquals("Playback failed. Retry, or try another version.", human)
        assertFalse(human.contains("ERROR_CODE_"))
    }

    @Test
    fun `the handoff a viewer sees carries the human sentence, not the code`() {
        val machine = FailoverStateMachine(
            listOf(
                PlaybackRendition(
                    rank = 1,
                    releaseId = 7,
                    print = PrintInfo(label = "A Movie", resolution = "1080p"),
                    playback = PlaybackInfo(
                        playUrl = "http://127.0.0.1:8080/api/v1/stream?id=h-a",
                        streamId = "h-a",
                        label = "Fast direct",
                        kind = "direct",
                        playabilityWire = Playability.STREAM.wire,
                        resumable = true,
                    ),
                ),
            ),
            PlaybackFailurePolicy(retrySame = 0, maxRanks = 3, backoffMs = 0),
        )
        // The machine starts with no active rendition (activeIndex = -1) until
        // selectInitial() picks one — without it onFailure takes the
        // no-current path and the Handoff carries no record at all.
        assertEquals(0, machine.selectInitial())
        val decision = machine.onFailure("ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT Read timed out")
        assertTrue(decision is FailoverDecision.Handoff)
        decision as FailoverDecision.Handoff
        assertEquals(
            "The connection timed out. Check your connection and try again.",
            decision.detail,
        )
        assertEquals(
            "The connection timed out. Check your connection and try again.",
            decision.record?.reason,
        )
    }
}
