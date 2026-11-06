package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * The language defaults (user order 2026-11-06): a stored pick always wins; only a viewer
 * who never chose falls back to their region — and an explicit Off or "Player default" is a
 * stored pick, not a never-chose.
 */
class LanguageDefaultsTest {

    @Test
    fun storedPickBeatsTheRegion() {
        assertEquals("Urdu", LanguageDefaults.effectiveAudioLanguage("Urdu", "desi_dubs"))
        assertEquals("Off", LanguageDefaults.effectiveSubtitleLanguage("Off", "desi_dubs"))
        assertEquals(
            "Player default",
            LanguageDefaults.effectiveAudioLanguage("Player default", "desi_dubs"),
        )
    }

    @Test
    fun blankStoredFallsBackLikeNull() {
        assertEquals("Hindi", LanguageDefaults.effectiveAudioLanguage("  ", "desi_dubs"))
        assertEquals("English", LanguageDefaults.effectiveSubtitleLanguage("", "desi_dubs"))
    }

    @Test
    fun desiDefaultsAreHindiAudioEnglishSubtitles() {
        assertEquals("Hindi", LanguageDefaults.effectiveAudioLanguage(null, "desi_dubs"))
        assertEquals("English", LanguageDefaults.effectiveSubtitleLanguage(null, "desi_dubs"))
        assertEquals("Urdu", LanguageDefaults.effectiveAudioFallback("desi_dubs"))
    }

    @Test
    fun internationalDefaultsAreEnglishAudioNoSubtitleStance() {
        assertEquals("English", LanguageDefaults.effectiveAudioLanguage(null, "international"))
        assertNull(LanguageDefaults.effectiveSubtitleLanguage(null, "international"))
        assertNull(LanguageDefaults.effectiveAudioFallback("international"))
    }

    @Test
    fun eastAsianKeepsOriginalAudioEnglishSubtitles() {
        assertNull(LanguageDefaults.effectiveAudioLanguage(null, "east_asian"))
        assertEquals("English", LanguageDefaults.effectiveSubtitleLanguage(null, "east_asian"))
        assertNull(LanguageDefaults.effectiveAudioFallback("east_asian"))
    }

    @Test
    fun unknownRegionFallsBackToDesi() {
        assertEquals("Hindi", LanguageDefaults.effectiveAudioLanguage(null, "nowhere"))
        assertEquals("English", LanguageDefaults.effectiveSubtitleLanguage(null, "nowhere"))
    }
}
