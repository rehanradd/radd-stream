package com.raddstream.app.viewmodel

import com.raddstream.app.network.models.ReleaseDetail
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Gap A2: the pre-resolve warms exactly the link Play would press, and a
 * cached bundle is reused only for its own print inside a short window.
 */
class PreResolveTest {

    private fun movieLayout(): ReleaseLayout {
        val low = ReleaseDetail(id = 11, quality = "480p")
        val high = ReleaseDetail(id = 22, quality = "1080p")
        return ReleaseLayoutBuilder.build("movie", listOf(low, high))
    }

    @Test
    fun `best print is the highest ranked print`() {
        val best = bestPrintOf(movieLayout())

        assertEquals(22, best?.releaseId)
    }

    @Test
    fun `no layout means no best print`() {
        assertNull(bestPrintOf(null))
    }

    @Test
    fun `fresh cache for the same print is reused`() {
        assertTrue(isPreresolveFresh(cachedReleaseId = 22, cachedAtMs = 1_000L, releaseId = 22, nowMs = 60_000L))
    }

    @Test
    fun `cache for another print is never reused`() {
        assertFalse(isPreresolveFresh(cachedReleaseId = 11, cachedAtMs = 1_000L, releaseId = 22, nowMs = 2_000L))
    }

    @Test
    fun `stale cache is never reused`() {
        assertFalse(
            isPreresolveFresh(
                cachedReleaseId = 22,
                cachedAtMs = 1_000L,
                releaseId = 22,
                nowMs = 1_000L + PRERESOLVE_FRESH_MS + 1L,
            ),
        )
    }

    @Test
    fun `no cached time means nothing cached`() {
        assertFalse(isPreresolveFresh(cachedReleaseId = 22, cachedAtMs = null, releaseId = 22, nowMs = 2_000L))
    }
}
