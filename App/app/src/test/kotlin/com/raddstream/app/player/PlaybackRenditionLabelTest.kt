package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Session 121 (P-7): the player's "Quality:" line must name a rung, never the title.
 * The print's `summary` used to fall back to its `label` — the title — when nothing
 * about the quality was known, so the start notice read "Quality: Ali Baba aur 40
 * Bhoot". A title is not a quality; saying nothing is, and the gate
 * ([looksLikeQualityLabel]) keeps anything that is not a rung out of the line.
 */
class PlaybackRenditionLabelTest {

    @Test
    fun `a print that names no quality has an empty summary, never its title`() {
        assertEquals("", PrintInfo(label = "Ali Baba aur 40 Bhoot").summary())
        assertEquals("", PrintInfo(label = "Ali Baba aur 40 Bhoot", resolution = "unknown").summary())
        assertEquals(
            "1080p · web dl · H264",
            PrintInfo(
                label = "Ali Baba aur 40 Bhoot",
                resolution = "1080p",
                sourceTag = "web_dl",
                codec = "h264",
            ).summary(),
        )
    }

    @Test
    fun `the display label is quality language or a rank, never the title`() {
        val titleOnly = PlaybackRendition(
            rank = 1,
            releaseId = 7,
            print = PrintInfo(label = "Ali Baba aur 40 Bhoot"),
            playback = PlaybackInfo(label = "Fast direct"),
        )
        assertEquals("Fast direct", titleOnly.displayLabel())

        val noLabel = titleOnly.copy(playback = PlaybackInfo())
        assertEquals("Rank #1", noLabel.displayLabel())

        val known = PlaybackRendition(
            rank = 1,
            releaseId = 7,
            print = PrintInfo(label = "Ali Baba aur 40 Bhoot", resolution = "1080p"),
            playback = PlaybackInfo(),
        )
        assertEquals("1080p · Standard bitrate", known.displayLabel())
    }

    @Test
    fun `only rung and codec words count as a quality label`() {
        assertTrue(looksLikeQualityLabel("1080p"))
        assertTrue(looksLikeQualityLabel("720p · Standard bitrate"))
        assertTrue(looksLikeQualityLabel("Auto"))
        assertTrue(looksLikeQualityLabel("Data saver"))
        assertTrue(looksLikeQualityLabel("1080p · High bitrate · Fast direct"))
        assertTrue(looksLikeQualityLabel("4K Ultra HD"))

        assertFalse(looksLikeQualityLabel("Rank #1"))
        assertFalse(looksLikeQualityLabel("Ali Baba aur 40 Bhoot"))
        assertFalse(looksLikeQualityLabel("Fast direct"))
        assertFalse(looksLikeQualityLabel(""))
    }
}
