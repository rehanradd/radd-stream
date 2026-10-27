package com.raddstream.app.viewmodel

import com.raddstream.app.network.models.Post
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * A rail that had rows and then failed to refresh used to render no branch at all: `visible`
 * required a clean error, the empty-with-error branch required no rows, so the row simply
 * disappeared and the failure went unsaid. These pin the one question the screen now asks.
 */
class HomeRailFailureTest {

    @Test
    fun `stale rows with a failed refresh say what happened`() {
        val section = HomeSection(
            key = "movie",
            title = "Movies",
            type = "movie",
            items = listOf(post(1), post(2)),
            error = "Could not load this row.",
        )
        assertEquals("Could not load this row.", section.refreshFailure)
    }

    @Test
    fun `a rail that never had rows is owned by its own failure block`() {
        val section = HomeSection(key = "series", title = "Series", type = "series", error = "Boom")
        assertNull(section.refreshFailure)
    }

    @Test
    fun `a healthy rail has nothing to report`() {
        val section = HomeSection(
            key = "recent",
            title = "Recently added",
            type = null,
            items = listOf(post(3)),
        )
        assertNull(section.refreshFailure)
        assertEquals(null, section.error)
    }

    @Test
    fun `the hero still refuses to promote a rail that failed`() {
        val failed = HomeSection(
            key = "series",
            title = "Series",
            type = "series",
            items = listOf(post(4)),
            error = "Boom",
        )
        assertEquals("Boom", failed.refreshFailure)
        assertEquals(false, failed.visible)
    }

    private fun post(id: Int) = Post(id = id, title = "Title $id", cleanTitle = "Title $id")
}
