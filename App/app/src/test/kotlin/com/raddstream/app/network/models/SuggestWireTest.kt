package com.raddstream.app.network.models

import com.google.gson.Gson
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * GET /api/v2/suggest wire shape (App/AGENTS.md §13.7): one JSON
 * deserialization test per new data class. The fixture is the shape the
 * server ACTUALLY sends (`catalog_api.suggest`) — work ids, not post ids,
 * so a tap searches for the title rather than opening a detail page.
 */
class SuggestWireTest {

    private val gson = Gson()

    @Test
    fun `suggest decodes the server's shape`() {
        val json = """
            {"ok": true, "query": "aven", "normalized": "aven",
             "items": [{"id": 1234, "title": "Avengers: Endgame", "year": 2019,
                        "work_type": "movie", "poster_url": "https://x/poster.jpg",
                        "quality_max": "1080p"}],
             "count": 1, "adult_included": false}
        """.trimIndent()
        val resp = gson.fromJson(json, SuggestResponse::class.java)
        assertTrue(resp.ok)
        assertEquals(1, resp.items.size)
        val item = resp.items[0]
        assertEquals(1234, item.id)
        assertEquals("Avengers: Endgame", item.title)
        assertEquals(2019, item.year)
        assertEquals("movie", item.workType)
        assertEquals("1080p", item.qualityMax)
    }

    @Test
    fun `a body without items decodes empty, never null`() {
        val resp = gson.fromJson("""{"ok": true}""", SuggestResponse::class.java)
        assertTrue(resp.items.isEmpty())
    }

    @Test
    fun `a fuzzy posts page decodes with the marker set`() {
        val json = """
            {"page": 1, "limit": 20, "total": 1, "total_pages": 1, "fuzzy": true,
             "results": [{"id": 42, "title": "Avengers: Endgame", "clean_title": "Avengers Endgame"}]}
        """.trimIndent()
        val resp = gson.fromJson(json, PostsResponse::class.java)
        assertTrue(resp.fuzzy)
        assertEquals(1, resp.total)
        assertEquals("Avengers Endgame", resp.results[0].cleanTitle)
    }
}
