package com.raddstream.app.ui.screens

import com.raddstream.app.ui.theme.RaddInk750
import com.raddstream.app.ui.theme.RaddInk800
import com.raddstream.app.ui.theme.RaddInk900
import com.raddstream.app.ui.theme.RaddMistOnInk
import com.raddstream.app.ui.theme.RaddPaperOnInk
import com.raddstream.app.ui.theme.RaddWhisperOnInk
import com.raddstream.app.ui.theme.contrastRatio
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Robo run 6 reported three low-contrast readings on near-black text
 * (1.01, 1.41, 1.09) — but the measured foregrounds (#0D1215, #2A3234,
 * #13181B) match the theme's SURFACE colours, not any text colour: no Text
 * in the app is painted in a dark colour on a dark background, and the
 * console itself notes two of the three elements were only partially
 * visible (a cut-off card at the scroll edge, a sliver below the fold) or a
 * skeleton/shimmer line. ATF pixel-sampled background/shimmer pixels, not
 * real text. This test pins the real theme pairs — the colours the text
 * actually uses — so a future darkening of any of them fails here first.
 * Plain JUnit — the contrast math is pure Kotlin, no composition needed.
 * Follows the DisabledButtonContrastTest pattern.
 */
class TextContrastTest {

    @Test
    fun primaryTextOnSurfaceMeetsContrastFloor() {
        // The detail print cards, the search cards, the empty-library card:
        // primary text on the surface tier.
        val ratio = contrastRatio(RaddPaperOnInk, RaddInk900)
        assertTrue(
            "primary text on surface is only $ratio:1, under the 4.5:1 floor",
            ratio >= 4.5f,
        )
    }

    @Test
    fun secondaryTextOnSurfaceMeetsContrastFloor() {
        // The dim grey line on the print cards ("Standard · Plays here",
        // the rung subtext, the section subtitles): onSurfaceVariant on
        // the surface tier. Robo run 6 read 1.41 for this line — but the
        // measured fg #2A3234 is a surface colour, not this text colour.
        val ratio = contrastRatio(RaddMistOnInk, RaddInk900)
        assertTrue(
            "secondary text on surface is only $ratio:1, under the 4.5:1 floor",
            ratio >= 4.5f,
        )
    }

    @Test
    fun mutedTextOnContainerHighMeetsContrastFloor() {
        // Muted metadata (year, source, timestamps) on chips and inputs.
        val ratio = contrastRatio(RaddWhisperOnInk, RaddInk800)
        assertTrue(
            "muted text on container high is only $ratio:1, under the 4.5:1 floor",
            ratio >= 4.5f,
        )
    }

    @Test
    fun primaryTextOnBrightestRaisedTierMeetsContrastFloor() {
        // Primary text on the brightest raised tier (dialogs, FABs on ink).
        val ratio = contrastRatio(RaddPaperOnInk, RaddInk750)
        assertTrue(
            "primary text on the brightest raised tier is only $ratio:1, under the 4.5:1 floor",
            ratio >= 4.5f,
        )
    }
}
