package com.raddstream.app.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.ui.test.assertIsOff
import androidx.compose.ui.test.assertIsOn
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.junit4.createComposeRule
import com.raddstream.app.ui.theme.RaddStreamTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * UI-layer half of the Robo run-4 a11y fix (Session 132): two Settings toggles
 * still announced a bare "On" in Robo run 4 — the run-3 fix put the label on
 * the row ("<label>, on/off") but the Switch's own toggleable node is what a
 * screen reader hears, and it only announced its state. The Switch itself now
 * carries the label as its spoken name, and its toggleable state is what
 * announces on/off. This test pins it: each toggle speaks its own label, and
 * no bare "On" node remains. Runs on the JVM under Robolectric because this
 * project has no emulator image.
 *
 * Requires an x86_64 runner. Robolectric's native runtime has no Linux/aarch64
 * build (robolectric/robolectric#9166) and it fails while the runner boots, so
 * the exclusion for ARM hosts lives in app/build.gradle.kts rather than here.
 */
@RunWith(RobolectricTestRunner::class)
class SwitchRowTest {

    @get:Rule
    val compose = createComposeRule()

    @Test
    fun togglesSpeakTheirOwnLabels() {
        compose.setContent {
            RaddStreamTheme {
                Column {
                    SwitchRow(
                        checked = true,
                        onCheckedChange = {},
                        label = "Download only on Wi-Fi",
                    )
                    SwitchRow(
                        checked = true,
                        onCheckedChange = {},
                        label = "Delete watched downloads",
                    )
                }
            }
        }
        // Each toggle speaks its own label — not a bare "On" — and the two
        // are distinct, so a screen reader can tell them apart.
        compose.onNode(hasContentDescription("Download only on Wi-Fi"))
            .assertExists()
            .assertIsOn()
        compose.onNode(hasContentDescription("Delete watched downloads"))
            .assertExists()
            .assertIsOn()
        compose.onNode(hasContentDescription("On")).assertDoesNotExist()
    }

    @Test
    fun offToggleSpeaksItsLabel() {
        compose.setContent {
            RaddStreamTheme {
                SwitchRow(
                    checked = false,
                    onCheckedChange = {},
                    label = "Download only on Wi-Fi",
                )
            }
        }
        compose.onNode(hasContentDescription("Download only on Wi-Fi"))
            .assertExists()
            .assertIsOff()
        compose.onNode(hasContentDescription("On")).assertDoesNotExist()
        compose.onNode(hasContentDescription("Off")).assertDoesNotExist()
    }
}
