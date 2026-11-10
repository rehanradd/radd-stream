package com.raddstream.app.ui.components

import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import com.raddstream.app.ui.theme.RaddStreamTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * Robo run 8: a poster that had not loaded yet was scored as a picture —
 * the McLintock! detail poster measured 1.63:1, and the sampled colours are
 * the poster's own surfaceVariant box and outlineVariant frame, no artwork at
 * all. Until a request produces a bitmap the box holds the loading shimmer,
 * not an image, so the image node stays out of the accessibility tree until
 * there is an image to describe (the run-7 ShimmerBox pattern); on success
 * it appears with its content description, and on error the fallback card
 * speaks instead. Pins that a loading poster exposes no image node.
 *
 * Runs on the JVM under Robolectric because this project has no emulator image.
 * The clock is frozen (the SkeletonPlaceholderTest pattern) so the shimmer's
 * infinite transition never advances past the first frame. Under Robolectric
 * the request cannot fetch — there is no real network — so by the time the
 * first query runs (onNode waits for idle) the load has already errored and
 * the fallback card is showing. That is still a "no bitmap yet" state, and it
 * is the state the test pins: the old code carried the content description
 * from the first frame in every state, so it would expose the image node here
 * too and fail the first assertion. The transient loading state itself is not
 * observable from a Robolectric test — every node query waits for idle first.
 *
 * Requires an x86_64 runner. Robolectric's native runtime has no Linux/aarch64
 * build (robolectric/robolectric#9166) and it fails while the runner boots, so
 * the exclusion for ARM hosts lives in app/build.gradle.kts rather than here.
 */
@RunWith(RobolectricTestRunner::class)
class CatalogImageLoadingTest {

    @get:Rule
    val compose = createComposeRule()

    @Test
    fun loadingPosterHasNoImageNode() {
        compose.mainClock.autoAdvance = false
        compose.setContent {
            RaddStreamTheme {
                CatalogImage(
                    url = "https://image.tmdb.org/t/p/w500/abc123.jpg",
                    contentDescription = "McLintock! poster",
                    fallbackLabel = "MC",
                )
            }
        }
        // No image node until the request produces a bitmap: on the old code
        // the SubcomposeAsyncImage carried "McLintock! poster" from the first
        // frame, so the checker scored the loading shimmer as a picture — and
        // it would carry it in the error state too, which is the state this
        // test observes under Robolectric.
        // onNode is a rule member and assertDoesNotExist is a member of the
        // returned interaction (the Session 131 trap — neither is imported);
        // hasContentDescription is a top-level matcher.
        compose.onNode(hasContentDescription("McLintock! poster")).assertDoesNotExist()
        // And the fallback card speaks instead of the blank rectangle: the
        // load errored (no real network under Robolectric), onError left
        // loaded false, so the error slot paints the branded card with the
        // initials — the checker scores a labelled fallback, not a bare box.
        // assertExists is likewise a member, not an import.
        compose.onNode(hasText("MC")).assertExists()
    }
}
