package com.raddstream.app.ui.theme

import androidx.compose.ui.unit.dp
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * RaddTokensTest — pins the benchmark §14 spec the token file promises, and
 * the Session 123 player-chrome fold that moved the HUD paints into brand
 * roles. Plain JUnit4 on the JVM: tokens are data, not composition.
 *
 * Deliberately no raw paint literals here: BrandDriftTest fails any file
 * outside Color.kt that writes one, and these assertions compare named values
 * against named values instead.
 */
class RaddTokensTest {

    @Test
    fun spacingIsTheEightPointGrid() {
        assertEquals(4.dp, RaddTokens.Space.Xs)
        assertEquals(8.dp, RaddTokens.Space.Sm)
        assertEquals(12.dp, RaddTokens.Space.Md)
        assertEquals(16.dp, RaddTokens.Space.Lg)
        assertEquals(20.dp, RaddTokens.Space.Step20)
        assertEquals(24.dp, RaddTokens.Space.Xl)
        assertEquals(32.dp, RaddTokens.Space.Xxl)
        assertEquals(48.dp, RaddTokens.Space.Step48)
    }

    @Test
    fun radiiFollowTheSpec() {
        assertEquals(8.dp, RaddTokens.Radius.Poster)
        assertEquals(8.dp, RaddTokens.Radius.Thumb)
        assertEquals(4.dp, RaddTokens.Radius.Chip)
        assertEquals(12.dp, RaddTokens.Radius.Input)
        assertEquals(16.dp, RaddTokens.Radius.Card)
        assertEquals(20.dp, RaddTokens.Radius.Sheet)
        assertEquals(999.dp, RaddTokens.Radius.Pill)
    }

    @Test
    fun motionDurationsAreTheBenchmarkNumbers() {
        assertEquals(120, RaddTokens.Motion.FastMs)
        assertEquals(200, RaddTokens.Motion.NormalMs)
        assertEquals(320, RaddTokens.Motion.SlowMs)
        assertEquals(400, RaddTokens.Motion.EmphasisMs)
        assertEquals(1500, RaddTokens.Motion.ShimmerMs)
        assertEquals(0.97f, RaddTokens.Motion.PressScale, 0.001f)
    }

    @Test
    fun touchTargetIsFortyEight() {
        assertEquals(48.dp, RaddTokens.Touch.MinTarget)
        assertEquals(8.dp, RaddTokens.Touch.MinGap)
    }

    @Test
    fun semanticColoursAreTheBrandRoles() {
        assertEquals(RaddCurrent500, RaddTokens.Color.Action)
        assertEquals(AccentOrange, RaddTokens.Color.PlayerAccent)
        assertEquals(RaddCoral400, RaddTokens.Color.Favourite)
        assertEquals(RaddTideIndigo, RaddTokens.Color.Download)
        assertEquals(RaddSignalGold, RaddTokens.Color.Signal)
        assertEquals(RaddSuccess, RaddTokens.Color.Success)
        assertEquals(RaddDanger, RaddTokens.Color.Danger)
        assertEquals(RaddWarning, RaddTokens.Color.Warning)
    }

    @Test
    fun playerChromeFoldKeepsThePlatesOnTheInkRamp() {
        assertEquals(RaddInk900, RaddPlayerStage)
        assertEquals(RaddInk850, RaddPlayerSheet)
        assertEquals(RaddInk800, RaddPlayerDialog)
        assertEquals(RaddSuccess, RaddNarrationCheck)
        assertEquals(RaddInk800.copy(alpha = 0.8f), RaddNarrationPlate)
        assertEquals(RaddInk800.copy(alpha = 0.9f), RaddPlayerSnackbarPlate)
        assertEquals(AccentOrange.copy(alpha = 0.8f), AccentOrangeToast)
    }

    @Test
    fun keepChipStatesAreMeaningColoursAtFortyPercent() {
        assertEquals(RaddSuccess.copy(alpha = 0.4f), RaddKeepStored)
        assertEquals(RaddDanger.copy(alpha = 0.4f), RaddKeepBlocked)
        assertEquals(RaddTideIndigo.copy(alpha = 0.4f), RaddKeepKeeping)
    }

    @Test
    fun typeAliasesAreTheShippedScale() {
        assertEquals(RaddTypography.displayLarge, RaddTokens.Type.Display)
        assertEquals(RaddTypography.headlineMedium, RaddTokens.Type.Headline)
        assertEquals(RaddTypography.titleMedium, RaddTokens.Type.Title)
        assertEquals(RaddTypography.bodyMedium, RaddTokens.Type.Body)
        assertEquals(RaddTypography.bodySmall, RaddTokens.Type.BodySmall)
        assertEquals(RaddTypography.labelSmall, RaddTokens.Type.Caption)
    }
}
