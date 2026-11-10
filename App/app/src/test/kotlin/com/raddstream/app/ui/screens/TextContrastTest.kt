package com.raddstream.app.ui.screens

import com.raddstream.app.ui.theme.RaddCurrent500
import com.raddstream.app.ui.theme.RaddInk750
import com.raddstream.app.ui.theme.RaddInk800
import com.raddstream.app.ui.theme.RaddInk900
import com.raddstream.app.ui.theme.RaddInk950
import com.raddstream.app.ui.theme.RaddMistOnInk
import com.raddstream.app.ui.theme.RaddOnTideContainer
import com.raddstream.app.ui.theme.RaddPaperOnInk
import com.raddstream.app.ui.theme.RaddTideContainerDark
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

    @Test
    fun detailHeaderTitleOnBackgroundMeetsContrastFloor() {
        // Robo run 9 read 1.03:1 on two TextViews at the very top edge of the
        // Fall detail screen (fg #030404 on bg #07090B) — but those are the
        // theme's background (#06090B) and surface floor (#040708), not any
        // text colour: no Text in the app is painted dark-on-dark, and the
        // flagged nodes are header texts caught partially scrolled under the
        // bar, where ATF samples background pixels (the run-6 artifact
        // class). The real header pairs are pinned here, so a future
        // darkening of any of them fails here first. Title: onBackground on
        // background.
        val ratio = contrastRatio(RaddPaperOnInk, RaddInk950)
        assertTrue(
            "detail header title on background is only $ratio:1, under the 4.5:1 floor",
            ratio >= 4.5f,
        )
    }

    @Test
    fun detailHeaderMetaOnBackgroundMeetsContrastFloor() {
        // The meta line ("2022 · Movie · 1 season"): onSurfaceVariant on
        // background. Same run-9 artifact as the title above.
        val ratio = contrastRatio(RaddMistOnInk, RaddInk950)
        assertTrue(
            "detail header meta on background is only $ratio:1, under the 4.5:1 floor",
            ratio >= 4.5f,
        )
    }

    @Test
    fun detailHeaderIncludedLineOnBackgroundMeetsContrastFloor() {
        // The "Included with VIP" line: primary on background. Same run-9
        // artifact as the title above.
        val ratio = contrastRatio(RaddCurrent500, RaddInk950)
        assertTrue(
            "detail header included line on background is only $ratio:1, under the 4.5:1 floor",
            ratio >= 4.5f,
        )
    }

    @Test
    fun detailHeaderRatingPillMeetsContrastFloor() {
        // The "★ 6.4 IMDb" pill: onTertiaryContainer on tertiaryContainer.
        // Same run-9 artifact as the title above.
        val ratio = contrastRatio(RaddOnTideContainer, RaddTideContainerDark)
        assertTrue(
            "detail header rating pill is only $ratio:1, under the 4.5:1 floor",
            ratio >= 4.5f,
        )
    }
}
