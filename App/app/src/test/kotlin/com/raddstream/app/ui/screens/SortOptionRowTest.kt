package com.raddstream.app.ui.screens

import androidx.compose.ui.test.assertIsNotSelected
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.junit4.createComposeRule
import com.raddstream.app.ui.theme.RaddStreamTheme
import com.raddstream.app.viewmodel.SearchSort
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * UI-layer half of the Robo run-4 a11y fix (Session 132): run 3 embedded the
 * sort state in the row's spoken name ("Sort by Newest, selected") to stop
 * the four radios reading identically — and run 4 flagged that as an item-type
 * label, because a contentDescription must not carry state words. The row now
 * speaks the label only ("Sort by Newest") and the RadioButton's own `selected`
 * state is what a screen reader announces. This test pins both halves: the
 * spoken name has no state word, and the selected state is still present on
 * the merged node. Runs on the JVM under Robolectric because this project has
 * no emulator image.
 *
 * Requires an x86_64 runner. Robolectric's native runtime has no Linux/aarch64
 * build (robolectric/robolectric#9166) and it fails while the runner boots, so
 * the exclusion for ARM hosts lives in app/build.gradle.kts rather than here.
 */
@RunWith(RobolectricTestRunner::class)
class SortOptionRowTest {

    @get:Rule
    val compose = createComposeRule()

    @Test
    fun selectedRowSpeaksLabelWithoutStateWord() {
        compose.setContent {
            RaddStreamTheme {
                SortOptionRow(sort = SearchSort.NEWEST, selected = true, onSelect = {})
            }
        }
        compose.onNode(hasContentDescription("Sort by Newest"))
            .assertExists()
            .assertIsSelected()
        compose.onNode(hasContentDescription("Sort by Newest, selected"))
            .assertDoesNotExist()
        compose.onNode(hasContentDescription("Sort by Newest, not selected"))
            .assertDoesNotExist()
    }

    @Test
    fun unselectedRowSpeaksLabelWithoutStateWord() {
        compose.setContent {
            RaddStreamTheme {
                SortOptionRow(sort = SearchSort.MOST_SOURCES, selected = false, onSelect = {})
            }
        }
        compose.onNode(hasContentDescription("Sort by Most versions"))
            .assertExists()
            .assertIsNotSelected()
        compose.onNode(hasContentDescription("Sort by Most versions, selected"))
            .assertDoesNotExist()
        compose.onNode(hasContentDescription("Sort by Most versions, not selected"))
            .assertDoesNotExist()
    }
}
