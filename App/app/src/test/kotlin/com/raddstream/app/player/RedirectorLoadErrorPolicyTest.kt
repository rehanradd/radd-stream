package com.raddstream.app.player

import androidx.media3.common.C
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Session 158 (S5): Media3 must never retry a final answer from our own
 * redirector. The player hands Media3 the redirector URL as its media
 * item, so the default load-error policy's retries re-press /api/v1/stream
 * — the S5 log shows the player pressing dead handles ~1/sec until the
 * server's per-minute bucket 429'd the session (239x404 + 136x429). A
 * 404/410 means the handle has no playable source, a 402 is the quality
 * gate's refusal (the failover machine's step-down), and a 429 is a
 * "wait", not a "retry now". These tests pin the terminal-status table
 * itself; the policy class that wraps it delegates everything else to
 * Media3's default, unchanged.
 */
class RedirectorLoadErrorPolicyTest {

    @Test
    fun `a 404 from the redirector never retries`() {
        assertEquals(C.TIME_UNSET, redirectorRetryDelayMs(404))
    }

    @Test
    fun `a 410 from the redirector never retries`() {
        assertEquals(C.TIME_UNSET, redirectorRetryDelayMs(410))
    }

    @Test
    fun `a 403 from the redirector never retries`() {
        assertEquals(C.TIME_UNSET, redirectorRetryDelayMs(403))
    }

    @Test
    fun `a 402 gate refusal never retries`() {
        assertEquals(C.TIME_UNSET, redirectorRetryDelayMs(402))
    }

    @Test
    fun `a 429 rate limit never retries`() {
        assertEquals(C.TIME_UNSET, redirectorRetryDelayMs(429))
    }

    @Test
    fun `a 500 defers to the default policy`() {
        assertNull(redirectorRetryDelayMs(500))
    }

    @Test
    fun `a 503 defers to the default policy`() {
        assertNull(redirectorRetryDelayMs(503))
    }

    @Test
    fun `no status defers to the default policy`() {
        assertNull(redirectorRetryDelayMs(null))
    }
}
