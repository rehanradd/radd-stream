package com.raddstream.app.ui.components

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * F2 (Batch A): the audio and subtitle badges draw their language names from the
 * same free-text column the hero pills do, so they hid the server's "Unknown"
 * the same way — "Unknown audio", "Subtitles Unknown". A missing language is a
 * missing value, never a badge word.
 */
class MediaBadgesTest {

    @Test
    fun `an unknown audio language is not a badge word`() {
        assertEquals("Dual Audio", audioBadgeText(dualAudio = true, languages = listOf("Unknown")))
        assertNull(audioBadgeText(dualAudio = false, languages = listOf("Unknown")))
        assertEquals(
            "Hindi audio",
            audioBadgeText(dualAudio = false, languages = listOf("Hindi", "Unknown")),
        )
    }

    @Test
    fun `known audio languages still read as before`() {
        assertEquals(
            "Dual Audio Hindi + English",
            audioBadgeText(dualAudio = true, languages = listOf("Hindi", "English")),
        )
        assertEquals("Hindi audio", audioBadgeText(dualAudio = false, languages = listOf("Hindi")))
    }

    @Test
    fun `an unknown subtitle language adds no suffix`() {
        assertEquals(
            "Subtitles",
            subtitleBadgeText(
                available = true,
                external = false,
                hardcoded = false,
                languages = listOf("Unknown"),
            ),
        )
        assertEquals(
            "Subtitles English",
            subtitleBadgeText(
                available = true,
                external = false,
                hardcoded = false,
                languages = listOf("English", "N/A"),
            ),
        )
        assertEquals(
            "Hardcoded subs",
            subtitleBadgeText(
                available = true,
                external = false,
                hardcoded = true,
                languages = listOf("Unknown"),
            ),
        )
    }
}
