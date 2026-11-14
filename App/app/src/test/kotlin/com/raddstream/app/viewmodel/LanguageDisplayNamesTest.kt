package com.raddstream.app.viewmodel

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * F23 (Batch B): every language the lists can show carries its name in its
 * own script — and the stored value stays the English name, so these are
 * display-only mappings, never a second spelling of the preference.
 */
class LanguageDisplayNamesTest {

    @Test
    fun hindiTamilAndKannadaHaveNativeScripts() {
        assertEquals("हिन्दी", nativeScriptName("Hindi"))
        assertEquals("தமிழ்", nativeScriptName("Tamil"))
        assertEquals("ಕನ್ನಡ", nativeScriptName("Kannada"))
    }

    @Test
    fun urduReadsRightToLeftInItsOwnScript() {
        assertEquals("اردو", nativeScriptName("Urdu"))
    }

    @Test
    fun englishAndPlayerDefaultHaveNoNativeScript() {
        assertNull(nativeScriptName("English"))
        assertNull(nativeScriptName("Player default"))
        assertNull(nativeScriptName("Off"))
    }

    @Test
    fun theChipLabelCarriesBothScripts() {
        assertEquals("Hindi · हिन्दी", displayLanguageName("Hindi"))
        assertEquals("Kannada · ಕನ್ನಡ", displayLanguageName("Kannada"))
    }

    @Test
    fun aLanguageWithNoNativeScriptPaintsItsBareName() {
        assertEquals("English", displayLanguageName("English"))
        assertEquals("Japanese", displayLanguageName("Japanese"))
    }

    @Test
    fun everySearchLanguageHasANativeScriptExceptEnglish() {
        LanguageFilter.entries.filter { it != LanguageFilter.ALL }.forEach { filter ->
            assertTrue(
                "LanguageFilter.${filter.name} is not English but has no native script",
                filter.label == "English" || nativeScriptName(filter.label) != null,
            )
        }
    }

    @Test
    fun kannadaIsInBothOptionLists() {
        assertTrue("Kannada" in UserPreferences.AUDIO_LANGUAGE_OPTIONS)
        assertTrue("Kannada" in com.raddstream.app.ui.screens.subtitleOptions)
    }
}
