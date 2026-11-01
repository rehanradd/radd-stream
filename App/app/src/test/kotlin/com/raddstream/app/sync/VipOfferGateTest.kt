package com.raddstream.app.sync

import com.raddstream.app.viewmodel.AccountCardCopy
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The rule Muse set on 2026-11-01: on a deployment whose `quality_gate` switch is off, the account
 * card keeps the trial countdown — it names a fact of the server's ledger — and stops offering the
 * free VIP day, because a day that unlocks nothing is not a thing worth offering.
 *
 * These are the paired kind the fleet asks for. The suppression is only half the claim; the other
 * half is that a gate-ON deployment still gets the exact words it always had, and that the countdown
 * was not quietly taken away along with the offer. A guard that asserted only the refusal would go
 * green the moment someone widened the suppression into hiding the trial itself.
 */
class VipOfferGateTest {

    @Test
    fun `a gated deployment offers the day in its historical words`() {
        assertEquals(
            "the offer line is the sentence this card has always shown",
            AccountCardCopy.LINK_BONUS,
            AccountCardCopy.bonusLine(qualityGateEnabled = true),
        )
        assertEquals(
            "and the button still names the day it is claiming",
            AccountCardCopy.LINK_BUTTON,
            AccountCardCopy.linkButton(qualityGateEnabled = true),
        )
    }

    @Test
    fun `an ungated deployment offers nothing it cannot deliver`() {
        assertNull(
            "no line at all, so the card cannot render an empty promise",
            AccountCardCopy.bonusLine(qualityGateEnabled = false),
        )
        val button = AccountCardCopy.linkButton(qualityGateEnabled = false)
        assertFalse("the button may not claim a day here: $button", button.contains("day"))
        assertFalse("and it is not the gate-on button", button == AccountCardCopy.LINK_BUTTON)
        assertTrue("it still says what the tap does: $button", button.contains("Link"))
    }

    /**
     * The other half of the ruling. The countdown takes only the days the server reported and never
     * sees the switch, so a lane that "simplifies" the card by hiding it on a gate-off deployment —
     * leaving a viewer without the day their trial ends — fails here.
     */
    @Test
    fun `the countdown is written without the switch and says the same thing either way`() {
        val model = source("viewmodel", "SettingsViewModel.kt")
        val offer = model.substringAfter("object AccountCardCopy {").substringBefore("\n}")
        assertTrue(
            "the countdown takes days only — no Boolean reaches it",
            Regex("""fun trialActive\(daysLeft: Int\)""").containsMatchIn(offer),
        )
        assertTrue("it still promises what it always did", offer.contains("Free VIP days are running"))
        assertEquals("three days", "3 days left.", AccountCardCopy.trialActive(3).substringAfter("— "))
        assertEquals("one day", "1 day left.", AccountCardCopy.trialActive(1).substringAfter("— "))
        assertFalse(
            "and the offer's switch never leaked into the clock",
            Regex("""fun trialActive\([^)]*Boolean""").containsMatchIn(offer),
        )
    }

    /**
     * The screen has to ask the rule rather than read the constant, or the copy owner is a no-op
     * with a nice name in it. Scanned as text because a Composable cannot be rendered on this
     * repository's only JVM — the same method the other guards in this package use.
     */
    @Test
    fun `the card asks the rule and never reads the bare offer constants`() {
        val screen = source("ui", "screens", "SettingsScreen.kt")
        assertTrue(
            "the offer goes through the rule",
            screen.contains("AccountCardCopy.bonusLine(account.qualityGateEnabled)"),
        )
        assertTrue(
            "and so does the button",
            screen.contains("AccountCardCopy.linkButton(account.qualityGateEnabled)"),
        )
        val bareReads = Regex("""AccountCardCopy\.(LINK_BONUS|LINK_BUTTON)\b""")
            .findAll(screen)
            .map { it.value }
            .toList()
        assertTrue("a bare read reintroduces the lie: $bareReads", bareReads.isEmpty())
        assertFalse(
            "the rule is asked, not restated beside the call",
            screen.contains("if (account.qualityGateEnabled) AccountCardCopy"),
        )
    }

    /** The view model must read the operator's stored answer rather than invent one. */
    @Test
    fun `the state carries the stored switch and is seeded so nothing is offered yet`() {
        val model = source("viewmodel", "SettingsViewModel.kt")
        assertTrue(
            "the switch arrives by the same collected flow the detail and player screens use",
            model.contains("settingsRepository.qualityGateEnabled.collect"),
        )
        assertTrue(
            "and cold it is off, so the offer cannot appear before the answer does",
            model.contains("val qualityGateEnabled: Boolean = false,"),
        )
    }

    private fun source(vararg path: String): String {
        val parts = listOf("src/main/kotlin/com/raddstream/app") + path
        val file = File(parts.joinToString("/"))
        assertTrue("${file.path} is gone — this guard has been looking at nothing", file.isFile)
        return file.readText()
    }
}
