package com.raddstream.app.ui.components

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.width
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.assertHasClickAction
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.performClick
import androidx.compose.ui.unit.dp
import com.raddstream.app.network.models.Post
import com.raddstream.app.ui.theme.RaddStreamTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * UI-fix P0-1: the ★ rating badge painted OVER the remove × on a PosterCard
 * (both `align(TopEnd)` in the same poster Box, the badge declared later, so
 * it won the tap). In My List / Continue Watching a rated title could not be
 * removed by tapping × — the tap hit the paint-only badge. The badge now
 * rides BottomStart, above the progress bar, and the × stays TopEnd.
 */
@RunWith(RobolectricTestRunner::class)
class PosterCardRemoveWithRatingTest {

    @get:Rule
    val compose = createComposeRule()

    private fun ratedPost() = Post(
        id = 1,
        title = "Inception",
        cleanTitle = "Inception",
        year = 2010,
        contentType = "movie",
        imdbRating = "8.6",
    )

    @Test
    fun `a rated tile with onRemove keeps its remove button tappable`() {
        var removed = 0
        compose.setContent {
            RaddStreamTheme(darkTheme = true) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.TopStart) {
                    PosterCard(
                        post = ratedPost(),
                        modifier = Modifier.width(120.dp),
                        onRemove = { removed++ },
                    )
                }
            }
        }
        // The tile still carries its rating in the spoken sentence …
        compose.onNode(hasContentDescription("rating 8.6 out of 10", substring = true))
            .assertIsDisplayed()
        // … and the × is a visible, clickable node of its own — not painted over.
        val remove = compose.onNodeWithContentDescription("Remove Inception from My List")
        remove.assertIsDisplayed().assertHasClickAction()
        remove.performClick()
        assertEquals("tapping the × on a rated tile must remove it", 1, removed)
    }

    @Test
    fun `an unrated tile with onRemove still removes`() {
        var removed = 0
        compose.setContent {
            RaddStreamTheme(darkTheme = true) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.TopStart) {
                    PosterCard(
                        post = ratedPost().copy(imdbRating = null),
                        modifier = Modifier.width(120.dp),
                        onRemove = { removed++ },
                    )
                }
            }
        }
        compose.onNodeWithContentDescription("Remove Inception from My List")
            .assertIsDisplayed().performClick()
        assertEquals(1, removed)
    }
}
