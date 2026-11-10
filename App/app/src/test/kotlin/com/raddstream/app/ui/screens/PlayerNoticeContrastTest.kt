package com.raddstream.app.ui.screens

import androidx.compose.ui.graphics.Color
import com.raddstream.app.ui.theme.RaddPlayerStage
import com.raddstream.app.ui.theme.contrastRatio
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Robo run 7: the "Warming the link" notice's title read 1.06:1. The old
 * plate was RaddHudCard — black at 60% — so over a bright frame it
 * composited to mid-grey, and the 65%-white title on that mid-grey is
 * ~3.5:1, under the 4.5:1 floor. The notice now sits on the solid stage
 * colour with a full-white title, and the 85% sub-lines clear the floor on
 * the same plate. Pins the plate/title pair so a future dimming fails here
 * first. Plain JUnit — the contrast math is pure Kotlin, no composition
 * needed. Follows the TextContrastTest pattern; luminance ignores alpha, so
 * a translucent colour is composited over the plate first.
 */
class PlayerNoticeContrastTest {

    /** This colour painted at its own alpha over opaque [bg], as the screen shows it. */
    private fun Color.over(bg: Color): Color = Color(
        red = alpha * red + (1f - alpha) * bg.red,
        green = alpha * green + (1f - alpha) * bg.green,
        blue = alpha * blue + (1f - alpha) * bg.blue,
    )

    @Test
    fun noticeTitleOnSolidPlateMeetsContrastFloor() {
        val ratio = contrastRatio(Color.White, RaddPlayerStage)
        assertTrue(
            "notice title on its plate is only $ratio:1, under the 7:1 bar",
            ratio >= 7f,
        )
    }

    @Test
    fun noticeSubLinesOnSolidPlateMeetContrastFloor() {
        val ratio = contrastRatio(Color.White.copy(alpha = 0.85f).over(RaddPlayerStage), RaddPlayerStage)
        assertTrue(
            "notice sub-lines on their plate are only $ratio:1, under the 4.5:1 floor",
            ratio >= 4.5f,
        )
    }
}
