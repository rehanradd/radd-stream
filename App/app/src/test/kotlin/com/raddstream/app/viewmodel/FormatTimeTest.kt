package com.raddstream.app.viewmodel

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The player clock (Session 117): `formatTime` divided the hours by 60 instead
 * of 3600, so every time shown at one minute or more was wrong — a 2 h 07 m 51 s
 * film printed "127:07:51" on the real device (127 = 7,671 s / 60), and a
 * 90-second position printed "1:01:30" instead of "1:30". The hours line is
 * the whole fix; these cases pin the retest's exact value and the boundaries
 * around it, so a future edit to the formatter cannot silently re-break the
 * one number every viewer reads.
 */
class FormatTimeTest {

    @Test
    fun `zero is zero minutes`() {
        assertEquals("0:00", 0L.formatTime())
    }

    @Test
    fun `under a minute is seconds only`() {
        assertEquals("0:45", 45_000L.formatTime())
    }

    @Test
    fun `ninety seconds is one thirty, not one hour one thirty`() {
        assertEquals("1:30", 90_000L.formatTime())
    }

    @Test
    fun `fifty-nine minutes fifty-nine seconds stays in minutes`() {
        assertEquals("59:59", 3_599_000L.formatTime())
    }

    @Test
    fun `one hour is one hour`() {
        assertEquals("1:00:00", 3_600_000L.formatTime())
    }

    @Test
    fun `one hour one minute one second`() {
        assertEquals("1:01:01", 3_661_000L.formatTime())
    }

    @Test
    fun `the retest film is two hours seven fifty-one`() {
        assertEquals("2:07:51", 7_671_000L.formatTime())
    }

    @Test
    fun `a day of footage is twenty-four hours`() {
        assertEquals("24:00:00", 86_400_000L.formatTime())
    }
}
