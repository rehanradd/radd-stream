package com.raddstream.app.viewmodel

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * D2.7: the Home trial note is a pure decision over the ledger countdown.
 * The screen renders the live days, never a hardcoded "3"; the note shows
 * only while the trial is genuinely running, the viewer is not VIP, and the
 * viewer has not dismissed it (dismissal persists — the note never returns).
 */
class TrialNoteTest {

    @Test
    fun `live trial shows whole days rounded up`() {
        // 2.5 days left reads as 3; 20 hours left reads as 1, never 0.
        assertEquals(3, trialNoteDaysRemaining(2.5 * 86_400.0, isVip = false, dismissed = false))
        assertEquals(1, trialNoteDaysRemaining(20 * 3600.0, isVip = false, dismissed = false))
        assertEquals(1, trialNoteDaysRemaining(1.0, isVip = false, dismissed = false))
    }

    @Test
    fun `no grant or finished trial shows nothing`() {
        assertNull(trialNoteDaysRemaining(null, isVip = false, dismissed = false))
        assertNull(trialNoteDaysRemaining(0.0, isVip = false, dismissed = false))
        assertNull(trialNoteDaysRemaining(-5.0, isVip = false, dismissed = false))
    }

    @Test
    fun `vip never sees the note`() {
        assertNull(trialNoteDaysRemaining(3 * 86_400.0, isVip = true, dismissed = false))
    }

    @Test
    fun `a dismissed note never returns`() {
        assertNull(trialNoteDaysRemaining(3 * 86_400.0, isVip = false, dismissed = true))
    }
}
