package com.raddstream.app.player

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * JVM-only tests for the scrub-thumbnail gate and visibility rule. Both are
 * pure functions of their inputs, so the whole API-23 gate and the
 * settle-then-show rule are assertable without Android: no ExoPlayer, no
 * TextureView, no composition.
 */
class ScrubPreviewTest {

    @Test
    fun `android 5_0 gets no scrub thumbnails`() {
        assertFalse(ScrubThumbnails.isSupported(sdkInt = 21))
    }

    @Test
    fun `android 5_1 gets no scrub thumbnails`() {
        assertFalse(ScrubThumbnails.isSupported(sdkInt = 22))
    }

    @Test
    fun `android 6_0 gets scrub thumbnails`() {
        assertTrue(ScrubThumbnails.isSupported(sdkInt = 23))
    }

    @Test
    fun `a modern device gets scrub thumbnails`() {
        assertTrue(ScrubThumbnails.isSupported(sdkInt = 34))
    }

    @Test
    fun `thumbnail shows once the target settles and a preview exists`() {
        assertTrue(
            ScrubThumbnails.shouldShowThumbnail(
                settledMs = 90_000L,
                targetMs = 90_000L,
                previewAvailable = true,
            ),
        )
    }

    @Test
    fun `thumbnail hides when there is no preview player`() {
        assertFalse(
            ScrubThumbnails.shouldShowThumbnail(
                settledMs = 90_000L,
                targetMs = 90_000L,
                previewAvailable = false,
            ),
        )
    }

    @Test
    fun `thumbnail hides while the finger is still moving`() {
        // The settled target trails the live one during a drag: the frame on
        // screen is from the last settled position, the wrong scene for the
        // time the toast prints.
        assertFalse(
            ScrubThumbnails.shouldShowThumbnail(
                settledMs = 60_000L,
                targetMs = 90_000L,
                previewAvailable = true,
            ),
        )
    }

    @Test
    fun `thumbnail hides before the first settle`() {
        assertFalse(
            ScrubThumbnails.shouldShowThumbnail(
                settledMs = null,
                targetMs = 90_000L,
                previewAvailable = true,
            ),
        )
    }
}
