package com.raddstream.app.player

import com.raddstream.app.network.models.Playability
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Mentor method #1, client side: a free CDN that answers 403 must cost the viewer
 * nothing. The rung it was watching has runner-ups of the SAME quality, so the
 * player hops to one at the same position and says nothing — only the auditable
 * trail records it, and only a rung with no runner-up left changes quality.
 */
class SilentFailoverTest {

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
    fun `an expired handle hands off at once, never retries or hops`() {
        // NAV-4 (Session 126): a rotted handle will not heal on a second try, and a
        // silent hop onto a runner-up of the same rotted handle is the same failure
        // wearing a different address — so the machine hands off as EXPIRED_LINK
        // immediately, with its retry budget untouched.
        val subject = machine(
            rung(1, "h-a", backups = listOf("b-a1", "b-a2")),
            rung(2, "h-b"),
        )
        assertEquals(0, subject.selectInitial())
        val decision = subject.onFailure("link expired before load", isExpiry = true)
        decision as FailoverDecision.Handoff
        assertEquals(HandoffWhy.EXPIRED_LINK, decision.why)
    }

    @Test
    fun `an expiry hands off as expired even after the retry budget is spent`() {
        val subject = machine(rung(1, "h-a"), rung(2, "h-b"))
        assertEquals(0, subject.selectInitial())
        assertTrue(subject.onFailure("HTTP 403") is FailoverDecision.RetrySame)
        val decision = subject.onFailure("link expired before load", isExpiry = true)
        decision as FailoverDecision.Handoff
        assertEquals(HandoffWhy.EXPIRED_LINK, decision.why)
    }

    @Test
    fun `a rung hops to its own runner-up before any quality changes`() {
        val subject = machine(
            rung(1, "h-a", backups = listOf("b-a1", "b-a2")),
            rung(2, "h-b"),
        )
        assertEquals(0, subject.selectInitial())
        assertTrue(subject.onFailure("HTTP 403") is FailoverDecision.RetrySame)

        val hop = subject.onFailure("HTTP 403")
        hop as FailoverDecision.AdvanceBackup
        assertEquals(0, hop.index)
        assertEquals("b-a1", hop.streamId)
        assertEquals("http://127.0.0.1:8080/api/v1/stream?id=b-a1", hop.playUrl)

        val second = subject.onFailure("HTTP 403")
        second as FailoverDecision.AdvanceBackup
        assertEquals("b-a2", second.streamId)

        // Runner-ups exhausted: only now does the ladder step down a rung.
        val third = subject.onFailure("HTTP 403")
        third as FailoverDecision.Advance
        assertEquals(1, third.index)
    }

    @Test
    fun `a silent hop never burns a rank and never announces a new rung`() {
        val subject = machine(rung(1, "h-a", backups = listOf("b-a1")), rung(2, "h-b"))
        subject.selectInitial()
        subject.onFailure("HTTP 403") // retry_same
        val hop = subject.onFailure("HTTP 403")
        assertTrue(hop is FailoverDecision.AdvanceBackup)
        // The rung is still active index 0, so the "settled on" chip must not change.
        assertEquals(0, subject.activeIndex)
        assertTrue(subject.log.none { it.action.startsWith("died → failover") })
        assertTrue(subject.log.last().action.contains("hop"))
    }

    @Test
    fun `a rung with no runner-ups behaves exactly as it did before`() {
        val subject = machine(rung(1, "h-a"), rung(2, "h-b"))
        subject.selectInitial()
        subject.onFailure("HTTP 504")
        assertTrue(subject.onFailure("HTTP 504") is FailoverDecision.Advance)
    }

    @Test
    fun `the hop only ever rewrites our own redirector`() {
        assertEquals(
            // Only our own handle is swapped: an expiry or cache-buster riding on the
            // redirector URL belongs to the request, not to the copy, so it stays.
            "https://our.box/api/v1/stream?id=zz&x=1",
            streamUrlForHandle("https://our.box/api/v1/stream?id=aa&x=1", "zz"),
        )
        assertNull(streamUrlForHandle(null, "zz"))
        assertNull(streamUrlForHandle("https://our.box/api/v1/stream", "zz"))
        assertNull(streamUrlForHandle("https://hoster.example/file.mp4", "zz"))
        assertNull(streamUrlForHandle("https://our.box/api/v1/stream?id=aa", " "))
        // A handle is base64 noise: a `+` must stay data, never become a query separator.
        val encoded = streamUrlForHandle("https://our.box/api/v1/stream?id=aa", "a+b=c")
        assertNotNull(encoded)
        assertTrue(encoded?.endsWith("id=a%2Bb%3Dc") == true)
    }

    @Test
    fun `a keep-only rung is never given a silent hop`() {
        val subject = machine(
            rung(1, "h-a", playability = Playability.DOWNLOAD,
                url = "http://127.0.0.1:8080/api/v1/stream?id=h-a"),
            rung(2, "h-b", backups = listOf("b-b1")),
        )
        // Index 0 is not presentable, so the machine must start at the rung that is.
        assertEquals(1, subject.selectInitial())
        subject.onFailure("HTTP 403")
        val hop = subject.onFailure("HTTP 403")
        assertTrue(hop is FailoverDecision.AdvanceBackup)
        assertEquals(1, (hop as FailoverDecision.AdvanceBackup).index)
        assertFalse(subject.log.isEmpty())
    }

    // ── Salaar (2026-11-12): a gate refusal is not a retryable failure ──────

    @Test
    fun `a gate refusal hands off at once, never retries or hops`() {
        // The server said this rung is VIP-only (402): retrying the same handle
        // and hopping to its runner-ups are the same refusal wearing different
        // addresses — the machine must hand off immediately so the service can
        // step the ladder down instead of burning ~3 s per hop.
        val subject = machine(rung(1, "h-a", backups = listOf("b-a1", "b-a2")))
        assertEquals(0, subject.selectInitial())
        val decision = subject.onFailure("Response code: 402", isGateRefusal = true)
        decision as FailoverDecision.Handoff
        assertEquals(HandoffWhy.GATE_REFUSED, decision.why)
        assertTrue(subject.log.last().action.contains("gate refused"))
    }

    @Test
    fun `a gate refusal with a next rank advances to it directly`() {
        val subject = machine(
            rung(1, "h-a", backups = listOf("b-a1")),
            rung(2, "h-b"),
        )
        assertEquals(0, subject.selectInitial())
        val decision = subject.onFailure("Response code: 402", isGateRefusal = true)
        decision as FailoverDecision.Advance
        assertEquals(1, decision.index)
    }

    @Test
    fun `a gate refusal on the last rank hands off, never retries`() {
        // Same as the handoff test above, but with no runner-ups at all: the
        // refusal still hands off as GATE_REFUSED, never as a retry.
        val subject = machine(rung(1, "h-a"))
        assertEquals(0, subject.selectInitial())
        val decision = subject.onFailure("Response code: 402", isGateRefusal = true)
        decision as FailoverDecision.Handoff
        assertEquals(HandoffWhy.GATE_REFUSED, decision.why)
    }

    @Test
    fun `a non-gate failure still retries and hops as before`() {
        val subject = machine(
            rung(1, "h-a", backups = listOf("b-a1")),
            rung(2, "h-b"),
        )
        assertEquals(0, subject.selectInitial())
        assertTrue(subject.onFailure("HTTP 403") is FailoverDecision.RetrySame)
        val hop = subject.onFailure("HTTP 403")
        assertTrue(hop is FailoverDecision.AdvanceBackup)
    }

    // ── the gate-refusal detector ────────────────────────────────────────────

    @Test
    fun `isGateRefusalError recognizes a 402 bad-http-status error`() {
        val error = androidx.media3.common.PlaybackException(
            "Response code: 402", null,
            androidx.media3.common.PlaybackException.ERROR_CODE_IO_BAD_HTTP_STATUS,
        )
        assertTrue(isGateRefusalError(error))
    }

    @Test
    fun `isGateRefusalError rejects a 404 and a timeout`() {
        val notFound = androidx.media3.common.PlaybackException(
            "Response code: 404", null,
            androidx.media3.common.PlaybackException.ERROR_CODE_IO_BAD_HTTP_STATUS,
        )
        assertFalse(isGateRefusalError(notFound))
        val timeout = androidx.media3.common.PlaybackException(
            "timeout", null,
            androidx.media3.common.PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT,
        )
        assertFalse(isGateRefusalError(timeout))
    }
}
