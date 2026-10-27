package com.raddstream.app.ui.components

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import com.raddstream.app.network.models.Post
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

    @Test
    fun `a cleaned title wins over the raw page title`() {
        compose.setContent {
            PosterCard(post = post(raw = "VegaMovies · Inception (2024) [1080p]", clean = "Inception"))
        }
        compose.onNode(hasText("Inception", substring = false)).assertIsDisplayed()
        assertFalse(
            "the raw page title reached the screen, so provenance leaked",
            compose.onAllNodes(hasText("VegaMovies", substring = true)).fetchSemanticsNodes().isNotEmpty(),
        )
    }

    @Test
    fun `year and medium render as their own line`() {
        compose.setContent { PosterCard(post = post(raw = "Inception", clean = null)) }
        compose.onNode(hasText("2024 · Movie", substring = true)).assertIsDisplayed()
    }

    @Test
    fun `an empty clean title falls back to the raw title rather than rendering blank`() {
        compose.setContent { PosterCard(post = post(raw = "Inception", clean = "")) }
        compose.onNode(hasText("Inception", substring = false)).assertIsDisplayed()
    }
}
