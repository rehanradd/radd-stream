package com.raddstream.app.ui.theme

import androidx.compose.ui.graphics.Color
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The operator's panel theme, resolved without an Activity: the mode string
 * and the accent hex are the only inputs, so a unit test can judge every
 * branch — including the typos a panel operator can actually type.
 */
class ThemeResolutionTest {

    @Test
    fun darkModeIsDarkWhateverTheSystemSays() {
        assertTrue(resolveThemeDark("dark", systemDark = false))
        assertTrue(resolveThemeDark("dark", systemDark = true))
    }

    @Test
    fun lightModeIsLightWhateverTheSystemSays() {
        assertFalse(resolveThemeDark("light", systemDark = false))
        assertFalse(resolveThemeDark("light", systemDark = true))
    }

    @Test
    fun systemModeFollowsTheSystem() {
        assertTrue(resolveThemeDark("system", systemDark = true))
        assertFalse(resolveThemeDark("system", systemDark = false))
    }

    @Test
    fun anUnknownModeFallsBackToDark() {
        assertTrue(resolveThemeDark("pink", systemDark = false))
        assertTrue(resolveThemeDark("", systemDark = false))
    }

    @Test
    fun emptyAccentMeansNoAccent() {
        assertNull(parseAccentHex(""))
    }

    @Test
    fun aValidHexAccentParsesToTheColour() {
        assertEquals(Color(0xFF2BC79A), parseAccentHex("#2BC79A"))
        assertEquals(Color(0xFF2BC79A), parseAccentHex("#2bc79a"))
    }

    @Test
    fun aTypoAccentParsesToNothing() {
        assertNull(parseAccentHex("red"))
        assertNull(parseAccentHex("#12345"))
        assertNull(parseAccentHex("#1234567"))
        assertNull(parseAccentHex("#GGGGGG"))
        assertNull(parseAccentHex("2BC79A"))
    }

    @Test
    fun theBrandJadeAccentTakesWhiteInk() {
        assertEquals(Color.White, accentOnPrimary(Color(0xFF2BC79A)))
        assertEquals(Color.White, accentOnPrimary(Color.Black))
    }

    @Test
    fun aLightAccentTakesTheDarkBrandInk() {
        assertEquals(Color(0xFF00281D), accentOnPrimary(Color.White))
        assertEquals(Color(0xFF00281D), accentOnPrimary(Color(0xFFF5E6C8)))
    }
}
