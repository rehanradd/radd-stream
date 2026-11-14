package com.raddstream.app.network.models

import com.raddstream.app.network.buildRaddGson
import com.raddstream.app.viewmodel.ReleaseLayoutBuilder
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Robo Batch B regression (2026-11-14): the Batch B build opened a title
 * twice (works 7681 Scarpetta, 9048 The Penguin) and both times showed
 * "Couldn't load this title / Failed to load details. Check connection." —
 * while the nginx log proves the API answered both GET /api/v2/works/{id}
 * calls with HTTP 200 and full bodies. The failure is therefore in the
 * client-side mapping of a real v2 detail answer into the detail screen,
 * not in the network. These tests replay the EXACT live answers through the
 * production decode + map + layout path, so whatever in them throws names
 * itself in the failure log.
 *
 * Fixtures are the live answers fetched from the running server, with only
 * the opaque per-link `stream_id` handles and the `/api/v1/art` tokens
 * replaced by test values (the mapping needs them non-blank, never real).
 */
class V2DetailRegressionTest {

    private val gson = buildRaddGson()
    private val baseUrl = "https://raddstream.duckdns.org"

    private fun loadFixture(name: String): String =
        javaClass.classLoader!!.getResourceAsStream("v2detail/$name")!!
            .bufferedReader().readText()

    private fun loadDetail(name: String): PostDetail {
        val response = gson.fromJson(loadFixture(name), WireWorkDetailResponse::class.java)
        assertTrue(response.ok)
        assertNotNull(response.work)
        val detail = response.toPostDetail(baseUrl, 0, null, emptyList())
        assertNotNull(detail)
        return detail!!
    }

    @Test
    fun `Scarpetta v2 detail maps to a series detail with all 82 prints`() {
        val detail = loadDetail("work-7681-scarpetta.json")
        assertEquals("Scarpetta", detail.title)
        assertEquals("gQAPsqIZYTeW_R879MZlhsEF7pIXJQ", detail.workRef)
        assertEquals(82, detail.releases.size)
        assertTrue(detail.optionGroups.isNotEmpty())
        val layout = ReleaseLayoutBuilder.build(
            detail.contentType, detail.releases, detail.backdropList, detail.seasonArtwork,
        )
        assertTrue(layout.isSeriesLike)
        assertTrue(layout.seasons.isNotEmpty())
    }

    @Test
    fun `The Penguin v2 detail maps to a series detail with all 126 prints`() {
        val detail = loadDetail("work-9048-penguin.json")
        assertEquals("The Penguin", detail.title)
        assertEquals("gQAPsqIZYTeW_R86981mh8UHCNRnpQ", detail.workRef)
        assertEquals(126, detail.releases.size)
        assertTrue(detail.optionGroups.isNotEmpty())
        val layout = ReleaseLayoutBuilder.build(
            detail.contentType, detail.releases, detail.backdropList, detail.seasonArtwork,
        )
        assertTrue(layout.isSeriesLike)
        assertTrue(layout.seasons.isNotEmpty())
    }
}
