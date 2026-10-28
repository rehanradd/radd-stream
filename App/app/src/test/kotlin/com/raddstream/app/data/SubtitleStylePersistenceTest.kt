package com.raddstream.app.data

import com.raddstream.app.player.SubtitleColor
import com.raddstream.app.player.SubtitleUiSettings
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The subtitle look is a stored preference now, so the rules about what a stored value MEANS
 * are testable on this JVM without a DataStore, a Context, or a screen: a viewer who picks
 * yellow and closes the app must get yellow back, and a store holding something this build
 * never wrote must answer with the shipped look rather than a guess.
 *
 * The sync offset is pinned here too, because forgetting why it is not stored is how it ends
 * up stored: it is a correction to one file, not a taste.
 */
class SubtitleStylePersistenceTest {

    @Test
    fun `an untouched store answers the shipped look`() {
        val stored = subtitleStyleOf(null, null, null, null, null)
        assertEquals(DEFAULT_SUBTITLE_STYLE, stored)
        assertEquals(100, stored.sizePercent)
        assertEquals(0.05f, stored.bottomFraction, 0f)
        assertFalse(stored.bold)
        assertTrue(stored.textBackground)
        assertEquals(SubtitleColor.WHITE, stored.colour)
        assertEquals(0L, stored.delayMs)
    }

    @Test
    fun `every field the sheet offers survives the store`() {
        val chosen = SubtitleUiSettings(
            sizePercent = 140,
            bottomFraction = 0.22f,
            bold = true,
            textBackground = false,
            colour = SubtitleColor.CYAN,
        )
        val stored = subtitleStyleOf(
            sizePercent = chosen.sizePercent,
            bottomFraction = chosen.bottomFraction,
            bold = chosen.bold,
            textBackground = chosen.textBackground,
            colour = chosen.colour.wireName,
        )
        assertEquals(chosen, stored)
    }

    @Test
    fun `a colour name this build has never seen falls back to the shipped one`() {
        listOf("chartreuse", "", "   ", null).forEach { junk ->
            assertEquals("store value <$junk>", SubtitleColor.WHITE, SubtitleColor.fromWire(junk))
        }
    }

    @Test
    fun `a stored colour name is read however the store happened to keep it`() {
        assertEquals(SubtitleColor.YELLOW, SubtitleColor.fromWire("yellow"))
        assertEquals(SubtitleColor.YELLOW, SubtitleColor.fromWire(" YELLOW "))
        assertEquals(SubtitleColor.PINK, SubtitleColor.fromWire("Pink"))
        SubtitleColor.entries.forEach { colour ->
            assertEquals(colour, SubtitleColor.fromWire(colour.wireName))
        }
    }

    @Test
    fun `a number an older build could not have written is clamped back into range`() {
        val wild = subtitleStyleOf(sizePercent = 9_000, bottomFraction = 0.9f, bold = null, textBackground = null, colour = null)
        assertEquals(200, wild.sizePercent)
        assertEquals(0.4f, wild.bottomFraction, 0f)
        val negative = subtitleStyleOf(sizePercent = -5, bottomFraction = -1f, bold = null, textBackground = null, colour = null)
        assertEquals(50, negative.sizePercent)
        assertEquals(0f, negative.bottomFraction, 0f)
    }

    @Test
    fun `a position that is not a number never reaches a renderer`() {
        val broken = subtitleStyleOf(
            sizePercent = 120,
            bottomFraction = Float.NaN,
            bold = true,
            textBackground = true,
            colour = "cyan",
        )
        assertEquals(0.05f, broken.bottomFraction, 0f)
        assertEquals(SubtitleColor.CYAN, broken.colour)
        assertTrue(broken.bold)
    }

    @Test
    fun `the stored look cannot reset the sync offset of the viewing in progress`() {
        val watching = SubtitleUiSettings(delayMs = 4_200L, sizePercent = 80)
        val reloaded = subtitleStyleOf(120, 0.1f, true, false, "pink").withDelay(watching.delayMs)
        assertEquals(4_200L, reloaded.delayMs)
        assertEquals(120, reloaded.sizePercent)
        assertEquals(SubtitleColor.PINK, reloaded.colour)
        assertFalse(reloaded.textBackground)
    }

    @Test
    fun `each offered colour has its own name and its own label`() {
        val names = SubtitleColor.entries.map { it.wireName }
        val labels = SubtitleColor.entries.map { it.label }
        assertEquals(names.size, names.distinct().size)
        assertEquals(labels.size, labels.distinct().size)
        SubtitleColor.entries.forEach { colour ->
            assertTrue("${colour.name} has no label", colour.label.isNotBlank())
            assertTrue("${colour.name} has no wire name", colour.wireName.isNotBlank())
        }
    }

    @Test
    fun `every colour the sheet offers reads on a bright picture`() {
        // The plate is a switch the viewer can turn off, so a caption colour has to survive
        // white snow on its own. Rec.709 luma is the honest measure of that; anything dimmer
        // than this floor belongs behind the plate and must not be offered as a choice.
        SubtitleColor.entries.forEach { colour ->
            val luma = 0.2126f * colour.red / 255f + 0.7152f * colour.green / 255f + 0.0722f * colour.blue / 255f
            assertTrue("${colour.name} is too dark to offer without a plate (luma $luma)", luma > 0.55f)
            assertEquals("${colour.name} must be opaque", 0xFF, colour.argb ushr 24)
            assertEquals(colour.red, (colour.argb shr 16) and 0xFF)
            assertEquals(colour.green, (colour.argb shr 8) and 0xFF)
            assertEquals(colour.blue, colour.argb and 0xFF)
        }
    }
}
