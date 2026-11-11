package com.raddstream.app.ui.screens

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performTextInput
import com.raddstream.app.ui.theme.RaddStreamTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * App-design audit (2026-11-12, issue #33): typing "av" rendered the
 * green hint "Search movies and shows" ABOVE the white "av" — the field
 * carried both a label and a placeholder with the same text, so the label
 * floated instead of vanishing. The hint must disappear the moment the
 * first character is typed.
 *
 * Runs on the JVM under Robolectric because this project has no emulator
 * image. Requires an x86_64 runner (robolectric/robolectric#9166).
 */
@RunWith(RobolectricTestRunner::class)
class SearchFieldHintTest {

    @get:Rule
    val compose = createComposeRule()

    @Test
    fun hintIsVisibleWhenEmpty() {
        compose.setContent {
            RaddStreamTheme {
                SearchField(query = "", onQueryChanged = {}, onSubmit = {})
            }
        }
        compose.onNodeWithText("Search movies and shows").assertIsDisplayed()
    }

    @Test
    fun hintDisappearsAfterOneCharacter() {
        var query by mutableStateOf("")
        compose.setContent {
            RaddStreamTheme {
                SearchField(query = query, onQueryChanged = { query = it }, onSubmit = {})
            }
        }
        compose.onNodeWithContentDescription("Search movies and shows")
            .performTextInput("a")
        compose.onNodeWithText("Search movies and shows").assertDoesNotExist()
        compose.onNodeWithText("a").assertIsDisplayed()
    }
}
