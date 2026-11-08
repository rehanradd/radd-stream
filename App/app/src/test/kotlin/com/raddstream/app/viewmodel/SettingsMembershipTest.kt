package com.raddstream.app.viewmodel

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Session 114: the Membership card used to say "Free plan" while the Account
 * card on the same screen said free VIP days were running. A trial account IS
 * a VIP account on the server, so a running trial must never read as the free
 * plan here; when the trial ends it falls back to the free-plan wording.
 */
class SettingsMembershipTest {

    @Test
    fun `vip with a date names the date`() {
        val line = MembershipCardCopy.summary(
            planIsVip = true,
            planVipUntilMillis = 1_800_000_000_000L,
            planPaymentPending = false,
            trialDays = null,
        )
        assertTrue(line.startsWith("VIP — confirmed through "))
    }

    @Test
    fun `vip without a date still says active`() {
        assertEquals(
            "VIP — active.",
            MembershipCardCopy.summary(
                planIsVip = true,
                planVipUntilMillis = 0L,
                planPaymentPending = false,
                trialDays = null,
            ),
        )
    }

    @Test
    fun `a running trial says so and names what it unlocks`() {
        val line = MembershipCardCopy.summary(
            planIsVip = false,
            planVipUntilMillis = 0L,
            planPaymentPending = false,
            trialDays = 3,
        )
        assertTrue(line.startsWith(AccountCardCopy.trialActive(3)))
        assertTrue(line.contains("1080p and 4K play until the days end."))
    }

    @Test
    fun `a pending payment keeps its own wording`() {
        assertEquals(
            "Payment submitted — waiting for confirmation.",
            MembershipCardCopy.summary(
                planIsVip = false,
                planVipUntilMillis = 0L,
                planPaymentPending = true,
                trialDays = 3,
            ),
        )
    }

    @Test
    fun `no vip no trial falls back to the free plan`() {
        assertEquals(
            "Free plan — playback stays at 720p.",
            MembershipCardCopy.summary(
                planIsVip = false,
                planVipUntilMillis = 0L,
                planPaymentPending = false,
                trialDays = 0,
            ),
        )
    }
}
