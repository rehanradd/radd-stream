package com.raddstream.app.viewmodel

import com.raddstream.app.network.models.Post
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Gap A5: the Home cache round-trips through JSON, never caches a panel
 * rail, and never lets a corrupt payload blank Home.
 */
class HomeCacheTest {

    private fun post(id: Int) = Post(id = id, title = "Title $id")

    private fun sections() = listOf(
        HomeSection(key = "recent", title = "Recently added", type = null, items = listOf(post(1), post(2))),
        HomeSection(key = "movie", title = "Movies", type = "movie", items = emptyList()),
        HomeSection(
            key = "panel:hero",
            title = "Hero",
            type = null,
            items = listOf(post(9)),
            panelManaged = true,
        ),
    )

    @Test
    fun `encode then decode returns the same rows`() {
        val json = encodeHomeCache(sections(), updatedAtMs = 1_000L)
        val decoded = decodeHomeCache(json)

        assertEquals(1_000L, decoded?.updatedAtMs)
        assertEquals(listOf("recent", "movie"), decoded?.sections?.map { it.key })
        assertEquals(listOf(1, 2), decoded?.sections?.firstOrNull()?.items?.map { it.id })
    }

    @Test
    fun `panel managed sections are never cached`() {
        val decoded = decodeHomeCache(encodeHomeCache(sections(), updatedAtMs = 1_000L))

        assertTrue(decoded?.sections?.none { it.key == "panel:hero" } == true)
    }

    @Test
    fun `corrupt json decodes to null`() {
        assertNull(decodeHomeCache("{not json"))
        assertNull(decodeHomeCache(""))
    }

    @Test
    fun `empty sections decode to null`() {
        assertNull(decodeHomeCache(encodeHomeCache(emptyList(), updatedAtMs = 1_000L)))
    }

    @Test
    fun `restored sections are not loading`() {
        val decoded = decodeHomeCache(encodeHomeCache(sections(), updatedAtMs = 1_000L)!!)!!
        val restored = restoreHomeSections(decoded)

        assertEquals(listOf("recent", "movie"), restored.map { it.key })
        assertTrue(restored.none { it.loading })
        assertEquals(listOf(1, 2), restored.first().items.map { it.id })
    }
}
