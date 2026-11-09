package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Session 123 (PL-1): the autoplay-next countdown is pure state — the ten
 * seconds between an episode's end and the advance, one tick at a time.
 * The test runs the whole countdown without a clock: 10 down to 1, then
 * null, the moment the advance fires. A cancelled countdown is simply
 * dropped, never ticked — there is nothing to test in a dropped object.
 */
class AutoplayCountdownTest {

    @Test
    fun `countdown starts at ten seconds`() {
        assertEquals(10, AutoplayCountdown.start().secondsLeft)
        assertEquals(AUTOPLAY_COUNTDOWN_SECONDS, AutoplayCountdown.start().secondsLeft)
    }

    @Test
    fun `tick walks down one second at a time`() {
        var countdown: AutoplayCountdown? = AutoplayCountdown.start()
        for (expected in 9 downTo 1) {
            countdown = countdown?.tick()
            assertEquals(expected, countdown?.secondsLeft)
        }
    }

    @Test
    fun `tick at one second returns null, the advance moment`() {
        assertNull(AutoplayCountdown(1).tick())
    }

    @Test
    fun `tick never goes below one`() {
        var countdown: AutoplayCountdown? = AutoplayCountdown.start()
        repeat(20) { countdown = countdown?.tick() }
        assertNull(countdown)
    }
}
