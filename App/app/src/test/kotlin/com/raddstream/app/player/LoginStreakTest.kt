package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The login streak's day math (plan §5 step 19): one open a day is the whole streak, and a day is
 * the device's own calendar day, not a UTC one.
 */
class LoginStreakTest {

    private val day0 = 100L
    private val day1 = 101L

    @Test
    fun firstOpenStartsAtOne() {
        assertEquals(LoginStreak(lastDay = day0, count = 1), nextLoginStreak(LoginStreak(), day0))
    }

    @Test
    fun secondOpenSameDayChangesNothing() {
        val streak = LoginStreak(lastDay = day0, count = 3)
        assertEquals(streak, nextLoginStreak(streak, day0))
    }

    @Test
    fun nextDayAddsOne() {
        val streak = LoginStreak(lastDay = day0, count = 3)
        assertEquals(LoginStreak(lastDay = day1, count = 4), nextLoginStreak(streak, day1))
    }

    @Test
    fun missedDayRestartsAtOne() {
        val streak = LoginStreak(lastDay = day0, count = 5)
        assertEquals(LoginStreak(lastDay = day0 + 2, count = 1), nextLoginStreak(streak, day0 + 2))
    }

    @Test
    fun clockMovedBackNeverShortens() {
        val streak = LoginStreak(lastDay = day1, count = 4)
        assertEquals(streak, nextLoginStreak(streak, day0))
    }

    @Test
    fun localDayUsesTheOffsetNotUtc() {
        // 19:00 UTC is 00:00 the next day in PKT (+5h) and 14:00 the same day in EST (-5h).
        val nineteenUtcMs = 19L * 3_600_000L
        assertEquals(1L, localEpochDay(nineteenUtcMs, 5L * 3_600_000L))
        assertEquals(0L, localEpochDay(nineteenUtcMs, -5L * 3_600_000L))
    }

    @Test
    fun localDayBeforeEpochFloors() {
        // 00:00 UTC is 19:00 the previous day in EST (-5h): the day is -1, not 0 — a truncating
        // division would call it 0 and count a day that had not happened yet.
        assertEquals(-1L, localEpochDay(0L, -5L * 3_600_000L))
    }
}
