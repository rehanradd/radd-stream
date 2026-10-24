package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class BingePreloaderTest {

    // Explicit tiny budget keeps the test independent of the Brand default.
    private fun preloader() =
        BingePreloader(maxHeadBytesPerRequest = BingePreloader.DEFAULT_HEAD_BYTES)

    private fun seriesState(
        positionMs: Long,
        durationMs: Long = 1_000_000L,
        handle: String? = "next-ep-handle",
    ) = BingePreloadState(
        positionMs = positionMs,
        durationMs = durationMs,
        isSeries = true,
        nextEpisodeHandle = handle,
    )

    @Test
    fun `below the 85 percent threshold nothing is requested`() {
        val d = preloader().decide(seriesState(positionMs = 849_999L), emptySet())
        assertTrue(d is BingePreloadDecision.Idle)
        assertEquals(BingeSkipReason.BEFORE_THRESHOLD, (d as BingePreloadDecision.Idle).reason)
    }

    @Test
    fun `at the threshold the next handle is requested once`() {
        val d = preloader().decide(seriesState(positionMs = 850_000L), emptySet())
        assertTrue(d is BingePreloadDecision.PrefetchNextHead)
        d as BingePreloadDecision.PrefetchNextHead
        assertEquals("next-ep-handle", d.handle)
        assertEquals(BingePreloader.DEFAULT_HEAD_BYTES, d.headBytes)
    }

    @Test
    fun `a handle already requested is never requested again`() {
        val d = preloader().decide(seriesState(positionMs = 900_000L), setOf("next-ep-handle"))
        assertTrue(d is BingePreloadDecision.Idle)
        assertEquals(BingeSkipReason.ALREADY_REQUESTED, (d as BingePreloadDecision.Idle).reason)
    }

    @Test
    fun `non-series never prefetches`() {
        val state = BingePreloadState(
            positionMs = 999_000L,
            durationMs = 1_000_000L,
            isSeries = false,
            nextEpisodeHandle = "next-ep-handle",
        )
        val d = preloader().decide(state, emptySet())
        assertTrue(d is BingePreloadDecision.Idle)
        assertEquals(BingeSkipReason.NOT_A_SERIES, (d as BingePreloadDecision.Idle).reason)
    }

    @Test
    fun `blank or missing next handle is skipped`() {
        for (handle in listOf<String?>("  ", "", null)) {
            val d = preloader().decide(seriesState(positionMs = 900_000L, handle = handle), emptySet())
            assertTrue(d is BingePreloadDecision.Idle)
            assertEquals(BingeSkipReason.NO_NEXT_HANDLE, (d as BingePreloadDecision.Idle).reason)
        }
    }

    @Test
    fun `non-positive duration is a guard, never a divide`() {
        for (duration in listOf(0L, -1L, Long.MIN_VALUE)) { // Long.MIN_VALUE == C.TIME_UNDEFINED
            val d = preloader().decide(seriesState(positionMs = 500_000L, durationMs = duration), emptySet())
            assertTrue(d is BingePreloadDecision.Idle)
            assertEquals(BingeSkipReason.DURATION_UNKNOWN, (d as BingePreloadDecision.Idle).reason)
        }
    }

    @Test
    fun `request head is capped by the injected budget`() {
        val d = BingePreloader(maxHeadBytesPerRequest = 4096L)
            .decide(seriesState(positionMs = 900_000L), emptySet())
        d as BingePreloadDecision.PrefetchNextHead
        assertEquals(4096L, d.headBytes)
    }

    @Test
    fun `exhausted budget disables prefetch instead of requesting zero bytes`() {
        val d = BingePreloader(maxHeadBytesPerRequest = 0L)
            .decide(seriesState(positionMs = 900_000L), emptySet())
        assertTrue(d is BingePreloadDecision.Idle)
        assertEquals(BingeSkipReason.BUDGET_EXHAUSTED, (d as BingePreloadDecision.Idle).reason)
    }
}
