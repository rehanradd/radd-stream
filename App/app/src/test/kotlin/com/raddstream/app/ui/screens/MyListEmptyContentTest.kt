package com.raddstream.app.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.raddstream.app.network.models.Post
import com.raddstream.app.ui.components.EmptyState
import com.raddstream.app.ui.components.PosterCard
import com.raddstream.app.ui.theme.RaddStreamTheme
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * Robo run 8: the My List empty state never showed its "Popular right now"
 * row — and Robo measured three 32dp clickables just above the nav bar.
 * Both are the same layout bug: [EmptyState] is a fillMaxSize Box, so inside
 * the empty-state Column it took the whole height and the PopularRow below it
 * was laid out with no height left — off-screen, its three poster cards
 * collapsed to a strip at the content's bottom edge, one per column. The
 * message now takes the remaining space (weight 1f) and the row takes its
 * natural height. These tests pin both halves: the new layout's cards are
 * full-height tiles, and the old shape (reproduced here) really did starve
 * them under the 48dp floor.
 *
 * Runs on the JVM under Robolectric because this project has no emulator image.
 *
 * Requires an x86_64 runner. Robolectric's native runtime has no Linux/aarch64
 * build (robolectric/robolectric#9166) and it fails while the runner boots, so
 * the exclusion for ARM hosts lives in app/build.gradle.kts rather than here.
 */
@RunWith(RobolectricTestRunner::class)
class MyListEmptyContentTest {

    @get:Rule
    val compose = createComposeRule()

    private fun post(id: Int, title: String) = Post(
        id = id,
        title = title,
        cleanTitle = title,
        year = 2024,
        contentType = "movie",
        // No poster URL: the card renders the branded fallback, so no image
        // load runs in the test — the measured height is the tile's own.
        posterUrl = null,
    )

    private val popular = listOf(
        post(1, "Inception"),
        post(2, "Dune"),
        post(3, "McLintock!"),
    )

    private fun clickableHeights(): List<Dp> {
        val clickable = compose.onAllNodes(hasClickAction())
        clickable.assertCountEquals(popular.size)
        return clickable.fetchSemanticsNodes().map {
            with(compose.density) { it.boundsInRoot.height.toDp() }
        }
    }

    @Test
    fun popularRowCardsAreFullHeightClickables() {
        compose.setContent {
            RaddStreamTheme {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.TopStart) {
                    MyListEmptyContent(
                        popular = popular,
                        onPostClick = {},
                        modifier = Modifier.width(360.dp),
                    )
                }
            }
        }
        // The row is visible: its heading is on screen, not pushed below the fold.
        compose.onNodeWithText("Popular right now").assertIsDisplayed()
        // The only clickables are the three poster cards — one per title.
        val heights = clickableHeights()
        assertTrue(
            "PopularRow cards measure $heights, expected every card a full-height tile (>= 48dp)",
            heights.all { it >= 48.dp },
        )
        assertTrue(
            "PopularRow cards measure $heights, expected poster height, not a collapsed strip",
            heights.all { it > 100.dp },
        )
    }

    @Test
    fun preFixLayoutStarvesPopularRow() {
        compose.setContent {
            RaddStreamTheme {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.TopStart) {
                    // The pre-fix empty state, verbatim in structure: a
                    // fillMaxSize EmptyState takes the whole Column and the
                    // PopularRow below it is laid out with no height left.
                    // Kept only to prove the bug — the production code no
                    // longer builds this shape.
                    Column(Modifier.width(360.dp)) {
                        EmptyState(
                            title = "Your list is empty",
                            message = "Tap the heart on any movie or series to save it here for quick access.",
                            modifier = Modifier.fillMaxWidth(),
                        )
                        Row(
                            Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
                            horizontalArrangement = Arrangement.spacedBy(12.dp),
                        ) {
                            popular.forEach { p ->
                                PosterCard(
                                    post = p,
                                    onClick = {},
                                    modifier = Modifier.weight(1f),
                                )
                            }
                        }
                    }
                }
            }
        }
        val heights = clickableHeights()
        assertTrue(
            "pre-fix PopularRow cards measure $heights, expected every card collapsed under 48dp",
            heights.all { it < 48.dp },
        )
    }
}
