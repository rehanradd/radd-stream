package com.raddstream.app.player

import com.raddstream.app.network.models.Playability
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Session 155 (S2): a start failure must never retry the SAME rendition.
 *
 * The S2 log shows 22 presses of our redirector in 2.5 min and no frame:
 * each retry of the same unplayable file re-pays the redirector's 6-12 s
 * live resolve, so the 30 s start budget is spent re-resolving one copy
 * instead of trying a different one. Before the first frame, a failure
 * hops to a backup handle / the next rank at once. After the first frame
 * the policy's retry_same still applies — a mid-playback blip is worth
 * one same-file retry.
 */
class RenditionFailoverStartTest {

    private fun rung(
        rank: Int,
        handle: String,
        backups: List<String> = emptyList(),
        playability: Playability = Playability.STREAM,
        url: String? = "http://127.0.0.1:8080/api/v1/stream?id=$handle",
    ) = PlaybackRendition(
        rank = rank,
        releaseId = 7,
        print = PrintInfo(label = "Title"),
        playback = PlaybackInfo(
            playUrl = url,
            streamId = handle,
            label = "Fast direct",
            kind = "direct",
            playabilityWire = playability.wire,
            resumable = true,
            backupStreamIds = backups,
        ),
    )

    private fun machine(vararg renditions: PlaybackRendition) = FailoverStateMachine(
        renditions.toList(), PlaybackFailurePolicy(retrySame = 1, maxRanks = 3, backoffMs = 500),
    )

    @Test
    fun `a start failure hops to the backup at once, never retries the same rendition`() {
        val subject = machine(
            rung(1, "h-a", backups = listOf("b-a1", "b-a2")),
            rung(2, "h-b"),
        )
        assertEquals(0, subject.selectInitial())

        val hop = subject.onFailure(
            "ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT ...",
            beforeFirstFrame = true,
        )
        hop as FailoverDecision.AdvanceBackup
        assertEquals(0, hop.index)
        assertEquals("b-a1", hop.streamId)
        assertEquals("http://127.0.0.1:8080/api/v1/stream?id=b-a1", hop.playUrl)
    }

    @Test
    fun `a start failure with no backup advances to the next rank at once`() {
        val subject = machine(rung(1, "h-a"), rung(2, "h-b"))
        assertEquals(0, subject.selectInitial())

        val advance = subject.onFailure(
            "ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT ...",
            beforeFirstFrame = true,
        )
        advance as FailoverDecision.Advance
        assertEquals(1, advance.index)
    }

    @Test
    fun `a start failure on the last rank hands off, never retries`() {
        val subject = machine(rung(1, "h-a"))
        assertEquals(0, subject.selectInitial())

        val decision = subject.onFailure(
            "ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT ...",
            beforeFirstFrame = true,
        )
        decision as FailoverDecision.Handoff
        assertEquals(HandoffWhy.NO_CANDIDATE_LEFT, decision.why)
    }

    @Test
    fun `a failure after the first frame still retries the same rendition`() {
        val subject = machine(rung(1, "h-a", backups = listOf("b-a1")), rung(2, "h-b"))
        assertEquals(0, subject.selectInitial())

        assertTrue(subject.onFailure("HTTP 403", beforeFirstFrame = false) is FailoverDecision.RetrySame)
    }

    @Test
    fun `a start failure consumes the same-rendition retry, so a later failure hops on`() {
        val subject = machine(
            rung(1, "h-a", backups = listOf("b-a1", "b-a2")),
            rung(2, "h-b"),
        )
        assertEquals(0, subject.selectInitial())

        // Start failure: hops to b-a1 at once (no same-rendition retry).
        val first = subject.onFailure("timeout", beforeFirstFrame = true)
        assertTrue(first is FailoverDecision.AdvanceBackup)
        assertEquals("b-a1", (first as FailoverDecision.AdvanceBackup).streamId)

        // The backup then fails mid-playback: the same-rendition retry was
        // already spent by the start failure, so it hops to b-a2, not RetrySame.
        val second = subject.onFailure("timeout", beforeFirstFrame = false)
        assertTrue(second is FailoverDecision.AdvanceBackup)
        assertEquals("b-a2", (second as FailoverDecision.AdvanceBackup).streamId)
    }
}
