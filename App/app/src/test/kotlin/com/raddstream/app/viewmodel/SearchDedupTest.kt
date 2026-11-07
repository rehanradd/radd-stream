package com.raddstream.app.viewmodel

import com.raddstream.app.network.models.Post
import org.junit.Assert.assertEquals
import org.junit.Test

class SearchDedupTest {

    private fun post(
        id: Int,
        title: String,
        cleanTitle: String? = null,
        year: Int? = 2024,
        workRef: String? = null,
        contentType: String = "movie",
        releaseCount: Int = 1,
        sourceCount: Int = 2,
    ) = Post(
        id = id,
        title = title,
        cleanTitle = cleanTitle,
        year = year,
        contentType = contentType,
        workRef = workRef,
        releaseCount = releaseCount,
        sourceCount = sourceCount,
    )

    @Test
    fun `postTitleDedupKey uses workRef when present`() {
        val p1 = post(1, "Inception", workRef = "imdb:tt1375666")
        val p2 = post(2, "Inception 1080p", workRef = "IMDB:TT1375666")
        assertEquals("work:imdb:tt1375666", postTitleDedupKey(p1))
        assertEquals("work:imdb:tt1375666", postTitleDedupKey(p2))
        assertEquals(postTitleDedupKey(p1), postTitleDedupKey(p2))
    }

    @Test
    fun `postTitleDedupKey normalizes cleanTitle and year when workRef missing`() {
        val p1 = post(1, "Spider-Man: No Way Home", cleanTitle = "Spider-Man: No Way Home", year = 2021)
        val p2 = post(2, "Spider-Man No Way Home (2021)", cleanTitle = "Spider-Man No Way Home", year = 2021)
        assertEquals("title:spider man no way home:2021", postTitleDedupKey(p1))
        assertEquals("title:spider man no way home:2021", postTitleDedupKey(p2))
        assertEquals(postTitleDedupKey(p1), postTitleDedupKey(p2))
    }

    @Test
    fun `deduplication preserves the highest sources entry when sorted`() {
        val p1 = post(1, "Dune: Part Two", cleanTitle = "Dune: Part Two", year = 2024, releaseCount = 1, sourceCount = 1)
        val p2 = post(2, "Dune Part Two", cleanTitle = "Dune Part Two", year = 2024, releaseCount = 3, sourceCount = 5)

        val list = listOf(p1, p2)
        val sorted = list.sortedWith(
            compareByDescending<Post> { (it.releaseCount ?: 0) + (it.sourceCount ?: 0) }
                .thenByDescending { it.id },
        )
        val deduped = sorted.distinctBy { postTitleDedupKey(it) }

        assertEquals(1, deduped.size)
        assertEquals(2, deduped.first().id)
        assertEquals(8, (deduped.first().releaseCount ?: 0) + (deduped.first().sourceCount ?: 0))
    }
}
