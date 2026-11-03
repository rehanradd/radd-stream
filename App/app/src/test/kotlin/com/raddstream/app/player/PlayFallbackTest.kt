package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Play never opens a provider page: when the tapped rung is only a page, Play
 * falls back to the next playable rung at the same quality. These tests pin
 * that fallback: same band only, a page is never a fallback, a locked rung is
 * skipped, a handle-less rung is skipped, and no fallback means no fallback.
 */
class PlayFallbackTest {

    private fun rung(
        band: String,
        id: String,
        playsHere: Boolean = true,
        page: Boolean = false,
    ) = QualityOption(
        band = band,
        title = "Copy $id",
        streamId = id,
        playUrl = "http://127.0.0.1:8080/api/v1/stream?id=$id",
        sizeBytes = 1_400_000_000,
        backupHandles = emptyList(),
        playsHere = playsHere,
        resumable = true,
        copies = 2,
        isProviderPage = page,
    )

    @Test
    fun `falls back to the next playable rung in the same band`() {
        val current = rung("720p", "page", playsHere = false, page = true)
        val first = rung("720p", "first", playsHere = false)
        val second = rung("720p", "second")
        val otherBand = rung("1080p", "other")

        val fallback = nextPlayableRung(listOf(otherBand, current, first, second), current)

        assertEquals(second, fallback)
    }

    @Test
    fun `a page rung is never a fallback`() {
        val current = rung("720p", "page", playsHere = false, page = true)
        val pageOnly = rung("720p", "page2", playsHere = false, page = true)

        assertNull(nextPlayableRung(listOf(current, pageOnly), current))
    }

    @Test
    fun `a locked rung is skipped for the next unlocked one`() {
        val current = rung("720p", "page", playsHere = false, page = true)
        val locked = rung("720p", "locked")
        val unlocked = rung("720p", "unlocked")

        val fallback = nextPlayableRung(
            listOf(current, locked, unlocked),
            current,
        ) { candidate -> candidate.streamId == "locked" }

        assertEquals(unlocked, fallback)
    }

    @Test
    fun `a rung without a handle is skipped`() {
        val current = rung("720p", "page", playsHere = false, page = true)
        val handleLess = rung("720p", "").copy(streamId = "")
        val good = rung("720p", "good")

        assertEquals(good, nextPlayableRung(listOf(current, handleLess, good), current))
    }

    @Test
    fun `no fallback when the band has no playable rung`() {
        val current = rung("720p", "page", playsHere = false, page = true)
        val otherBandPlayable = rung("1080p", "other")

        assertNull(nextPlayableRung(listOf(current, otherBandPlayable), current))
        assertNull(nextPlayableRung(emptyList(), current))
    }
}
