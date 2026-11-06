package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * A-B repeat (plan §5 step 14, P13): loop one segment, A to B. The loop is
 * ticker-driven — the ViewModel asks [loopTargetMs] on every 200 ms visit — so
 * the policy is pure position and time, and this test proves it without a player.
 */
class AbRepeatTest {

    @Test
    fun `setting B past A makes a segment, setting A past B starts a new one`() {
        val ab = abRepeatWithB(abRepeatWithA(AbRepeat(), 10_000), 20_000)
        assertTrue(ab.isActive)
        assertEquals(10_000L, ab.aMs)
        assertEquals(20_000L, ab.bMs)
        val restarted = abRepeatWithA(ab, 25_000)
        assertFalse(restarted.isActive)
        assertEquals(25_000L, restarted.aMs)
        assertNull(restarted.bMs)
    }

    @Test
    fun `B at or before A is ignored, the old A stands`() {
        val ab = abRepeatWithA(AbRepeat(), 10_000)
        assertEquals(ab, abRepeatWithB(ab, 10_000))
        assertEquals(ab, abRepeatWithB(ab, 5_000))
        assertEquals(AbRepeat(), abRepeatWithB(AbRepeat(), 5_000))
    }

    @Test
    fun `the playhead loops to A at B and not before`() {
        val ab = AbRepeat(aMs = 10_000, bMs = 20_000)
        assertNull(loopTargetMs(19_999, ab, null, 0))
        assertEquals(10_000L, loopTargetMs(20_000, ab, null, 0))
        assertEquals(10_000L, loopTargetMs(25_000, ab, null, 0))
    }

    @Test
    fun `the re-arm window stops a seek still in flight from being re-issued`() {
        val ab = AbRepeat(aMs = 10_000, bMs = 20_000)
        assertNull(loopTargetMs(20_500, ab, lastLoopAtMs = 500, nowMs = 1_000))
        assertEquals(10_000L, loopTargetMs(20_500, ab, lastLoopAtMs = 500, nowMs = 1_500))
    }

    @Test
    fun `no segment means no loop`() {
        assertNull(loopTargetMs(30_000, AbRepeat(), null, 0))
        assertNull(loopTargetMs(30_000, AbRepeat(aMs = 10_000), null, 0))
        assertNull(loopTargetMs(30_000, AbRepeat(aMs = 20_000, bMs = 10_000), null, 0))
    }
}
