package com.raddstream.app.viewmodel

import com.raddstream.app.network.models.PaymentReceipt
import com.raddstream.app.sync.PaymentFiled
import com.raddstream.app.sync.Refusal
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * What each filing attempt tells the viewer, and what it may keep on the device.
 *
 * The two assertions that matter most are about honesty rather than wording: only an
 * unreachable server is allowed to leave a draft behind (everything else means the operator's
 * queue has the claim or does not want it), and a reference the server refused must stay in the
 * field so the viewer can correct it instead of watching it vanish.
 */
class VipSubmissionTest {

    private fun accepted() = PaymentFiled.Accepted(
        PaymentReceipt(
            paymentId = 7,
            status = "pending",
            plan = "vip_monthly",
            amountPkr = 200,
            method = "jazzcash",
            submittedAt = 1_700_000_000.0,
        ),
    )

    @Test
    fun `an accepted claim clears the device copy and the field`() {
        val outcome = VipSubmission.outcome(accepted())
        assertFalse("a filed claim must not stay as a local draft", outcome.keepDraft)
        assertTrue(outcome.clearField)
        assertNull(outcome.tidError)
        // The sentence promises the operator's decision, never activation of anything.
        assertTrue(outcome.message, outcome.message.contains("operator"))
    }

    @Test
    fun `an unreachable server is the only failure that keeps the reference`() {
        listOf(Refusal.OFFLINE, Refusal.NO_SERVER).forEach { reason ->
            val outcome = VipSubmission.outcome(PaymentFiled.Refused(reason))
            assertTrue("$reason must keep the draft", outcome.keepDraft)
            assertTrue(outcome.message, outcome.message.contains("kept on this device"))
        }
    }

    @Test
    fun `a signed-out device keeps the draft and names the door to the account`() {
        val outcome = VipSubmission.outcome(PaymentFiled.Refused(Refusal.SIGNED_OUT))
        assertTrue(outcome.keepDraft)
        assertTrue(outcome.message, outcome.message.contains("Sign in"))
    }

    @Test
    fun `a refused reference stays on screen for one correction`() {
        val outcome = VipSubmission.outcome(PaymentFiled.Refused(Refusal.REJECTED))
        assertFalse("a refusal is not a draft", outcome.keepDraft)
        assertFalse("the viewer must be able to fix what they typed", outcome.clearField)
        assertNotNull(outcome.tidError)
    }

    @Test
    fun `the rate limit is explained as a wait and not as a failure`() {
        val outcome = VipSubmission.outcome(PaymentFiled.Refused(Refusal.THROTTLED))
        assertFalse(outcome.keepDraft)
        assertTrue(outcome.message, outcome.message.contains("Wait"))
    }

    @Test
    fun `no outcome ever claims VIP was granted`() {
        // One sentence is enough to sell a membership the app cannot switch on, so none of
        // them may read like an activation.
        val every = listOf(
            accepted(),
        ) + Refusal.entries.map { PaymentFiled.Refused(it) }
        every.forEach { filed ->
            val message = VipSubmission.outcome(filed).message.lowercase()
            assertFalse(message, "activated" in message || "vip is active" in message)
        }
    }
}
