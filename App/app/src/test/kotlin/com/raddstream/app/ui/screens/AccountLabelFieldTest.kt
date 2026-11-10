package com.raddstream.app.ui.screens

import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.junit4.createComposeRule
import com.raddstream.app.ui.theme.RaddStreamTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * Robo run 5: the Settings account label field was flagged as having no label
 * readable by screen readers, even though it carries a label. The label is
 * now paint-only (the SwitchRow pattern) and the field itself carries the
 * spoken name. This test pins it: exactly one node speaks the label, it is
 * the editable text field itself, and the description is a single entry —
 * not the label twice. Runs on the JVM under Robolectric because this project
 * has no emulator image.
 *
 * Requires an x86_64 runner. Robolectric's native runtime has no Linux/aarch64
 * build (robolectric/robolectric#9166) and it fails while the runner boots, so
 * the exclusion for ARM hosts lives in app/build.gradle.kts rather than here.
 */
@RunWith(RobolectricTestRunner::class)
class AccountLabelFieldTest {

    @get:Rule
    val compose = createComposeRule()

    @Test
    fun labelFieldSpeaksItsLabelOnce() {
        compose.setContent {
            RaddStreamTheme {
                AccountLabelField(value = "", onValueChange = {}, onSave = null)
            }
        }
        // Exactly one node speaks the label — the field, not a duplicate.
        val nodes = compose.onAllNodes(hasContentDescription("Label (optional)"))
        nodes.assertCountEquals(1)
        val node = nodes.fetchSemanticsNodes().single()
        // It is the editable text field itself.
        assertTrue(
            "the labelled node is not the editable text field",
            node.config.contains(SemanticsActions.SetText),
        )
        // And the description is a single entry, not the label twice.
        val descriptions = node.config[SemanticsProperties.ContentDescription]
        assertEquals(listOf("Label (optional)"), descriptions)
    }
}
