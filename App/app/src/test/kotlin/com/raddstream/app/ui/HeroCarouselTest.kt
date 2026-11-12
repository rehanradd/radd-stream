package com.raddstream.app.ui

import com.raddstream.app.ui.components.HERO_INDICATOR_TOP_DP
import com.raddstream.app.ui.components.heroIndicatorOverlapsActionRow
import com.raddstream.app.ui.components.heroLanguagePills
import com.raddstream.app.ui.components.nextHeroPage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The hero banner's one piece of real logic: what a free-text `posts.language` column
 * becomes when it is drawn as pills. The renderer cannot be tested here (no Robolectric),
 * so what is tested is the decision the renderer depends on.
 */
class HeroCarouselTest {

    @Test
    fun splitsTheMixedSeparatorsTheColumnActuallyUses() {
        assertEquals(
            listOf("Hindi", "English", "Japanese"),
            heroLanguagePills("Hindi + English + Japanese"),
        )
        assertEquals(listOf("Tamil", "Telugu"), heroLanguagePills("Tamil, Telugu"))
        assertEquals(listOf("English"), heroLanguagePills("English"))
    }

    @Test
    fun answersNothingForNothing() {
        assertTrue(heroLanguagePills(null).isEmpty())
        assertTrue(heroLanguagePills("").isEmpty())
        assertTrue(heroLanguagePills("   ").isEmpty())
    }

    @Test
    fun capsThePillsAndDropsValuesTooLongToFit() {
        assertEquals(3, heroLanguagePills("A, B, C, D, E").size)

        // A 40-character "language" is a scrape accident, not a pill: it would push the
        // title off the banner, so it is dropped instead of truncated.
        val tooLong = "x".repeat(40)
        assertEquals(listOf("English"), heroLanguagePills("$tooLong, English"))
        assertTrue(heroLanguagePills(tooLong).isEmpty())
    }

    @Test
    fun dropsDuplicates() {
        assertEquals(listOf("English"), heroLanguagePills("English, English, English"))
    }

    // The auto-advance step: forward one page, wrapping from the last back to 0.
    @Test
    fun nextPageAdvancesAndWraps() {
        assertEquals(1, nextHeroPage(0, 6))
        assertEquals(5, nextHeroPage(4, 6))
        assertEquals(0, nextHeroPage(5, 6))
        assertEquals(0, nextHeroPage(0, 1))
    }

    @Test
    fun nextPageNowhereOnDegenerateCount() {
        assertEquals(0, nextHeroPage(0, 0))
        assertEquals(0, nextHeroPage(3, 0))
    }

    // The Watch Now regression (Appetize v1.1.2): the indicator's 48dp hit boxes sat in
    // the buttons' bottom strip, on top in z-order, and on a 6-dot hero covered the Watch
    // Now button's centre — a centred tap selected a dot instead of navigating. The
    // indicator now rides the top band, so its band must clear the button strip on both
    // hero heights (320dp narrow phone, 400dp regular).
    @Test
    fun indicatorBandClearsTheButtonStrip() {
        assertFalse(heroIndicatorOverlapsActionRow(320f, HERO_INDICATOR_TOP_DP))
        assertFalse(heroIndicatorOverlapsActionRow(400f, HERO_INDICATOR_TOP_DP))
    }

    @Test
    fun bottomAnchoredIndicatorWouldOverlapTheButtonStrip() {
        // Regression witness: the old placement anchored the indicator 20dp up from the
        // bottom edge, so its top sat at heroH - 20 - 48 — inside the buttons' band
        // [heroH - 72, heroH - 20] — and the overlap ate the taps. If this ever goes
        // false, the witness is stale, not the fix.
        assertTrue(heroIndicatorOverlapsActionRow(320f, 320f - 20f - 48f))
        assertTrue(heroIndicatorOverlapsActionRow(400f, 400f - 20f - 48f))
    }
}
