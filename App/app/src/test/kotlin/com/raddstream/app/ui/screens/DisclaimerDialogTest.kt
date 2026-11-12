package com.raddstream.app.ui.screens

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.raddstream.app.network.models.PanelDisclaimer
import com.raddstream.app.ui.theme.RaddStreamTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * Samsung RTL (v1.1.2, Issue 4): the first-run disclaimer dialog's text
 * overlapped and clipped — the long text ran over the buttons in an
 * AlertDialog whose text slot held an unbounded scrolling column. The
 * dialog is now a bounded layout (fixed title, weighted scrollable text,
 * buttons pinned in their own row), so however long the panel's text is,
 * the buttons stay on screen and reachable. This pins that with a
 * near-maximum-length text (the panel allows 4000 characters) the confirm
 * and decline buttons are both displayed, not pushed off the dialog.
 *
 * Runs on the JVM under Robolectric because this project has no emulator image.
 * Requires an x86_64 runner (robolectric/robolectric#9166); see
 * CatalogImageLoadingTest for the exclusion note.
 */
@RunWith(RobolectricTestRunner::class)
class DisclaimerDialogTest {

    @get:Rule
    val compose = createComposeRule()

    private val longText = ("Radd Stream is a media browser and video player. " +
        "It does not own, host, upload, or store any movie, show, video, or song. ")
        .repeat(30).take(4000)

    @Test
    fun firstRunDialogKeepsBothButtonsVisibleWithLongText() {
        compose.setContent {
            RaddStreamTheme {
                DisclaimerDialog(
                    disclaimer = PanelDisclaimer(
                        text = longText,
                        version = 1,
                        email = "radddao1@gmail.com",
                    ),
                    confirmLabel = "I understand",
                    onConfirm = {},
                    onDismissRequest = {},
                    dismissLabel = "Decline",
                    onDecline = {},
                )
            }
        }
        compose.onNodeWithText("I understand").assertIsDisplayed()
        compose.onNodeWithText("Decline").assertIsDisplayed()
        compose.onNodeWithText("Version 1").assertExists()
        compose.onNodeWithText("Contact: radddao1@gmail.com").assertExists()
    }

    @Test
    fun settingsDialogKeepsItsCloseButtonVisibleWithLongText() {
        compose.setContent {
            RaddStreamTheme {
                DisclaimerDialog(
                    disclaimer = PanelDisclaimer(
                        text = longText,
                        version = 1,
                        email = "radddao1@gmail.com",
                    ),
                    confirmLabel = "Close",
                    onConfirm = {},
                    onDismissRequest = {},
                )
            }
        }
        compose.onNodeWithText("Close").assertIsDisplayed()
    }
}
