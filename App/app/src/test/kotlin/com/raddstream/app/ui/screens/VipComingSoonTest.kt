package com.raddstream.app.ui.screens

import androidx.compose.ui.test.assertDoesNotExist
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.raddstream.app.ui.theme.RaddStreamTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * App-design audit (2026-11-12, issues #8/#47): with no payment account
 * published, VIP shows "VIP is coming soon" — no prices to pick, no
 * accounts to copy, no transaction ID to submit. And a payment row with
 * no account behind it shows no copy icon at all.
 *
 * Runs on the JVM under Robolectric because this project has no emulator
 * image. Requires an x86_64 runner (robolectric/robolectric#9166).
 */
@RunWith(RobolectricTestRunner::class)
class VipComingSoonTest {

    @get:Rule
    val compose = createComposeRule()

    @Test
    fun comingSoonCardSaysSoAndShowsNoPurchaseForm() {
        compose.setContent {
            RaddStreamTheme {
                ComingSoonCard()
            }
        }
        compose.onNodeWithText("VIP is coming soon").assertIsDisplayed()
        compose.onNodeWithText("Transaction ID (TID)").assertDoesNotExist()
        compose.onNodeWithText("Submit for verification").assertDoesNotExist()
    }

    @Test
    fun unconfiguredRowHasNoCopyIcon() {
        compose.setContent {
            RaddStreamTheme {
                PaymentHandleRow(label = "JazzCash Merchant Till ID", value = "") { _, _ -> }
            }
        }
        compose.onNodeWithText("Not configured yet").assertIsDisplayed()
        compose.onNode(hasContentDescription("Copy JazzCash Merchant Till ID"))
            .assertDoesNotExist()
    }

    @Test
    fun configuredRowKeepsItsCopyIcon() {
        compose.setContent {
            RaddStreamTheme {
                PaymentHandleRow(label = "JazzCash Merchant Till ID", value = "7019882") { _, _ -> }
            }
        }
        compose.onNodeWithText("7019882").assertIsDisplayed()
        compose.onNode(hasContentDescription("Copy JazzCash Merchant Till ID"))
            .assertIsDisplayed()
    }
}
