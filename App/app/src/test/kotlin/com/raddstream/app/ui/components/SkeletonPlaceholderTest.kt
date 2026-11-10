package com.raddstream.app.ui.components

import androidx.compose.foundation.layout.Column
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import com.raddstream.app.ui.theme.RaddStreamTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * Robo run 7: the Home empty-library skeleton read as low-contrast text
 * (1.09:1) in runs 6 and 7 — the run-6 "sampling artifact" reading changed
 * nothing, so the flag came back identical. The placeholder bars are
 * decorative: they carry no words, so they must not appear in the
 * accessibility tree as text (or anything a contrast check can sample).
 * Pins that: the hero skeleton and the poster-grid skeleton — the two
 * skeletons Home and My List show while loading — expose no text nodes.
 *
 * Requires an x86_64 runner. Robolectric's native runtime has no
 * Linux/aarch64 build (robolectric/robolectric#9166) and it fails while the
 * runner boots, so the exclusion for ARM hosts lives in
 * app/build.gradle.kts rather than here. The shimmer's infinite transition
 * is frozen for the test so the clock never advances past the first frame.
 */
@RunWith(RobolectricTestRunner::class)
class SkeletonPlaceholderTest {

    @get:Rule
    val compose = createComposeRule()

    @Test
    fun skeletonsExposeNoTextNodes() {
        compose.mainClock.autoAdvance = false
        compose.setContent {
            RaddStreamTheme {
                Column {
                    HeroSkeleton()
                    PosterGridSkeleton()
                }
            }
        }
        // Every string contains "" — so this matches any node that carries
        // text at all, and nothing else. onAllNodes is a rule member (the
        // Session 131 trap — no import); hasText is a top-level matcher.
        compose.onAllNodes(hasText("", substring = true), useUnmergedTree = true)
            .assertCountEquals(0)
    }
}
