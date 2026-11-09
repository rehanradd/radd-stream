package com.raddstream.app.viewmodel

import java.time.LocalDateTime
import java.time.ZoneId
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Session 123: "already claimed today" is read from the overview's
 * `last_counted_day`, not by spending a claim to learn it — and the day
 * rolls at 04:00 PKT, not at midnight, exactly as the server's `_day_bucket`
 * counts it. These tests pin the rollover: 02:00 still belongs to yesterday,
 * 05:00 belongs to today.
 */
class AccountStreakTest {

    private fun millis(year: Int, month: Int, day: Int, hour: Int, minute: Int = 0): Long =
        LocalDateTime.of(year, month, day, hour, minute)
            .atZone(ZoneId.of("Asia/Karachi")).toInstant().toEpochMilli()

    @Test
    fun `a claim counted today reads as claimed`() {
        assertTrue(
            claimedTodayFor("2026-11-09", "Asia/Karachi", 4, millis(2026, 11, 9, 12)),
        )
    }

    @Test
    fun `a claim counted yesterday reads as not claimed`() {
        assertFalse(
            claimedTodayFor("2026-11-08", "Asia/Karachi", 4, millis(2026, 11, 9, 12)),
        )
    }

    @Test
    fun `two in the morning still belongs to yesterday's bucket`() {
        // 02:00 PKT on the 9th, boundary 04:00: the bucket is still the 8th,
        // so a claim counted on the 8th reads as claimed.
        assertTrue(
            claimedTodayFor("2026-11-08", "Asia/Karachi", 4, millis(2026, 11, 9, 2)),
        )
        assertFalse(
            claimedTodayFor("2026-11-09", "Asia/Karachi", 4, millis(2026, 11, 9, 2)),
        )
    }

    @Test
    fun `five in the morning belongs to today's bucket`() {
        assertTrue(
            claimedTodayFor("2026-11-09", "Asia/Karachi", 4, millis(2026, 11, 9, 5)),
        )
        assertFalse(
            claimedTodayFor("2026-11-08", "Asia/Karachi", 4, millis(2026, 11, 9, 5)),
        )
    }

    @Test
    fun `never claimed is never claimed today`() {
        assertFalse(claimedTodayFor(null, "Asia/Karachi", 4, millis(2026, 11, 9, 12)))
        assertFalse(claimedTodayFor("", "Asia/Karachi", 4, millis(2026, 11, 9, 12)))
    }

    @Test
    fun `an unreadable timezone falls back to Karachi`() {
        assertTrue(
            claimedTodayFor("2026-11-09", "Not/AZone", 4, millis(2026, 11, 9, 12)),
        )
    }
}
