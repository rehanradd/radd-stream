package com.raddstream.app.ui.screens

import androidx.compose.ui.test.assertLeftPositionInRootEquals
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.unit.dp
import com.raddstream.app.network.models.FacetEntry
import com.raddstream.app.network.models.FacetsResponse
import com.raddstream.app.ui.theme.RaddStreamTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * App-design audit (2026-11-12, issue #15): "Your library" and "Browse by
 * type" started at x=0 with their first letter cut off. Every Home section
 * heading sits 16 dp from the screen edge (M3 Expressive phone margin).
 *
 * Runs on the JVM under Robolectric because this project has no emulator
 * image. Requires an x86_64 runner (robolectric/robolectric#9166).
 */
@RunWith(RobolectricTestRunner::class)
class HomeSectionMarginsTest {

    @get:Rule
    val compose = createComposeRule()

    @Test
    fun browserStripHeadingHasThePhoneMargin() {
        compose.setContent {
            RaddStreamTheme {
                BrowserStrip(onPlayVideoLink = {}, onOpenLocalFiles = {}, onOpenDownloads = {})
            }
        }
        compose.onNodeWithText("Your library").assertLeftPositionInRootEquals(16.dp)
    }

    @Test
    fun facetRowHeadingHasThePhoneMargin() {
        val facets = FacetsResponse(
            genres = listOf(FacetEntry(key = "action", label = "Action", count = 12)),
        )
        compose.setContent {
            RaddStreamTheme {
                FacetChipsRow(facets = facets, onFacetSelected = { _, _ -> })
            }
        }
        compose.onNodeWithText("Browse by genre").assertLeftPositionInRootEquals(16.dp)
    }

    @Test
    fun jumpOffRowHeadingHasThePhoneMargin() {
        compose.setContent {
            RaddStreamTheme {
                JumpOffRow(onBrowseType = {})
            }
        }
        compose.onNodeWithText("Browse by type").assertLeftPositionInRootEquals(16.dp)
    }
}
