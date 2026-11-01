package com.raddstream.app.viewmodel

import com.raddstream.app.network.models.Post
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Covers flow-audit item #7 at trunk `9074134`: Browse and Search append server pages into
 * lists whose grids key on `post.id`, and the server orders `id DESC` — so a scrape landing
 * between page fetches shifts the window and hands the same row back twice. A duplicate key
 * in `LazyVerticalGrid`/keyed `MediaRail` throws; `distinctById` is the guard every paging
 * site now runs through.
 */
class PagedGridDedupTest {

    @Test
    fun `an appended page repeating an existing id keeps one copy`() {
        val page1 = listOf(post(10), post(9), post(8))
        val page2 = listOf(post(8), post(7), post(6)) // id 8 shifted into the window
        val merged = (page1 + page2).distinctById()
        assertEquals(listOf(10, 9, 8, 7, 6), merged.map { it.id })
    }

    @Test
    fun `duplicates inside one response are removed too`() {
        val page = listOf(post(3), post(3), post(2))
        assertEquals(listOf(3, 2), page.distinctById().map { it.id })
    }

    @Test
    fun `the first occurrence wins so grid order never jumps`() {
        val merged = (listOf(post(5, "first")) + listOf(post(5, "second"), post(4))).distinctById()
        assertEquals("first", merged.first { it.id == 5 }.title)
        assertEquals(listOf(5, 4), merged.map { it.id })
    }

    @Test
    fun `distinct titles sharing no id all survive`() {
        val merged = (listOf(post(1)) + listOf(post(2), post(3))).distinctById()
        assertEquals(3, merged.size)
    }

    private fun post(id: Int, title: String = "Title $id") =
        Post(id = id, title = title, cleanTitle = title)
}
