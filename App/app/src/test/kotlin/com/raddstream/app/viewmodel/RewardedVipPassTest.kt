package com.raddstream.app.viewmodel

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RewardedVipPassTest {

    private val now = 1_700_000_000_000L
    private val fourHours = 4L * 60L * 60_000L

    @Test
    fun `a grant four hours ahead is active with the full window left`() {
        val expiresAt = now + fourHours
        assertTrue(RewardedVipPass.isActive(expiresAt, now))
        assertEquals(fourHours, RewardedVipPass.remainingMs(expiresAt, now))
    }

    @Test
    fun `the instant of expiry and anything after it is inactive`() {
        assertFalse(RewardedVipPass.isActive(now, now))
        assertFalse(RewardedVipPass.isActive(now - 1L, now))
        assertEquals(0L, RewardedVipPass.remainingMs(now - 1L, now))
    }

    @Test
    fun `a pass that was never granted is inactive`() {
        assertFalse(RewardedVipPass.isActive(0L, now))
    }

    @Test
    fun `human countdown keeps hours minutes and seconds`() {
        assertEquals("4h 0m 0s", RewardedVipPass.formatRemaining(fourHours))
        assertEquals("3h 59m 58s",
            RewardedVipPass.formatRemaining((3 * 3600 + 59 * 60 + 58) * 1000L))
        assertEquals("59m 58s", RewardedVipPass.formatRemaining((59 * 60 + 58) * 1000L))
        assertEquals("0m 1s", RewardedVipPass.formatRemaining(1L))
        assertEquals("0m 0s", RewardedVipPass.formatRemaining(0L))
    }

    @Test
    fun `a part-second remainder rounds up instead of showing zero early`() {
        assertEquals("0m 1s", RewardedVipPass.formatRemaining(1L))
        assertEquals("0m 1s", RewardedVipPass.formatRemaining(999L))
    }

    @Test
    fun `either promise silences a sponsor slot`() {
        // The paid card and the rewarded card both say, in words, that no sponsor break is owed.
        assertTrue(RewardedVipPass.isAdFree(serverVip = true, rewardedExpiresAt = 0L, now = now))
        assertTrue(RewardedVipPass.isAdFree(serverVip = false, rewardedExpiresAt = now + fourHours, now = now))
    }

    @Test
    fun `a lapsed membership with no pass is not ad-free`() {
        // `serverVip` is the ledger's live answer, so a membership that expired arrives here as
        // false; nothing in this function can age a paid grant on its own clock.
        assertFalse(RewardedVipPass.isAdFree(serverVip = false, rewardedExpiresAt = 0L, now = now))
        assertFalse(RewardedVipPass.isAdFree(serverVip = false, rewardedExpiresAt = now - 1L, now = now))
    }
}
