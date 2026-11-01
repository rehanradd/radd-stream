package com.raddstream.app.viewmodel

import com.raddstream.app.network.models.Post
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Duplicate search results are forbidden, and the count under the search box has to be the number
 * of works, not the number of catalog rows. Both are one rule: collapse rows the server named as
 * one work, and never collapse rows it did not.
 */
class SearchMergeTest {

    private fun row(
        id: Int,
        ref: String? = "W1",
        title: String = "Inception",
        releases: Int? = 1,
        sources: Int? = 1,
        art: String? = "http://127.0.0.1/a.jpg",
        imdb: String? = "8.8",
        year: Int? = 2010,
    ) = Post(
        id = id,
        title = "$title ($id)",
        cleanTitle = title,
        year = year,
        contentType = "movie",
        posterUrl = art,
        imdbRating = imdb,
        releaseCount = releases,
        sourceCount = sources,
        workRef = ref,
    )

    @Test
    fun `one work the server named twice is one result`() {
        val merged = SearchMerge.dedupe(listOf(row(1), row(2)))
        assertEquals(1, merged.size)
    }

    @Test
    fun `the copy that stays is the one that tells the viewer more`() {
        // Six prints beat one print: the richer row moves into the first row's slot rather than the
        // list reordering under the viewer's finger.
        val merged = SearchMerge.dedupe(listOf(row(1, releases = 1), row(2, releases = 6)))
        assertEquals(2, merged.single().id)
    }

    @Test
    fun `a merged row keeps the slot of the first copy the server sent`() {
        // The richer copy moves INTO position zero; the list does not reorder under the viewer.
        val merged = SearchMerge.dedupe(
            listOf(row(1, releases = 1, art = null), row(2, releases = 2, art = null), row(3, ref = "W9")),
        )
        assertEquals(listOf(2, 3), merged.map { it.id })
    }

    @Test
    fun `equal information never swaps`() {
        val merged = SearchMerge.dedupe(listOf(row(1), row(2, art = null)))
        assertEquals(1, merged.single().id)
    }

    @Test
    fun `an unnamed row is never merged with anything`() {
        // A blank or absent work_ref is not "the same unknown work" — dropping one of these would
        // take a title out of the catalog as far as the viewer can tell.
        val merged = SearchMerge.dedupe(listOf(row(1, ref = null), row(2, ref = "  "), row(3, ref = "")))
        assertEquals(3, merged.size)
    }

    @Test
    fun `different works are never merged`() {
        val merged = SearchMerge.dedupe(listOf(row(1, ref = "W1"), row(2, ref = "W2")))
        assertEquals(listOf(1, 2), merged.map { it.id })
    }

    @Test
    fun `the order the server sent is the order the viewer sees`() {
        val merged = SearchMerge.dedupe(
            listOf(row(1, ref = "W1"), row(2, ref = "W2"), row(3, ref = "W1"), row(4, ref = "W2")),
        )
        assertEquals(listOf(1, 2), merged.map { it.id })
    }

    @Test
    fun `the count under the search box counts works`() {
        val rows = listOf(row(1), row(2), row(3, ref = "W7"))
        val merged = SearchMerge.dedupe(rows)
        assertEquals("two names for one work must not become two results", 2, merged.size)
        assertTrue(rows.size > merged.size)
    }

    @Test
    fun `nothing is dropped when every work is named once`() {
        val rows = listOf(row(1, ref = "A"), row(2, ref = "B"), row(3, ref = "C"))
        assertEquals(rows, SearchMerge.dedupe(rows))
    }
}
