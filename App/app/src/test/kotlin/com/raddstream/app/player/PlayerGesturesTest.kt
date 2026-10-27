package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * JVM-only tests for the pure gesture decision table. The Compose layer captures pointers and
 * delegates every meaning here, so the whole MX behaviour matrix is assertable without Android:
 * zones, dominance, lock, and the clamps that stop a swipe from seeking past the file.
 */
class PlayerGesturesTest {

    private val width = 1080f
    private val height = 1920f
    private val base = GestureSettings()

    @Test
    fun `tap zones are thirds of the width`() {
        assertEquals(ScreenZone.LEFT, tapZone(1f, width))
        assertEquals(ScreenZone.LEFT, tapZone(width / 3f - 1f, width))
        assertEquals(ScreenZone.CENTER, tapZone(width / 2f, width))
        assertEquals(ScreenZone.RIGHT, tapZone(width * 5f / 6f, width))
        assertEquals(ScreenZone.RIGHT, tapZone(width - 1f, width))
    }

    @Test
    fun `vertical drag zones are halves, not thirds`() {
        assertEquals(ScreenZone.LEFT, dragHalfZone(width / 2f - 1f, width))
        assertEquals(ScreenZone.RIGHT, dragHalfZone(width / 2f, width))
    }

    @Test
    fun `dominant axis needs the slop to be crossed`() {
        assertEquals(DominantAxis.NONE, dominantAxis(4f, 6f, slopPx = 16f))
        assertEquals(DominantAxis.HORIZONTAL, dominantAxis(120f, 20f))
        assertEquals(DominantAxis.VERTICAL, dominantAxis(20f, 120f))
    }

    @Test
    fun `single tap toggles controls and a lock silences it`() {
        assertEquals(TapCommand.ToggleControls, GestureMapper.onSingleTap(base))
        assertEquals(TapCommand.None, GestureMapper.onSingleTap(base.copy(lockGestures = true)))
    }

    @Test
    fun `double tap seeks on the sides and plays in the middle`() {
        val expected = GestureSettings(skipMs = 5_000L)
        assertEquals(
            TapCommand.SeekWithRipple(-5_000L, ScreenZone.LEFT),
            GestureMapper.onDoubleTap(10f, width, expected),
        )
        assertEquals(
            TapCommand.SeekWithRipple(5_000L, ScreenZone.RIGHT),
            GestureMapper.onDoubleTap(width - 10f, width, expected),
        )
        assertEquals(TapCommand.TogglePlayPause, GestureMapper.onDoubleTap(width / 2f, width, expected))
    }

    @Test
    fun `a centre double tap can fall back to controls, and lock wins over both`() {
        val noCenterPlay = GestureSettings(doubleTapCenterPlays = false)
        assertEquals(TapCommand.ToggleControls, GestureMapper.onDoubleTap(width / 2f, width, noCenterPlay))
        assertEquals(TapCommand.None, GestureMapper.onDoubleTap(10f, width, GestureSettings(lockGestures = true)))
    }

    @Test
    fun `long press boosts only when enabled and unlocked`() {
        assertTrue(GestureMapper.onLongPress(base))
        assertFalse(GestureMapper.onLongPress(base.copy(longPressBoostEnabled = false)))
        assertFalse(GestureMapper.onLongPress(base.copy(lockGestures = true)))
    }

    @Test
    fun `two-finger tap rewinds three seconds in ghost mode only`() {
        assertEquals(TapCommand.None, GestureMapper.onTwoFingerTap(base))

        val cinema = base.copy(pureCinema = true)
        assertEquals(
            TapCommand.SeekWithRipple(-3_000L, ScreenZone.LEFT),
            GestureMapper.onTwoFingerTap(cinema),
        )
        assertEquals(
            TapCommand.SeekWithRipple(-750L, ScreenZone.LEFT),
            GestureMapper.onTwoFingerTap(cinema.copy(cinemaRewindMs = 750L)),
        )
    }

    @Test
    fun `a locked ghost frame answers nothing, because no seek may hide behind the lock`() {
        assertEquals(
            TapCommand.None,
            GestureMapper.onTwoFingerTap(GestureSettings(pureCinema = true, lockGestures = true)),
        )
        assertEquals(
            TapCommand.None,
            GestureMapper.onTwoFingerTap(GestureSettings(pureCinema = true, cinemaRewindMs = 0L)),
        )
    }

    @Test
    fun `view mode cycles and an unknown stored name is the mode nobody opted into`() {
        assertEquals(ViewMode.PURE_CINEMA, ViewMode.nextOf(ViewMode.STANDARD))
        assertEquals(ViewMode.STANDARD, ViewMode.nextOf(ViewMode.PURE_CINEMA))
        assertEquals(ViewMode.STANDARD, ViewMode.fromName("STANDARD"))
        assertEquals(ViewMode.PURE_CINEMA, ViewMode.fromName("PURE_CINEMA"))
        assertEquals(ViewMode.STANDARD, ViewMode.fromName("CINEMA_MAX"))
        assertEquals(ViewMode.STANDARD, ViewMode.fromName(null))
        assertFalse(PlayerUiState().pureCinema)
        assertTrue(PlayerUiState(viewMode = ViewMode.PURE_CINEMA).pureCinema)
    }

    @Test
    fun `dragging up increases and the centre stays quiet`() {
        val left = GestureMapper.onVerticalDrag(ScreenZone.LEFT, -480f, height, base)
        assertTrue(left is DragCommand.BrightnessDelta && left.fractionPerSwipe > 0f)

        val right = GestureMapper.onVerticalDrag(ScreenZone.RIGHT, 480f, height, base)
        assertTrue(right is DragCommand.VolumeDelta && right.fractionPerSwipe < 0f)

        assertEquals(DragCommand.None, GestureMapper.onVerticalDrag(ScreenZone.CENTER, -480f, height, base))
        assertEquals(
            DragCommand.None,
            GestureMapper.onVerticalDrag(ScreenZone.LEFT, -480f, height, GestureSettings(lockGestures = true)),
        )
    }

    @Test
    fun `a full-width swipe moves a quarter of the duration and clamps to the file`() {
        val duration = 60_000L
        val forward = GestureMapper.onHorizontalScrub(10_000L, width, width, duration, base)
        assertEquals(DragCommand.ScrubTarget(25_000L, startedNewScrub = true), forward)

        // The width→jump mapping is linear, so a quarter-screen drag is a quarter of that jump.
        val small = GestureMapper.onHorizontalScrub(10_000L, width / 4f, width, duration, base)
        assertEquals(DragCommand.ScrubTarget(13_750L, startedNewScrub = true), small)

        val past = GestureMapper.onHorizontalScrub(55_000L, width, width, duration, base)
        assertTrue(past is DragCommand.ScrubTarget && past.targetMs == duration)

        val before = GestureMapper.onHorizontalScrub(2_000L, -width, width, duration, base)
        assertTrue(before is DragCommand.ScrubTarget && before.targetMs == 0L)
    }

    @Test
    fun `scrub and vertical gestures honour their own switches`() {
        assertEquals(
            DragCommand.None,
            GestureMapper.onHorizontalScrub(0L, 100f, width, 60_000L, GestureSettings(horizontalScrubEnabled = false)),
        )
        assertEquals(
            DragCommand.None,
            GestureMapper.onVerticalDrag(ScreenZone.RIGHT, -100f, height, GestureSettings(verticalGesturesEnabled = false)),
        )
        assertEquals(DragCommand.None, GestureMapper.onHorizontalScrub(0L, 100f, 0f, 60_000L, base))
        assertEquals(DragCommand.None, GestureMapper.onHorizontalScrub(0L, 100f, width, 0L, base))
    }

    @Test
    fun `pinch out fills and pinch in fits`() {
        assertEquals(PinchCommand.ZoomFill, GestureMapper.onPinch("out", base))
        assertEquals(PinchCommand.ZoomFit, GestureMapper.onPinch("in", base))
        assertEquals(PinchCommand.None, GestureMapper.onPinch("sideways", base))
        assertEquals(PinchCommand.None, GestureMapper.onPinch("out", GestureSettings(lockGestures = true)))
    }

    @Test
    fun `speed stays inside the menu range`() {
        assertEquals(0.25f, GestureMapper.clampedSpeed(0.01f), 0f)
        assertEquals(4.0f, GestureMapper.clampedSpeed(9f), 0f)
        assertEquals(1.75f, GestureMapper.clampedSpeed(1.75f), 0f)
        assertTrue(GestureMapper.SPEED_PRESETS.first() == 0.25f && GestureMapper.SPEED_PRESETS.last() == 4.0f)
    }
}
