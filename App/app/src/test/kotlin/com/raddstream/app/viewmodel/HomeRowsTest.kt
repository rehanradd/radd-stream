package com.raddstream.app.viewmodel

import com.raddstream.app.network.models.Post
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The Home row budget: Continue Watching first and pinned, then at most
 * [MAX_HOME_ROWS] rows total — so with a saved title on screen the page
 * carries nine content rails, never sixteen.
 */
class HomeRowsTest {

    private fun section(key: String) = HomeSection(
        key = key,
        title = key,
        type = null,
        items = listOf(Post(id = key.hashCode(), title = key)),
    )

    private fun twelve() = (1..12).map { section("row$it") }

    @Test
    fun `ten rows at most without continue watching`() {
        val shown = visibleHomeRows(twelve(), hasContinueWatching = false)

        assertEquals(10, shown.size)
        assertEquals((1..10).map { "row$it" }, shown.map { it.key })
    }

    @Test
    fun `nine content rows when continue watching takes the first slot`() {
        val shown = visibleHomeRows(twelve(), hasContinueWatching = true)

        assertEquals(9, shown.size)
        assertEquals((1..9).map { "row$it" }, shown.map { it.key })
    }

    @Test
    fun `fewer sections pass through unchanged`() {
        val shown = visibleHomeRows(twelve().take(3), hasContinueWatching = true)

        assertEquals(3, shown.size)
    }

    @Test
    fun `empty stays empty`() {
        assertTrue(visibleHomeRows(emptyList(), hasContinueWatching = false).isEmpty())
        assertTrue(visibleHomeRows(emptyList(), hasContinueWatching = true).isEmpty())
    }
}
