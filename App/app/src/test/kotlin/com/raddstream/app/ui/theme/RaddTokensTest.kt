package com.raddstream.app.ui.theme

import androidx.compose.ui.unit.dp
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
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
    fun motionKeepsOnlyThePressScale() {
        // Session 154 (T-1): the duration/easing/spring duplicates were
        // deleted — they were unused and their values did not match the
        // skill. The live motion system is RaddMotion (Theme.kt); only
        // PressScale survives here.
        assertEquals(0.97f, RaddTokens.Motion.PressScale, 0.001f)
    }

    @Test
    fun navIndicatorKeepsTheRoboMeasuredSizes() {
        // Session 154 (N-2): the 64×48dp pill and 80dp tab are deliberate,
        // not spec drift — Robo runs 4–6 measured the 32dp pill under the
        // 48dp touch floor. These pin the token; BottomNavTouchTargetTest
        // pins the rendered bar.
        assertEquals(64.dp, RaddTokens.Touch.NavIndicatorWidth)
        assertEquals(48.dp, RaddTokens.Touch.NavIndicatorHeight)
        assertEquals(80.dp, RaddTokens.Touch.NavTabHeight)
    }

    @Test
    fun slowDurationStaysInsideTheFiveHundredMillisecondCap() {
        // Session 154 (T-2): no transition may exceed about 500ms.
        assertTrue(RaddMotion.DurationSlow <= 500)
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
