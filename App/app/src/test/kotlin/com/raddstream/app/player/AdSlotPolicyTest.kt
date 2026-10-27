package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AdSlotPolicyTest {

    private fun state(
        isSeriesEpisode: Boolean = true,
        isEnded: Boolean = false,
        isPlaying: Boolean = false,
        positionMs: Long = 0L,
        durationMs: Long = 1_000_000L,
        hasNextEpisode: Boolean = true,
        isEntitled: Boolean = false,
    ) = AdSlotState(isSeriesEpisode, isEnded, isPlaying, positionMs, durationMs, hasNextEpisode, isEntitled)

    @Test
    fun `a paused file at its first frame is the only pre-roll slot`() {
        assertEquals(AdSlot.PRE_ROLL, AdSlotPolicy.decide(state(positionMs = 0L)))
        assertEquals(AdSlot.PRE_ROLL, AdSlotPolicy.decide(state(positionMs = 1_500L)))
    }

    @Test
    fun `a running title never gets a break at any position`() {
        assertEquals(
            AdSlot.NONE,
            AdSlotPolicy.decide(state(isPlaying = true, positionMs = 0L)),
        )
        assertEquals(
            AdSlot.NONE,
            AdSlotPolicy.decide(state(isPlaying = true, positionMs = 600_000L)),
        )
    }

    @Test
    fun `a series end with a successor gets the between-episodes slot`() {
        assertEquals(
            AdSlot.BETWEEN_EPISODES,
            AdSlotPolicy.decide(state(isEnded = true, positionMs = 1_000_000L)),
        )
    }

    @Test
    fun `a movie end gets no break at all`() {
        assertEquals(
            AdSlot.NONE,
            AdSlotPolicy.decide(state(isSeriesEpisode = false, isEnded = true, positionMs = 1_000_000L)),
        )
    }

    @Test
    fun `a series end with nowhere to go gets no break`() {
        assertEquals(
            AdSlot.NONE,
            AdSlotPolicy.decide(state(isEnded = true, hasNextEpisode = false, positionMs = 1_000_000L)),
        )
    }

    @Test
    fun `unknown duration is never a pre-roll`() {
        assertEquals(AdSlot.NONE, AdSlotPolicy.decide(state(durationMs = 0L)))
    }

    @Test
    fun `mid-playback placement is illegal by construction`() {
        assertFalse(AdSlotPolicy.isLegalMidPlayback(AdSlot.PRE_ROLL, positionMs = 300_000L, durationMs = 1_000_000L))
        assertTrue(AdSlotPolicy.isLegalMidPlayback(AdSlot.PRE_ROLL, positionMs = 0L, durationMs = 1_000_000L))
        assertTrue(AdSlotPolicy.isLegalMidPlayback(AdSlot.BETWEEN_EPISODES, positionMs = 1_000_000L, durationMs = 1_000_000L))
    }

    @Test
    fun `a paid member is silent at every moment a slot exists`() {
        // The purchase removes both placements, not only the mid-title one: the between-episodes
        // break is exactly what a binge runs into, so honouring VIP only while playing would
        // sell the wrong thing.
        assertEquals(AdSlot.NONE, AdSlotPolicy.decide(state(positionMs = 0L, isEntitled = true)))
        assertEquals(
            AdSlot.NONE,
            AdSlotPolicy.decide(
                state(isEnded = true, hasNextEpisode = true, positionMs = 1_000_000L, isEntitled = true),
            ),
        )
    }

    @Test
    fun `entitlement is the only thing that can silence a free viewer slot`() {
        // Guards against a future field being folded into the same branch by accident: with no
        // entitlement the documented slots still exist.
        assertEquals(AdSlot.PRE_ROLL, AdSlotPolicy.decide(state(positionMs = 0L, isEntitled = false)))
        assertEquals(
            AdSlot.BETWEEN_EPISODES,
            AdSlotPolicy.decide(
                state(isEnded = true, hasNextEpisode = true, positionMs = 1_000_000L, isEntitled = false),
            ),
        )
    }
}
