package com.raddstream.app.viewmodel

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class CatalogHelpersTest {

    @Test
    fun `parseYear extracts a plausible year from messy strings`() {
        assertEquals(2019, parseYear("2019"))
        assertEquals(2024, parseYear("2024–2025"))
        assertEquals(1998, parseYear("(1998)"))
        assertNull(parseYear(null))
        assertNull(parseYear(""))
        assertNull(parseYear("Season 7"))
    }

    @Test
    fun `normalizeTypeLabel maps v1 content types to group labels`() {
        assertEquals("Movies", normalizeTypeLabel("movie"))
        assertEquals("Series", normalizeTypeLabel("series"))
        assertEquals("Seasons", normalizeTypeLabel("complete_season"))
        assertEquals("Seasons", normalizeTypeLabel("ongoing_season"))
        assertEquals("Other", normalizeTypeLabel(null))
        assertEquals("Anime", normalizeTypeLabel("anime"))
    }

    @Test
    fun `posterMaxWidthPx respects quality and mobile-data saver`() {
        val high = UserPreferences(imageQuality = ImageQuality.HIGH)
        assertEquals(640, high.posterMaxWidthPx)
        val autoMobile = UserPreferences(imageQuality = ImageQuality.AUTO, downloadOnMobileData = true)
        assertEquals(400, autoMobile.posterMaxWidthPx)
        val autoWifi = UserPreferences(imageQuality = ImageQuality.AUTO, downloadOnMobileData = false)
        assertEquals(640, autoWifi.posterMaxWidthPx)
    }

    @Test
    fun `kept item progress is clamped and safe against divide by zero`() {
        val partial = KeptItem("1", "T", "1080p", bytesDownloaded = 50, bytesTotal = 100, state = KeepState.DOWNLOADING, expiresAtMillis = null)
        assertEquals(0.5f, partial.progress, 0.0001f)
        val zeroTotal = KeptItem("2", "T", "1080p", bytesDownloaded = 0, bytesTotal = 0, state = KeepState.QUEUED, expiresAtMillis = null)
        assertEquals(0f, zeroTotal.progress, 0f)
        val overflow = KeptItem("3", "T", "1080p", bytesDownloaded = 200, bytesTotal = 100, state = KeepState.DOWNLOADING, expiresAtMillis = null)
        assertEquals(1f, overflow.progress, 0f)
    }

    @Test
    fun `storage low-space flag triggers under half a gig`() {
        val low = StorageInfo(freeBytes = 100_000_000L, totalBytes = 64_000_000_000L)
        assertTrue(low.lowSpace)
        assertTrue(low.usedBytes > 0)
        val plenty = StorageInfo(freeBytes = 40_000_000_000L, totalBytes = 64_000_000_000L)
        assertFalse(plenty.lowSpace)
        val zeroFree = StorageInfo(freeBytes = 0L, totalBytes = 64_000_000_000L)
        assertFalse(zeroFree.lowSpace) // exactly zero is handled as "no space" separately, not the <500MB advisory
    }

    @Test
    fun `kept item remaining millis counts down`() {
        val now = 1_000_000L
        val future = KeptItem("4", "T", "480p", 0, 0, KeepState.READY, expiresAtMillis = now + 5_000)
        assertEquals(5_000L, future.remainingMillis(now))
        val past = KeptItem("5", "T", "480p", 0, 0, KeepState.EXPIRING, expiresAtMillis = now - 1_000)
        assertEquals(0L, past.remainingMillis(now))
    }

    @Test
    fun `a partial page never claims to be the whole answer`() {
        // The old header said "37 results" for a query the server reported as 4,112 strong,
        // because it counted only the page this device had paged in.
        assertEquals("Showing 37 of 4112", resultsSummary(loaded = 37, serverTotal = 4112, hasMore = true))
        assertEquals("Showing 37 of 4112", resultsSummary(loaded = 37, serverTotal = 4112, hasMore = false))
    }

    @Test
    fun `a complete answer is counted plainly`() {
        assertEquals("1 result", resultsSummary(loaded = 1, serverTotal = 1, hasMore = false))
        assertEquals("12 results", resultsSummary(loaded = 12, serverTotal = 12, hasMore = false))
        assertEquals("0 results", resultsSummary(loaded = 0, serverTotal = 0, hasMore = false))
    }
}
