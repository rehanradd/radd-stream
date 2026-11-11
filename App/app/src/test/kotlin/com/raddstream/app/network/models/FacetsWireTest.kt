package com.raddstream.app.network.models

import com.google.gson.Gson
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * GET /api/v1/facets wire shape (App/AGENTS.md §13.7): one JSON
 * deserialization test per new data class. The fixture is the shape the
 * server ACTUALLY sends (`viewer.api_v1_get_facets`) — four groups, each
 * entry a key, a label and the count its tap delivers.
 */
class FacetsWireTest {

    private val gson = Gson()

    @Test
    fun `facets decode the server's shape`() {
        val json = """
            {"genres": [{"key": "action", "label": "Action", "count": 27922},
                        {"key": "sci-fi", "label": "Sci-Fi", "count": 3616},
                        {"key": "animation", "label": "Animation", "count": 0}],
             "languages": [{"key": "hindi", "label": "Hindi", "count": 41200}],
             "industries": [{"key": "bollywood", "label": "Bollywood", "count": 38000}],
             "types": [{"key": "movie", "label": "Movies", "count": 120000},
                       {"key": "series", "label": "Series", "count": 30000}]}
        """.trimIndent()
        val resp = gson.fromJson(json, FacetsResponse::class.java)
        assertEquals(3, resp.genres.size)
        val action = resp.genres[0]
        assertEquals("action", action.key)
        assertEquals("Action", action.label)
        assertEquals(27922, action.count)
        assertEquals("sci-fi", resp.genres[1].key)
        assertEquals("Sci-Fi", resp.genres[1].label)
        assertEquals(0, resp.genres[2].count)
        assertEquals(1, resp.languages.size)
        assertEquals("hindi", resp.languages[0].key)
        assertEquals(1, resp.industries.size)
        assertEquals("bollywood", resp.industries[0].key)
        assertEquals(2, resp.types.size)
        assertEquals("movie", resp.types[0].key)
        assertEquals("series", resp.types[1].key)
    }

    @Test
    fun `a body without groups decodes empty, never null`() {
        val resp = gson.fromJson("""{}""", FacetsResponse::class.java)
        assertTrue(resp.genres.isEmpty())
        assertTrue(resp.languages.isEmpty())
        assertTrue(resp.industries.isEmpty())
        assertTrue(resp.types.isEmpty())
    }

    @Test
    fun `a facet entry without a count decodes zero, never null`() {
        val resp = gson.fromJson(
            """{"genres": [{"key": "horror", "label": "Horror"}]}""",
            FacetsResponse::class.java,
        )
        assertEquals(1, resp.genres.size)
        assertEquals(0, resp.genres[0].count)
    }
}
