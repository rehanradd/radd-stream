package com.raddstream.app.ui.components

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * App-design audit (2026-11-12): "★ 100.0" on a 0–10 scale, a literal
 * "/PLOT" line on the detail screen, and the same titles repeated across
 * Home rails. Each rule in [UserWords] is pinned here so the bad input
 * can never render again.
 */
class UserWordsTest {

    @Test
    fun ratingKeepsAValidTenScaleValue() {
        assertEquals("8.6", UserWords.displayRating("8.6"))
        assertEquals("10.0", UserWords.displayRating("10"))
    }

    @Test
    fun ratingDividesAHundredScaleValueByTen() {
        // The audit's "★ 100.0": a 0–100 value on a 0–10 badge.
        assertEquals("10.0", UserWords.displayRating("100.0"))
        assertEquals("7.6", UserWords.displayRating("76"))
    }

    @Test
    fun ratingHidesUnparseableOrOutOfRangeValues() {
        assertNull(UserWords.displayRating(null))
        assertNull(UserWords.displayRating(""))
        assertNull(UserWords.displayRating("abc"))
        assertNull(UserWords.displayRating("-1"))
        assertNull(UserWords.displayRating("101"))
        assertNull(UserWords.displayRating("Unknown"))
    }

    @Test
    fun synopsisDropsSectionMarkerLines() {
        val text = "A thief steals a dream.\n/PLOT\nHe wakes up changed."
        assertEquals(
            "A thief steals a dream.\nHe wakes up changed.",
            UserWords.stripSectionMarkers(text),
        )
    }

    @Test
    fun synopsisKeepsSlashesInsideSentences() {
        val text = "A comedy/drama about two friends."
        assertEquals(text, UserWords.stripSectionMarkers(text))
    }

    @Test
    fun dataEstimateNamesTheSameCostsAsThePlayerSheet() {
        assertEquals("≈ 700 MB/hour", UserWords.dataEstimateForQuality("480p"))
        assertEquals("≈ 1.5 GB/hour", UserWords.dataEstimateForQuality("720p"))
        assertEquals("≈ 3 GB/hour", UserWords.dataEstimateForQuality("1080p"))
        assertNull(UserWords.dataEstimateForQuality("cam"))
    }

    @Test
    fun titleBreaksBeforeAtSignNeverInsideTheNumber() {
        // "Kesariya@100" wrapped as "Kesariya@1 / 00" in the audit.
        val broken = UserWords.breakableTitle("Kesariya@100")
        assertEquals("Kesariya\u200B@100", broken)
        // The number itself carries no break opportunity.
        assert(!broken.substringAfter("@").contains("\u200B"))
    }

    @Test
    fun railDedupeKeepsFirstRailAndDropsRepeats() {
        val (first, seen) = UserWords.dedupeAcrossRails(
            listOf("a", "b", "c"), emptySet(), { it },
        )
        assertEquals(listOf("a", "b", "c"), first)
        val (second, _) = UserWords.dedupeAcrossRails(
            listOf("b", "c", "d"), seen, { it },
        )
        assertEquals(listOf("d"), second)
    }
}
