package com.raddstream.app.viewmodel

import com.raddstream.app.network.models.Post
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Gap A6: the "Pick 3 you like" card shows only to a brand-new viewer, and
 * only once a rail can offer three real titles.
 */
class PickThreeTest {

    private fun post(id: Int) = Post(id = id, title = "Title $id")

    private fun rail(items: List<Post>) =
        HomeSection(key = "recent", title = "Recently added", type = null, items = items)

    private fun state(
        sections: List<HomeSection> = listOf(rail(listOf(post(1), post(2), post(3), post(4)))),
        continueWatching: List<ResumeTile> = emptyList(),
        favoriteIds: Set<Int> = emptySet(),
        pickThreeDone: Boolean = false,
    ) = HomeUiState(
        sections = sections,
        continueWatching = continueWatching,
        favoriteIds = favoriteIds,
        pickThreeDone = pickThreeDone,
    )

    @Test
    fun `brand new viewer with a full rail sees the card with the first three`() {
        val s = state()

        assertTrue(s.showPickThree)
        assertEquals(listOf(1, 2, 3), s.pickThreeCandidates.map { it.id })
    }

    @Test
    fun `continue watching hides the card`() {
        val tile = ResumeTile.of(
            com.raddstream.app.data.local.WatchHistoryEntity(
                workRef = "w1",
                postId = 1,
                title = "Title 1",
                posterUrl = null,
                seasonNumber = 0,
                episodeNumber = 0,
                positionMs = 1_000L,
                durationMs = 10_000L,
                updatedAt = 1_000L,
            ),
        )
        assertFalse(state(continueWatching = listOfNotNull(tile)).showPickThree)
    }

    @Test
    fun `any saved title hides the card`() {
        assertFalse(state(favoriteIds = setOf(1)).showPickThree)
    }

    @Test
    fun `dismissed card never returns`() {
        assertFalse(state(pickThreeDone = true).showPickThree)
    }

    @Test
    fun `a rail with fewer than three titles offers nothing`() {
        val s = state(sections = listOf(rail(listOf(post(1), post(2)))))

        assertTrue(s.pickThreeCandidates.isEmpty())
        assertFalse(s.showPickThree)
    }
}
