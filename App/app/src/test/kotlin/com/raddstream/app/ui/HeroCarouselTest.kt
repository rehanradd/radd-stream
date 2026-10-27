package com.raddstream.app.ui

import com.raddstream.app.ui.components.heroLanguagePills
import org.junit.Assert.assertEquals
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
}
