package com.raddstream.app.viewmodel

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * The play button used to start every title at zero after a process death: the position map
 * lives in memory, while the timestamp the Continue watching rail was showing sat in Room
 * unread by the player. These cases pin the ladder that decides which remembered position, if
 * any, a new load starts from.
 */
class ResumeSeedTest {

    @Test
    fun `an explicit start is never second-guessed`() {
        assertNull(
            ResumeSeed.seedFor(
                explicitStartMs = 45_000L,
                inProcessMs = 90_000L,
                syncedMs = 10_000L,
                localHistoryMs = 20_000L,
            ),
        )
    }

    @Test
    fun `a position measured in this process outranks any stored row`() {
        assertNull(
            ResumeSeed.seedFor(
                explicitStartMs = null,
                inProcessMs = 600_000L,
                syncedMs = 10_000L,
                localHistoryMs = 20_000L,
            ),
        )
    }

    @Test
    fun `the account row is asked before this devices own history`() {
        assertEquals(
            300_000L,
            ResumeSeed.seedFor(null, null, 300_000L, 240_000L),
        )
    }

    @Test
    fun `a dead process is what the local row is for`() {
        assertEquals(
            480_000L,
            ResumeSeed.seedFor(explicitStartMs = null, inProcessMs = null, syncedMs = null, localHistoryMs = 480_000L),
        )
    }

    @Test
    fun `nothing remembered means the load starts where it always did`() {
        assertNull(ResumeSeed.seedFor(null, null, null, null))
    }

    @Test
    fun `a newer remembered position re-seeds an already seeded one`() {
        // Session 126 (audit bug d): the viewer watched further elsewhere, so the
        // freshest row beats the seeded position.
        assertEquals(300_000L, ResumeSeed.newerSeed(120_000L, 300_000L, 240_000L))
        assertEquals(480_000L, ResumeSeed.newerSeed(120_000L, null, 480_000L))
    }

    @Test
    fun `an older or equal remembered position never moves the seed back`() {
        assertNull(ResumeSeed.newerSeed(300_000L, 120_000L, 240_000L))
        assertNull(ResumeSeed.newerSeed(300_000L, 300_000L, null))
        assertNull(ResumeSeed.newerSeed(300_000L, null, null))
    }

    @Test
    fun `no seeded position takes the freshest row`() {
        assertEquals(300_000L, ResumeSeed.newerSeed(null, 300_000L, 240_000L))
    }
}
