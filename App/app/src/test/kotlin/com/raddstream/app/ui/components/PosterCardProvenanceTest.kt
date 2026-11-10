package com.raddstream.app.ui.components

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.width
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.dp
import com.raddstream.app.network.models.Post
import com.raddstream.app.ui.theme.RaddStreamTheme
import org.junit.Assert.assertTrue
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
 * ratio that alone is ~470dp tall, i.e. the entire window — and the tile lands below the fold.
 * `assertIsDisplayed` is a viewport assertion, so the cases below failed on geometry while being
 * right about content. Confining the tile to a grid cell is what makes the test describe the
 * layout the app builds instead of a window it never does.
 *
 * **Since the Robo run-2 a11y fix (Session 130) the tile speaks one merged sentence.** The
 * title, year/medium line, badges and progress are paint in the text column
 * (`clearAndSetSemantics`), and the tile's root carries the whole sentence as its content
 * description — so a screen reader hears each tile once instead of the same words four times.
 * These tests therefore pin the spoken sentence, not the two painted lines: the provenance
 * facts (cleaned title wins, year + medium present, empty clean title falls back) are the same,
 * asserted through the one node the user actually hears.
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

    /**
     * The tile's one spoken sentence for these posts: cleaned title, then "2024 · Movie".
     * No rating, no audio badges (the test post carries no language/industry), no progress.
     */
    private val tileSpeech = "Inception, 2024 · Movie"

    @Test
    fun `a cleaned title wins over the raw page title`() {
        showTile(post(raw = "VegaMovies · Inception (2024) [1080p]", clean = "Inception"))
        compose.onNode(hasContentDescription(tileSpeech, substring = false)).assertIsDisplayed()
        assertTrue(
            "the raw page title reached the screen, so provenance leaked",
            compose.onAllNodes(hasContentDescription("VegaMovies", substring = true))
                .fetchSemanticsNodes().isEmpty(),
        )
    }

    @Test
    fun `year and medium ride in the tile's one spoken sentence`() {
        showTile(post(raw = "Inception", clean = null))
        // One node, one sentence: the title and the "2024 · Movie" details are both in it, in
        // that order. The two painted lines below the poster are paint-only since Session 130,
        // so two separately resolvable text nodes no longer exist — and must not, or TalkBack
        // hears the tile four times over.
        compose.onNode(hasContentDescription(tileSpeech, substring = false)).assertIsDisplayed()
    }

    @Test
    fun `an empty clean title falls back to the raw title rather than rendering blank`() {
        showTile(post(raw = "Inception", clean = ""))
        compose.onNode(hasContentDescription(tileSpeech, substring = false)).assertIsDisplayed()
    }
}
