package com.raddstream.app.ui.components

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.width
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.dp
import com.raddstream.app.network.models.Post
import com.raddstream.app.ui.theme.RaddStreamTheme
import org.junit.Assert.assertFalse
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * UI-layer half of the provenance rule: the ledger keeps site names, the screen must not show
 * them. Runs on the JVM under Robolectric because this project has no emulator image.
 *
 * Requires an x86_64 runner. Robolectric's native runtime has no Linux/aarch64 build
 * (robolectric/robolectric#9166) and it fails while the runner boots, so the exclusion for ARM
 * hosts lives in app/build.gradle.kts rather than here — an in-test Assume is too late to help.
 *
 * **The tile is given the width the app actually gives it, and that is not a workaround.** Every
 * catalog grid hands a [PosterCard] a `GridCells.Adaptive(minSize = 120.dp)` cell
 * (`CatalogGridColumns`), but Robolectric composes into its own default 320dp-wide window, so an
 * unconstrained `fillMaxWidth` card here gets a 320dp-wide artwork — at the tile's 0.68 aspect
 * ratio that alone is ~470dp tall, i.e. the entire window — and both text lines land below the
 * fold. `assertIsDisplayed` is a viewport assertion, so the three cases below failed on geometry
 * while being right about content: the component really does render the cleaned title, and really
 * does paint "2024 · Movie" as its own line. Confining the tile to a grid cell is what makes the
 * test describe the layout the app builds instead of a window it never does.
 */
@RunWith(RobolectricTestRunner::class)
class PosterCardProvenanceTest {

    @get:Rule
    val compose = createComposeRule()

    private fun post(raw: String, clean: String?) = Post(
        id = 1,
        title = raw,
        cleanTitle = clean,
        year = 2024,
        contentType = "movie",
    )

    /** The narrowest cell the catalog grid can hand a tile, so nothing here depends on a wide phone. */
    private fun showTile(post: Post) {
        compose.setContent {
            RaddStreamTheme(darkTheme = true) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.TopStart) {
                    PosterCard(post = post, modifier = Modifier.width(120.dp))
                }
            }
        }
    }

    @Test
    fun `a cleaned title wins over the raw page title`() {
        showTile(post(raw = "VegaMovies · Inception (2024) [1080p]", clean = "Inception"))
        compose.onNode(hasText("Inception", substring = false)).assertIsDisplayed()
        assertFalse(
            "the raw page title reached the screen, so provenance leaked",
            compose.onAllNodes(hasText("VegaMovies", substring = true)).fetchSemanticsNodes().isNotEmpty(),
        )
    }

    @Test
    fun `year and medium render as their own line`() {
        showTile(post(raw = "Inception", clean = null))
        // Two nodes with two exact strings, not one merged label: onNode refuses an ambiguous or
        // missing match, so both lines being resolvable on their own IS the "own line" claim.
        compose.onNode(hasText("Inception", substring = false)).assertIsDisplayed()
        compose.onNode(hasText("2024 · Movie", substring = false)).assertIsDisplayed()
    }

    @Test
    fun `an empty clean title falls back to the raw title rather than rendering blank`() {
        showTile(post(raw = "Inception", clean = ""))
        compose.onNode(hasText("Inception", substring = false)).assertIsDisplayed()
    }
}
