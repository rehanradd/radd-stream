package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * JVM-only tests for the sleep timer's two modes and the fade curve. The ViewModel only feeds
 * ticks and multiplies the result by the user's own volume, so everything that decides WHEN the
 * screen goes dark and HOW the sound leaves is asserted here rather than on a device.
 */
class SleepTimerTest {

    private val fade = SleepTimerState.DEFAULT_FADE_MS

    @Test
    fun `a fresh timer is off and idle ticks change nothing`() {
        val timer = SleepTimer()
        assertEquals(SleepMode.OFF, timer.snapshot().mode)
        val tick = timer.onTick(1_000)
        assertEquals(1f, tick.volumeFactor, 0f)
        assertFalse(tick.shouldPause)
        assertFalse(tick.justFired)
    }

    @Test
    fun `countdown advances by the elapsed time it is given`() {
        val timer = SleepTimer()
        timer.start(60_000)
        assertEquals(SleepMode.COUNTDOWN, timer.snapshot().mode)
        assertEquals(60_000L, timer.snapshot().remainingMs)

        val tick = timer.onTick(15_000)
        assertEquals(45_000L, tick.state.remainingMs)
        assertEquals(1f, tick.volumeFactor, 0f)
        assertFalse(tick.justFired)
    }

    @Test
    fun `the fade is linear across the window and silent at the end`() {
        assertEquals(1f, SleepTimer.volumeFactorFor(fade + 10_000, fade), 0f)
        assertEquals(1f, SleepTimer.volumeFactorFor(fade, fade), 0f)
        assertEquals(0.5f, SleepTimer.volumeFactorFor(fade / 2, fade), 0.001f)
        assertEquals(0.25f, SleepTimer.volumeFactorFor(fade / 4, fade), 0.001f)
        assertEquals(0f, SleepTimer.volumeFactorFor(0, fade), 0f)
        assertEquals(0f, SleepTimer.volumeFactorFor(-5_000, fade), 0f)
    }

    @Test
    fun `a zero fade window cuts instead of ramping`() {
        assertEquals(1f, SleepTimer.volumeFactorFor(5_000, 0), 0f)
        assertEquals(0f, SleepTimer.volumeFactorFor(0, 0), 0f)
    }

    @Test
    fun `the last tick fires exactly once and drives the pause`() {
        val timer = SleepTimer()
        timer.start(90_000)
        val ramping = timer.onTick(90_000 - fade / 2)
        assertFalse(ramping.shouldPause)
        assertTrue(ramping.volumeFactor < 1f && ramping.volumeFactor > 0f)

        val fired = timer.onTick(fade / 2 + 1)
        assertEquals(0L, fired.state.remainingMs)
        assertEquals(0f, fired.volumeFactor, 0f)
        assertTrue(fired.shouldPause)
        assertTrue(fired.justFired)

        val after = timer.onTick(5_000)
        assertFalse(after.justFired)
    }

    @Test
    fun `starting a shorter timer replaces the longer one`() {
        val timer = SleepTimer()
        timer.start(90 * 60_000L)
        timer.start(5 * 60_000L)
        assertEquals(5 * 60_000L, timer.snapshot().remainingMs)
        assertEquals(1f, timer.onTick(0).volumeFactor, 0f)
    }

    @Test
    fun `end-of-video mode waits for the media boundary, not the clock`() {
        val timer = SleepTimer()
        timer.armEndOfVideo()
        assertEquals(SleepMode.END_OF_VIDEO, timer.snapshot().mode)
        val tick = timer.onTick(120_000)
        assertEquals(1f, tick.volumeFactor, 0f)
        assertFalse(tick.shouldPause)
        assertFalse(tick.justFired)
        assertEquals(0L, timer.snapshot().remainingMs)
    }

    @Test
    fun `cancel silences the timer and a fresh start re-arms the fade window`() {
        val timer = SleepTimer()
        timer.start(20_000)
        timer.cancel()
        assertEquals(SleepMode.OFF, timer.snapshot().mode)
        assertEquals(1f, timer.onTick(20_000).volumeFactor, 0f)
        timer.start(20_000)
        assertEquals(SleepMode.COUNTDOWN, timer.snapshot().mode)
    }

    @Test
    fun `the menu presets are whole minutes in ascending order`() {
        val minutes = SleepTimerState.PRESETS_MS.map { it / 60_000L }
        assertEquals(listOf(5L, 10L, 15L, 30L, 45L, 60L, 90L, 120L), minutes)
    }
}
