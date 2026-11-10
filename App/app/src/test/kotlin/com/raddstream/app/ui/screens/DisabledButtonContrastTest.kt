package com.raddstream.app.ui.screens

import androidx.compose.ui.graphics.compositeOver
import com.raddstream.app.ui.theme.RaddInk900
import com.raddstream.app.ui.theme.RaddPaperOnInk
import com.raddstream.app.ui.theme.contrastRatio
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Robo run 5: the two disabled Settings buttons ("Test & Save Connection"
 * with no server typed, "Sign in" with no key typed) read 2.98:1 — the M3
 * default disabled text (onSurface at 38%) on the dark fill, under the
 * 4.5:1 floor. The buttons now use onSurface at DisabledButtonContentAlpha
 * for their disabled text. This test pins the math against the real dark
 * theme colors (Robo runs the dark scheme): the disabled fill is onSurface
 * at 12% over the card's surface, the disabled text is onSurface at the
 * alpha over that fill, and the ratio must clear 4.5:1. It reads the same
 * alpha constant the buttons use, so lowering the alpha fails here first.
 * Plain JUnit — the contrast math is pure Kotlin, no composition needed.
 */
class DisabledButtonContrastTest {

    @Test
    fun disabledButtonTextMeetsContrastFloor() {
        // The card the buttons sit on is surface (RaddInk900); the M3
        // disabled fill is onSurface at 12% over it.
        val surface = RaddInk900
        val onSurface = RaddPaperOnInk
        val disabledContainer = onSurface.copy(alpha = 0.12f).compositeOver(surface)
        val disabledContent = onSurface.copy(alpha = DisabledButtonContentAlpha)
            .compositeOver(disabledContainer)
        val ratio = contrastRatio(disabledContent, disabledContainer)
        assertTrue(
            "disabled button text is only $ratio:1, under the 4.5:1 floor",
            ratio >= 4.5f,
        )
    }
}
