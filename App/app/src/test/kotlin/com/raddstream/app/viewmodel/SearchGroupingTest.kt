package com.raddstream.app.viewmodel

import com.raddstream.app.network.models.Post
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Session 120: a search whose results spanned types showed ONE rail — a
 * "Series" header, the Movies count, and film cards underneath. The grouping
 * was `groupBy { ... }.toSortedMap(typeComparator)`, and a TreeMap treats two
 * keys as the same key when the comparator returns 0; `typeOrder` only ever
 * matched the plural labels ("Movies"), never the raw wire keys it was handed
 * ("movie"), so every key compared equal and the map kept the first key with
 * the last value. These tests pin the grouping itself, not the label helpers:
 * mixed results keep every rail, each header names the cards under it, and
 * rails run Movies, Series, Seasons, Anime.
 */
class SearchGroupingTest {

    private fun post(id: Int, title: String, contentType: String?, year: Int? = 2026, animated: Boolean? = false) =
        Post(id = id, title = title, contentType = contentType, year = year, isAnimated = animated)

    @Test
    fun `mixed movie and series results keep both rails`() {
        // Series first in server order, movies last: the old TreeMap kept the
        // "series" key and the movie list — one "Series" rail of film cards.
        val rows = listOf(
            post(1, "S One", "series"),
            post(2, "S Two", "series"),
            post(3, "M One", "movie"),
            post(4, "M Two", "movie"),
            post(5, "M Three", "movie"),
            post(6, "M Four", "movie"),
        )
        val groups = groupSearchResults(rows, SearchSort.DEFAULT)

        assertEquals(listOf("Movies", "Series"), groups.map { it.label })
        val movies = groups.first { it.label == "Movies" }
        val series = groups.first { it.label == "Series" }
        // Within a rail the sort is newest-first (id desc on a year tie), so
        // compare as sets: the point is which rows each rail holds, not order.
        assertEquals(listOf(3, 4, 5, 6), movies.items.map { it.id }.sorted())
        assertEquals(listOf(1, 2), series.items.map { it.id }.sorted())
        // The header count is the rail's own size: "Series — 2", never the
        // other rail's 4.
        assertEquals(2, series.items.size)
        assertEquals(4, movies.items.size)
    }

    @Test
    fun `every card under a header paints the header word`() {
        val rows = listOf(
            post(1, "Film", "movie"),
            post(2, "Show", "series"),
            post(3, "Season Pack", "complete_season"),
            post(4, "Toon", "series", animated = true),
            post(5, "Doc", "documentary"),
        )
        val groups = groupSearchResults(rows, SearchSort.DEFAULT)

        assertEquals(listOf("Movies", "Series", "Seasons", "Anime", "Documentary"), groups.map { it.label })
        groups.forEach { group ->
            group.items.forEach { item ->
                // "Movies" heads cards saying "Movie"; "Seasons" heads cards
                // saying "Season"; the rest match word for word.
                val headerWord = when (group.label) {
                    "Movies" -> "Movie"
                    "Seasons" -> "Season"
                    else -> group.label
                }
                assertEquals(
                    "card ${item.id} under '${group.label}' paints '${item.typeLabel}'",
                    headerWord,
                    item.typeLabel,
                )
            }
        }
    }

    @Test
    fun `rails run movies series seasons anime in that order`() {
        val rows = listOf(
            post(1, "Toon", "anime"),
            post(2, "Pack", "complete_season"),
            post(3, "Show", "series"),
            post(4, "Film", "movie"),
        )
        val groups = groupSearchResults(rows, SearchSort.DEFAULT)

        assertEquals(listOf("Movies", "Series", "Seasons", "Anime"), groups.map { it.label })
    }

    @Test
    fun `a row with no type lands in Other and paints no word`() {
        val rows = listOf(post(1, "Mystery", null))
        val groups = groupSearchResults(rows, SearchSort.DEFAULT)

        assertEquals(listOf("Other"), groups.map { it.label })
        assertTrue(groups.single().items.single().typeLabel == null)
    }
}
