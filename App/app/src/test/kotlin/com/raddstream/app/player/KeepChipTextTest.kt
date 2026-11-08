package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

/**
 * Session 120: the Keep chip used to read "Keeping 0 B of 3.05 GB" while a
 * start never landed, which reads as "the player is downloading the whole
 * file before it will play". Playback streams from the redirector at once;
 * the keep is a background copy. The chip says so and never quotes the full
 * file size as a download still owed.
 */
class KeepChipTextTest {

    @Test
    fun `a keeping chip names the background copy, not a download owed`() {
        val text = CacheAffordance.chipText(KeepUiState.Keeping(0L, 3_050_000_000L, 0L))
        assertEquals("Saving a copy in the background", text)
        assertFalse("chip must not quote the file size as a pending download", text.contains("3.05"))
        assertFalse("chip must not show zero bytes saved as a stalled download", text.contains("0 B"))
    }

    @Test
    fun `a keeping chip may still show the live save rate`() {
        val text = CacheAffordance.chipText(KeepUiState.Keeping(40_000_000L, 3_050_000_000L, 1_200_000L))
        assertEquals("Saving a copy in the background · 1.2 MB/s", text)
    }

    @Test
    fun `watching and stored chips keep their words`() {
        assertEquals(
            "40.0 MB of 3.05 GB saved",
            CacheAffordance.chipText(KeepUiState.Watching(40_000_000L, 3_050_000_000L, false, null)),
        )
        assertEquals("Kept ✓", CacheAffordance.chipText(KeepUiState.Stored(true, null)))
    }
}
