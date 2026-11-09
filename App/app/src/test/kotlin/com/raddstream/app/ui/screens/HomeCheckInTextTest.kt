package com.raddstream.app.ui.screens

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The check-in card's wording, pinned (Session 123, HO-6/HO-8): the day
 * number is the server's claimed count, never the device's open count, and
 * the claim button states the amount today pays from the server's ladder.
 */
class HomeCheckInTextTest {

    private val ladder = mapOf(1 to 5, 2 to 5, 3 to 10, 4 to 10, 5 to 15, 6 to 15, 7 to 20)

    @Test
    fun `signed in with a server streak shows the server day`() {
        assertEquals(
            "Day 2 of 7 — claim today's coins to keep the streak going.",
            checkInDayLine(signedIn = true, serverStreak = 2, streakCount = 9, targetDays = 7),
        )
    }

    @Test
    fun `signed in before the overview answers prints no day number`() {
        assertEquals(
            "Claim today's coins to keep your streak going.",
            checkInDayLine(signedIn = true, serverStreak = null, streakCount = 9, targetDays = 7),
        )
    }

    @Test
    fun `a guest reads the honest local wording`() {
        assertEquals(
            "You've opened the app 9 days in a row.",
            checkInDayLine(signedIn = false, serverStreak = null, streakCount = 9, targetDays = 7),
        )
    }

    @Test
    fun `the claim states todays pay from the ladder`() {
        assertEquals(
            "Claim 10 coins for Day 3",
            claimButtonLabel(serverStreak = 2, streakLadder = ladder, isClaiming = false),
        )
    }

    @Test
    fun `claiming overrides the amount`() {
        assertEquals(
            "Claiming…",
            claimButtonLabel(serverStreak = 2, streakLadder = ladder, isClaiming = true),
        )
    }

    @Test
    fun `no ladder value means no amount promised`() {
        assertEquals(
            "Claim today's coins",
            claimButtonLabel(serverStreak = 2, streakLadder = emptyMap(), isClaiming = false),
        )
    }

    @Test
    fun `an unknown streak claims day one`() {
        assertEquals(
            "Claim 5 coins for Day 1",
            claimButtonLabel(serverStreak = null, streakLadder = ladder, isClaiming = false),
        )
    }
}
