package com.raddstream.app.player.subtitles

import org.junit.Assert.assertEquals
import org.junit.Test

class SubtitleOffsetTest {

    @Test
    fun `clamp pins the offset to the same window the overlay enforces`() {
        assertEquals(60_000L, SubtitleOffset.clamp(90_000L))
        assertEquals(-60_000L, SubtitleOffset.clamp(-90_000L))
        assertEquals(1_234L, SubtitleOffset.clamp(1_234L))
    }

    @Test
    fun `shift moves by the requested step and keeps the clamp`() {
        assertEquals(500L, SubtitleOffset.shift(0L, SubtitleOffset.COARSE_STEP_MS))
        assertEquals(-100L, SubtitleOffset.shift(0L, -SubtitleOffset.FINE_STEP_MS))
        assertEquals(60_000L, SubtitleOffset.shift(59_800L, SubtitleOffset.COARSE_STEP_MS))
    }

    @Test
    fun `reset returns to zero from either direction`() {
        assertEquals(0L, SubtitleOffset.reset())
    }

    @Test
    fun `quantize snaps slider noise to a tenth of a second`() {
        assertEquals(100L, SubtitleOffset.quantize(149L))
        assertEquals(200L, SubtitleOffset.quantize(150L))
        assertEquals(-100L, SubtitleOffset.quantize(-149L))
        assertEquals(0L, SubtitleOffset.quantize(49L))
        assertEquals(0L, SubtitleOffset.quantize(-49L))
    }

    @Test
    fun `format reads as a signed offset with the right precision`() {
        assertEquals("In sync", SubtitleOffset.format(0L))
        assertEquals("+0.1s", SubtitleOffset.format(100L))
        assertEquals("-0.1s", SubtitleOffset.format(-100L))
        assertEquals("+0.5s", SubtitleOffset.format(500L))
        assertEquals("+1.0s", SubtitleOffset.format(1_000L))
        assertEquals("-1.5s", SubtitleOffset.format(-1_500L))
        assertEquals("+60.0s", SubtitleOffset.format(60_000L))
        assertEquals("-0.05s", SubtitleOffset.format(-50L))
    }

    @Test
    fun `format never prints a sign the offset does not have`() {
        assertEquals("-60.0s", SubtitleOffset.format(-90_000L))
        assertEquals("+60.0s", SubtitleOffset.format(90_000L))
    }

    @Test
    fun `describe speaks in playback terms, not signs`() {
        assertEquals("Subtitles appear later than the picture", SubtitleOffset.describe(500L))
        assertEquals("Subtitles appear earlier than the picture", SubtitleOffset.describe(-500L))
        assertEquals("Picture and subtitles are aligned", SubtitleOffset.describe(0L))
    }

    @Test
    fun `a full sequence of quick presses arrives where the buttons promise`() {
        var offset = 0L
        offset = SubtitleOffset.shift(offset, -SubtitleOffset.COARSE_STEP_MS)
        offset = SubtitleOffset.shift(offset, -SubtitleOffset.FINE_STEP_MS)
        assertEquals(-600L, offset)
        offset = SubtitleOffset.shift(offset, SubtitleOffset.FINE_STEP_MS)
        offset = SubtitleOffset.shift(offset, SubtitleOffset.COARSE_STEP_MS)
        assertEquals(0L, offset)
    }
}
