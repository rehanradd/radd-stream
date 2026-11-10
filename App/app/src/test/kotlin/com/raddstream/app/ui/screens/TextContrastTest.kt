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

    @Test
    fun homeSectionHeaderTitleOnBackgroundMeetsContrastFloor() {
        // Robo run 10, issue 2: one low-contrast reading (1.04:1, fg #192927
        // on bg #172625) on a TextView directly under the Home ScrollView.
        // The reported fg/bg are theme surface tones (surfaceContainerHigh
        // #1E282B, surfaceContainer #141D20), not any text colour: the Home
        // SectionHeader title ("Your library") is onBackground on background
        // — the same pair the detail header pins above — and no Text in the
        // app is painted dark-on-dark. ATF sampled surface pixels, the run-6
        // / run-9 artifact class. Pinned here for the Home usage, so a future
        // darkening of the Home header fails here first.
        val ratio = contrastRatio(RaddPaperOnInk, RaddInk950)
        assertTrue(
            "home section header title on background is only $ratio:1, under the 4.5:1 floor",
            ratio >= 4.5f,
        )
    }

    @Test
    fun homeBrowserTileLabelOnSurfaceVariantMeetsContrastFloor() {
        // Robo run 10, issue 1: two low-contrast readings (1.04:1, fg
        // #1B2E2C on bg #1C312E; 1.33:1, fg #20282A on bg #07090B) on Text
        // nodes in the "Your library" BrowserStrip — the "Paste a video
        // link" / "On this phone" / "Downloads" tiles. The reported fg
        // #20282A is surfaceContainerHigh #1E282B to the pixel (luminance
        // 0.0199 vs 0.0197), the bg #07090B is the background #06090B, and
        // #1B2E2C/#1C312E sit in the shimmer placeholder range
        // (#10191C–#1C2A2E): ATF sampled surface/shimmer pixels, not the
        // label text. The real label is onSurfaceVariant on surfaceVariant
        // (the tile Surface's contentColor on its own color), 7.59:1. This
        // pair was the one Home pair no earlier test pinned.
        val ratio = contrastRatio(RaddMistOnInk, RaddInk800)
        assertTrue(
            "home browser tile label on surface variant is only $ratio:1, under the 4.5:1 floor",
            ratio >= 4.5f,
        )
    }

    @Test
    fun homePosterCardTitleOnSurfaceMeetsContrastFloor() {
        // Robo run 10, issue 3: three low-contrast readings (1.01–1.02:1)
        // on TextView[1] nodes in the Home rails — the poster card titles
        // (Kesariya@100 and its neighbours). The reported fg/bg are all
        // surface/surfaceContainer tones (#171E1E, #1A1A1B, #121E1D on
        // #161F1E, #1A1B1C, #121C1C), not any text colour: a PosterCard title
        // is onSurface on the card's surface, 15.45:1. ATF sampled the card
        // surface / poster pixels, the run-6 / run-9 artifact class. Pinned
        // here for the Home rail usage.
        val ratio = contrastRatio(RaddPaperOnInk, RaddInk900)
        assertTrue(
            "home poster card title on surface is only $ratio:1, under the 4.5:1 floor",
            ratio >= 4.5f,
        )
    }

    @Test
    fun homePosterCardDetailsOnSurfaceMeetsContrastFloor() {
        // Robo run 10, issue 3 (same three readings): the year · type line
        // under each poster card title. It is onSurfaceVariant on the card's
        // surface, 9.28:1 — the same pair the search/print cards pin above.
        // The flagged nodes are the card titles, but the details line shares
        // the card and the artifact, so it is pinned here too.
        val ratio = contrastRatio(RaddMistOnInk, RaddInk900)
        assertTrue(
            "home poster card details on surface is only $ratio:1, under the 4.5:1 floor",
            ratio >= 4.5f,
        )
    }
}
