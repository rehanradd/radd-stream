package com.raddstream.app.ui.components

import androidx.compose.foundation.layout.Column
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.junit4.createComposeRule
import com.raddstream.app.ui.theme.RaddStreamTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * Robo run 6: every Home rail's "See all" announced identically — the Movies
 * link and the Series link both said bare "See all", so a screen reader could
 * not tell them apart. Each rail's button now speaks its section ("See all
 * Movies") while the painted text stays the short "See all". The button
 * carries the name and the painted text is silent, so it is heard exactly
 * once (the SwitchRow pattern).
 */
@RunWith(RobolectricTestRunner::class)
class SeeAllButtonTest {

    @get:Rule
    val compose = createComposeRule()

    @Test
    fun twoSectionButtonsSpeakDifferentNames() {
        compose.setContent {
            RaddStreamTheme {
                Column {
                    SeeAllButton(onClick = {}, contentDescription = "See all Movies")
                    SeeAllButton(onClick = {}, contentDescription = "See all Series")
                }
            }
        }
        // Each button is heard once, by its own section name.
        compose.onNode(hasContentDescription("See all Movies")).assertExists()
        compose.onNode(hasContentDescription("See all Series")).assertExists()
        // No bare "See all" node remains: the painted text is silent, and
        // neither section name equals the bare label.
        compose.onAllNodes(hasContentDescription("See all")).assertCountEquals(0)
        // Both buttons are still clickable.
        compose.onAllNodes(hasClickAction()).assertCountEquals(2)
    }

    @Test
    fun defaultButtonSpeaksItsLabel() {
        compose.setContent {
            RaddStreamTheme {
                SeeAllButton(onClick = {})
            }
        }
        compose.onNode(hasContentDescription("See all")).assertExists()
    }
}
