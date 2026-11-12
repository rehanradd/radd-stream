package com.raddstream.app.ui.screens

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Samsung RTL (v1.1.2, Issue 9): in landscape the detail page's Play
 * button ran off the right edge while the system navigation overlapped it —
 * the Scaffold's padding covers the status and navigation bars but not the
 * display cutout. The content padding takes the larger of the Scaffold's
 * ask and the safe-drawing inset per side, so the two are never
 * double-counted: portrait is unchanged, landscape clears the cutout.
 */
class DetailContentPaddingTest {

    @Test
    fun portraitIsUnchanged() {
        // No cutout, no system bars beyond what the Scaffold already asks:
        // 16 dp sides, Scaffold top, Scaffold bottom + 40 dp breathing room.
        val padding = detailContentPadding(
            scaffoldPadding = PaddingValues(top = 64.dp, bottom = 24.dp),
            safeDrawingPadding = PaddingValues(0.dp),
            layoutDirection = LayoutDirection.Ltr,
        )
        assertEquals(16.dp, padding.calculateStartPadding(LayoutDirection.Ltr))
        assertEquals(16.dp, padding.calculateEndPadding(LayoutDirection.Ltr))
        assertEquals(64.dp, padding.calculateTopPadding())
        assertEquals(64.dp, padding.calculateBottomPadding())
    }

    @Test
    fun landscapeCutoutWinsOverTheBaseMargin() {
        // A camera hole intruding 28 dp from the start side in landscape:
        // the content starts at 28 dp, not 16 dp, so nothing sits under it.
        val padding = detailContentPadding(
            scaffoldPadding = PaddingValues(top = 0.dp, bottom = 20.dp),
            safeDrawingPadding = PaddingValues(start = 28.dp, bottom = 20.dp),
            layoutDirection = LayoutDirection.Ltr,
        )
        assertEquals(28.dp, padding.calculateStartPadding(LayoutDirection.Ltr))
        assertEquals(16.dp, padding.calculateEndPadding(LayoutDirection.Ltr))
        assertEquals(60.dp, padding.calculateBottomPadding())
    }

    @Test
    fun endCutoutWinsOnTheOtherRotation() {
        // Rotated the other way, the hole is on the end side instead.
        val padding = detailContentPadding(
            scaffoldPadding = PaddingValues(top = 0.dp, bottom = 20.dp),
            safeDrawingPadding = PaddingValues(end = 28.dp, bottom = 20.dp),
            layoutDirection = LayoutDirection.Ltr,
        )
        assertEquals(16.dp, padding.calculateStartPadding(LayoutDirection.Ltr))
        assertEquals(28.dp, padding.calculateEndPadding(LayoutDirection.Ltr))
    }

    @Test
    fun insetsAreNeverDoubleCounted() {
        // The Scaffold already asks for 48 dp at the bottom (navigation
        // bar) and safe drawing asks for the same 48 dp: the content gets
        // 48 dp + 40 dp of breathing room, not 48 + 48 + 40.
        val padding = detailContentPadding(
            scaffoldPadding = PaddingValues(top = 24.dp, bottom = 48.dp),
            safeDrawingPadding = PaddingValues(top = 24.dp, bottom = 48.dp),
            layoutDirection = LayoutDirection.Ltr,
        )
        assertEquals(24.dp, padding.calculateTopPadding())
        assertEquals(88.dp, padding.calculateBottomPadding())
    }

    @Test
    fun rtlKeepsStartAndEndStraight() {
        val padding = detailContentPadding(
            scaffoldPadding = PaddingValues(0.dp),
            safeDrawingPadding = PaddingValues(start = 28.dp),
            layoutDirection = LayoutDirection.Rtl,
        )
        assertEquals(28.dp, padding.calculateStartPadding(LayoutDirection.Rtl))
        assertEquals(16.dp, padding.calculateEndPadding(LayoutDirection.Rtl))
    }
}
