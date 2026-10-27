package com.raddstream.app.viewmodel

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Guards the sort rule that decides whether the search screen answers in under a
 * second or hangs up.
 *
 * Measured on the live catalog (2026-10-28, `GET /api/v1/posts?limit=20` against the
 * running service): the server's `trending`, `rating` and `title` sorts each aggregate
 * or collate the whole matched set before paging, so a facet search with no text took
 * 13.3 s on `trending` and 4.3 s on `rating`/`title`, while the default newest path
 * answered in 0.66 s. OkHttp's read timeout in `network/ApiProvider.kt` is 15 s, so the
 * slowest sort starts the screen one bad hop away from a timeout on every fresh install.
 *
 * The slow set is stated here as a checked expectation rather than a comment: if someone
 * makes one of them the default again, this fails and the measurement has to be re-argued.
 */
class SearchSortPolicyTest {

    /** Wire values that force a whole-result-set pass server-side. */
    private val serverWideScanSorts = setOf("trending", "rating", "title")

    @Test
    fun `the first search never asks the server for a wide scan`() {
        val default = SearchUiState()
        assertFalse(
            "SearchScreen now defaults to ${default.sort.wireValue}, which the live catalog " +
                "answers in seconds; keep the default on the indexed newest path",
            default.sort.wireValue in serverWideScanSorts,
        )
        assertEquals("newest", default.sort.wireValue)
    }

    @Test
    fun `every offered sort is a value the server actually accepts`() {
        // viewer.py's api_v1_get_posts maps rating/title/trending and treats anything
        // else as newest, so an unmapped value silently lies about what it sorted by.
        val accepted = setOf("newest", "trending", "rating", "title")
        SearchSort.entries.forEach { sort ->
            assertTrue("${sort.name} sends sort=${sort.wireValue}", sort.wireValue in accepted)
        }
        assertEquals(SearchSort.DEFAULT, SearchSort.NEWEST)
    }

    @Test
    fun `no chip promises popularity the ledger cannot measure`() {
        // There is no play-count column, so "Trending"/"Popular" would be a false claim.
        SearchSort.entries.forEach { sort ->
            val label = sort.label.lowercase()
            assertFalse(
                "${sort.name} is labelled \"${sort.label}\" but the catalog has no view counts",
                label.contains("trending") || label.contains("popular"),
            )
        }
        assertEquals("Most Sources", SearchSort.MOST_SOURCES.label)
    }

    @Test
    fun `the default sort is not reported as an active filter`() {
        // Clearing filters must be able to restore the default, and the chip row must not
        // light "Newest" up as though the viewer had narrowed something.
        val state = SearchUiState(sort = SearchSort.DEFAULT)
        assertFalse(state.hasActiveFilters)
        assertTrue(state.copy(sort = SearchSort.MOST_SOURCES).hasActiveFilters)
    }
}
