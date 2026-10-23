package com.raddstream.app.data.cache

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class CoverageMappingTest {

    // 780 kB / 130 min (7800 s) => exactly 100 bytes per second.
    private val total = 780_000L
    private val durationSec = 7_800.0

    @Test
    fun `simple movie maps time to byte linearly`() {
        val m = CoverageMapping.simple(total, durationSec)
        assertEquals(420_000L, m.fileByteAt(4_200.0)) // 70 minutes
        assertEquals(4_200.0, m.fileTimeAtByte(420_000L), 0.0001)
    }

    @Test
    fun `time is clamped to file bounds`() {
        val m = CoverageMapping.simple(total, durationSec)
        assertEquals(0L, m.fileByteAt(-50.0))
        assertEquals(total, m.fileByteAt(999_999.0))
    }

    @Test
    fun `zero duration yields zero offset safely`() {
        val m = CoverageMapping.simple(1000L, 0.0)
        assertEquals(0L, m.fileByteAt(50.0))
        assertEquals(0.0, m.fileTimeAtByte(500L), 0.0)
    }

    @Test
    fun `packed season maps episode-relative time through the pack offset`() {
        // Three 40-min episodes packed into one file; episode 2 starts at 2600s.
        val pack = CoverageMapping(
            totalSizeBytes = total,
            totalDurationSeconds = durationSec,
            episodeOffsetSeconds = 2_600.0,
            episodeDurationSeconds = 2_600.0,
            isPacked = true,
        )
        // 100s into episode 2 => 2700s into file => 270000 bytes.
        assertEquals(270_000L, pack.episodeByteAt(100.0))
        // The episode's own byte window is [2600s, 5200s) => [260000, 520000).
        assertEquals(260_000L..519_999L, pack.episodeByteRange())
    }

    @Test
    fun `episode byte range is null for a non-packed movie`() {
        val m = CoverageMapping.simple(total, durationSec)
        assertNull(m.episodeByteRange())
    }

    @Test
    fun `watched covered seconds is bounded by the verified byte prefix`() {
        val pack = CoverageMapping(
            totalSizeBytes = total,
            totalDurationSeconds = durationSec,
            episodeOffsetSeconds = 2_600.0,
            episodeDurationSeconds = 2_600.0,
            isPacked = true,
        )
        // Prefix reached 2700s in file time => 100s into this episode; user is at 300s.
        assertEquals(100.0, pack.watchedSecondsCovered(270_000L, 300.0), 0.001)
        // If the prefix is before the episode start, nothing of THIS episode is covered.
        assertEquals(0.0, pack.watchedSecondsCovered(100_000L, 300.0), 0.001)
        // Never exceeds the position the user is actually at.
        assertEquals(50.0, pack.watchedSecondsCovered(3_000_000L, 50.0), 0.001)
    }
}
