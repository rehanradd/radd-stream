package com.raddstream.app.ui.screens

import androidx.compose.ui.test.assertLeftPositionInRootIsEqualTo
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
 * UI-fix P1-H3: the two browse rows merged into one "Browse" section, so the
 * two heading cases below are now one — the single heading still carries
 * the 16 dp margin.
 *
 * Runs on the JVM under Robolectric because this project has no emulator
 * image. Requires an x86_64 runner (robolectric/robolectric#9166).
 */
@RunWith(RobolectricTestRunner::class)
class HomeSectionMarginsTest {

    @get:Rule
    val compose = createComposeRule()

    @Test
    fun libraryStripHeadingHasThePhoneMargin() {
        compose.setContent {
            RaddStreamTheme {
                LibraryStrip(onOpenLocalFiles = {}, onOpenDownloads = {})
            }
        }
        compose.onNodeWithText("Your library").assertLeftPositionInRootIsEqualTo(16.dp)
    }

    @Test
    fun browseSectionHeadingHasThePhoneMargin() {
        val facets = FacetsResponse(
            genres = listOf(FacetEntry(key = "action", label = "Action", count = 12)),
        )
        compose.setContent {
            RaddStreamTheme {
                BrowseSection(facets = facets, onBrowseType = {}, onFacetSelected = { _, _, _ -> })
            }
        }
        compose.onNodeWithText("Browse").assertLeftPositionInRootIsEqualTo(16.dp)
    }
}
