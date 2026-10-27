package com.raddstream.app.data

import com.raddstream.app.ui.screens.subtitleOptions
import com.raddstream.app.viewmodel.UserPreferences
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The three onboarding cards, pinned to the two things they must never drift from: the stored
 * region vocabulary ([UserRegion]) and the words the Settings chips can actually display.
 *
 * A card is a promise about the catalog, so the second group of tests is the honest one — the
 * screen may only offer what `classify_media()` can produce, and what it cannot offer has to be
 * said out loud instead of quietly omitted.
 */
class RegionChoicesTest {

    @Test
    fun `every stored region value has exactly one card`() {
        assertEquals(UserRegion.ALL, RegionChoices.ALL.map { it.id })
        assertEquals(RegionChoices.ALL.size, RegionChoices.ALL.map { it.id }.distinct().size)
    }

    @Test
    fun `the default card is the shipped default region`() {
        assertEquals(UserRegion.DEFAULT, RegionChoices.DEFAULT.id)
        assertEquals(RegionChoices.DEFAULT, RegionChoices.byId(null))
    }

    @Test
    fun `an unreadable value resolves to the default card rather than to a guess`() {
        assertEquals(RegionChoices.byId(UserRegion.INTERNATIONAL), RegionChoices.byId(" International "))
        assertEquals(RegionChoices.DEFAULT, RegionChoices.byId("klingon"))
        assertEquals(RegionChoices.DEFAULT, RegionChoices.byId(""))
    }

    @Test
    fun `desi dubs seeds hindi audio and english subtitles`() {
        val desi = RegionChoices.byId(UserRegion.DESI_DUBS)
        assertEquals("Hindi", desi.audioLanguage)
        assertEquals("English", desi.subtitleLanguage)
    }

    @Test
    fun `east asian keeps the original audio and asks only for subtitles`() {
        val eastAsian = RegionChoices.byId(UserRegion.EAST_ASIAN)
        assertNull("naming a preferred audio track would demote the original it exists to protect", eastAsian.audioLanguage)
        assertEquals("English", eastAsian.subtitleLanguage)
    }

    @Test
    fun `international seeds english audio and takes no subtitle stance`() {
        val international = RegionChoices.byId(UserRegion.INTERNATIONAL)
        assertEquals("English", international.audioLanguage)
        assertNull(international.subtitleLanguage)
    }

    @Test
    fun `a seeded language is a word the settings row can display`() {
        RegionChoices.ALL.forEach { choice ->
            choice.audioLanguage?.let { audio ->
                assertTrue("$audio is not an audio chip", audio in UserPreferences.AUDIO_LANGUAGE_OPTIONS)
            }
            choice.subtitleLanguage?.let { subtitle ->
                assertTrue("$subtitle is not a subtitle chip", subtitle in subtitleOptions)
            }
        }
    }

    @Test
    fun `the preference line states exactly what one write stores`() {
        assertEquals(
            "Prefers Hindi audio with English subtitles",
            RegionChoices.byId(UserRegion.DESI_DUBS).preferenceLine(),
        )
        assertEquals(
            "Keeps original audio, prefers English subtitles",
            RegionChoices.byId(UserRegion.EAST_ASIAN).preferenceLine(),
        )
        assertEquals(
            "Prefers English audio",
            RegionChoices.byId(UserRegion.INTERNATIONAL).preferenceLine(),
        )
    }

    @Test
    fun `no card sells content this catalog cannot serve`() {
        // classify_media() has no Pakistani-drama industry and no importer scrapes Hum, ARY or
        // Geo, so an offer of those serials would be a promise the server cannot keep.
        RegionChoices.ALL.forEach { choice ->
            choice.contents.forEach { line ->
                val lowered = line.lowercase()
                assertTrue(
                    "card ${choice.id} promises $line",
                    listOf("hum tv", "ary", "geo tv", "pakistani drama").none { lowered.contains(it) },
                )
            }
            assertTrue(choice.contents.isNotEmpty())
        }
        val caveat = RegionChoices.byId(UserRegion.DESI_DUBS).caveat
        assertTrue("the missing Pakistani dramas must be said, not omitted", caveat != null && caveat.contains("Pakistani"))
    }
}
