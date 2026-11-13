package com.raddstream.app.viewmodel

import com.raddstream.app.player.SubtitleUiSettings
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The Languages screen shows the values in force, not the stored words — so the
 * mapping from stored values to screen state is pinned here, on this JVM, with no
 * DataStore and no screen: a stored pick wins, a viewer who never chose gets
 * their region's default, and a region with no stance on a row falls back to the
 * player's own pick for audio and off for subtitles. An explicit Off is a pick,
 * never a fallback, and the size is whatever the stored style says.
 *
 * The ViewModel itself has no test harness (no fake ServerSettingsRepository
 * exists anywhere; the save path is DataStore-backed), so this mapping is the
 * testable half — the same split Session 79 used for the Region screen.
 */
class LanguagesStateTest {

    private fun state(
        region: String = "desi_dubs",
        audio: String? = null,
        subtitle: String? = null,
        style: SubtitleUiSettings = SubtitleUiSettings(),
    ): LanguagesUiState = languagesStateOf(region, audio, subtitle, style)

    @Test
    fun `a stored pick beats the region default`() {
        assertEquals("Urdu", state(audio = "Urdu").audioLanguage)
        assertEquals("Off", state(subtitle = "Off").subtitleLanguage)
        assertEquals("Player default", state(audio = "Player default").audioLanguage)
    }

    @Test
    fun `a viewer who never chose gets the Desi default`() {
        val s = state()
        assertEquals("Hindi", s.audioLanguage)
        assertEquals("English", s.subtitleLanguage)
        assertEquals(100, s.subtitleSizePercent)
    }

    @Test
    fun `a region with no stance falls back to player default and off`() {
        val eastAsian = state(region = "east_asian")
        assertEquals("Player default", eastAsian.audioLanguage)
        assertEquals("English", eastAsian.subtitleLanguage)

        val international = state(region = "international")
        assertEquals("English", international.audioLanguage)
        assertEquals("Off", international.subtitleLanguage)
    }

    @Test
    fun `an explicit Off never falls back to the region English`() {
        assertEquals("Off", state(subtitle = "Off").subtitleLanguage)
        assertEquals("Off", state(region = "international", subtitle = "Off").subtitleLanguage)
    }

    @Test
    fun `a blank stored value falls back like null`() {
        assertEquals("Hindi", state(audio = "  ").audioLanguage)
        assertEquals("English", state(subtitle = "").subtitleLanguage)
    }

    @Test
    fun `the size is the stored style size`() {
        assertEquals(140, state(style = SubtitleUiSettings(sizePercent = 140)).subtitleSizePercent)
        assertEquals(50, state(style = SubtitleUiSettings(sizePercent = 50)).subtitleSizePercent)
        assertEquals(200, state(style = SubtitleUiSettings(sizePercent = 200)).subtitleSizePercent)
    }

    // F5a (Batch A): each language row names where its value came from, so the
    // Languages screen and the Settings card can never disagree without saying
    // why — the screenshot disagreement was a stored word ("Player default")
    // shown next to an effective value ("Hindi"), with no provenance on either.
    @Test
    fun `a stored pick is the viewers own choice`() {
        val s = state(audio = "Urdu", subtitle = "Off")
        assertEquals("your choice", s.audioProvenance)
        assertEquals("your choice", s.subtitleProvenance)
    }

    @Test
    fun `a stored Player default is still the viewers own choice`() {
        val s = state(audio = "Player default")
        assertEquals("Player default", s.audioLanguage)
        assertEquals("your choice", s.audioProvenance)
    }

    @Test
    fun `a viewer who never chose gets the region default provenance`() {
        val desi = state()
        assertEquals("Desi default", desi.audioProvenance)
        assertEquals("Desi default", desi.subtitleProvenance)

        assertEquals("East Asian default", state(region = "east_asian").audioProvenance)
        assertEquals("International default", state(region = "international").subtitleProvenance)
    }

    @Test
    fun `a blank stored value falls back to the region default provenance`() {
        assertEquals("Desi default", state(audio = "  ").audioProvenance)
        assertEquals("Desi default", state(subtitle = "").subtitleProvenance)
    }

    @Test
    fun `the other style fields do not leak into the state`() {
        val s = state(style = SubtitleUiSettings(sizePercent = 120, bold = true, delayMs = 4200))
        assertEquals(120, s.subtitleSizePercent)
        assertEquals("Hindi", s.audioLanguage)
    }
}
