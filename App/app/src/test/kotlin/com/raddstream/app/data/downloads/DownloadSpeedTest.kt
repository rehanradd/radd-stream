package com.raddstream.app.data.downloads

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** App-design audit (2026-11-12, issue #12): % + MB + speed + ETA. */
class DownloadSpeedTest {

    @Test
    fun rollingAverageOverSamples() {
        // 1 MB in 10 s, then another 1 MB in 10 s: 100 KB/s.
        val samples = listOf(0L to 0L, 1_000_000L to 10_000L, 2_000_000L to 20_000L)
        assertEquals(100_000L, DownloadSpeed.estimateBytesPerSec(samples))
    }

    @Test
    fun tooFewSamplesMeansCalculating() {
        assertEquals(0L, DownloadSpeed.estimateBytesPerSec(emptyList()))
        assertEquals(0L, DownloadSpeed.estimateBytesPerSec(listOf(100L to 0L)))
        assertNull(DownloadSpeed.etaSeconds(1_000L, 0L))
    }

    @Test
    fun etaDividesRemainingBySpeed() {
        assertEquals(40L, DownloadSpeed.etaSeconds(4_000_000L, 100_000L))
        assertEquals(0L, DownloadSpeed.etaSeconds(0L, 100_000L))
    }

    @Test
    fun speedAndEtaFormatInViewerWords() {
        assertEquals("1.2 MB/s", DownloadSpeed.formatSpeed(1_200_000L))
        assertEquals("850 KB/s", DownloadSpeed.formatSpeed(850_000L))
        assertEquals("about 4 min left", DownloadSpeed.formatEta(240L))
        assertEquals("about 30 sec left", DownloadSpeed.formatEta(30L))
        assertNull(DownloadSpeed.formatEta(null))
    }
}
