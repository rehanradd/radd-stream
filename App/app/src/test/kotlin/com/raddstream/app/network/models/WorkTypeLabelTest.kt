package com.raddstream.app.network.models

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * App-design audit (2026-11-12, issue #16): the hero wore a "Movie ·
 * Unknown" chip. A work whose type the catalog does not know paints no
 * type chip at all — never the word "Unknown".
 */
class WorkTypeLabelTest {

    @Test
    fun unknownContentTypePaintsNothing() {
        assertNull(WorkTypeLabel.of("unknown", false))
        assertNull(WorkTypeLabel.of("Unknown", false))
        assertNull(WorkTypeLabel.of("", false))
        assertNull(WorkTypeLabel.of(null, false))
    }

    @Test
    fun knownContentTypeStillLabels() {
        assertEquals("Movie", WorkTypeLabel.of("movie", false))
        assertEquals("Season", WorkTypeLabel.of("complete_season", false))
        assertEquals("Anime", WorkTypeLabel.of("series", true))
    }
}
