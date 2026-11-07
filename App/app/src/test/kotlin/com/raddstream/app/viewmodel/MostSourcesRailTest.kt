package com.raddstream.app.viewmodel

import com.raddstream.app.network.models.PanelSection
import com.raddstream.app.network.models.Post
import com.raddstream.app.network.models.VipRemoteConfig
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * D2.2 Shape C: the "Most Sources" rail is `sort=trending` on the live
 * `/api/v1/posts` route — no new endpoint, no nginx allow, no Browse call.
 * These pin the rail itself, not the network: five rails in order, only
 * "Most Sources" asks for a sort, and only it hides "See all" (Browse takes
 * a type but no sort, so it cannot reproduce that order). The label is
 * pinned too: "Trending" would promise popularity data that does not exist
 * — the ledger has no play-count column, so the order is prints + mirrors.
 */
class MostSourcesRailTest {

    @Test
    fun `five rails in order with most sources last`() {
        val sections = initialHomeSections()

        assertEquals(
            listOf("recent", "movie", "series", "season", "most_sources"),
            sections.map { it.key },
        )
        assertEquals(
            listOf("Recently added", "Movies", "Series", "Seasons", "Most Sources"),
            sections.map { it.title },
        )
        assertTrue(sections.all { it.loading })
    }

    @Test
    fun `only most sources asks the server for a sort`() {
        val sections = initialHomeSections()

        assertEquals("trending", sections.last().sort)
        assertNull(sections.last().type)
        assertTrue(sections.dropLast(1).all { it.sort == null })
    }

    @Test
    fun `the rail is named for its input not for popularity`() {
        val rail = initialHomeSections().last()

        assertEquals("Most Sources", rail.title)
        assertFalse(rail.title.contains("Trending", ignoreCase = true))
    }

    @Test
    fun `only a sorted rail hides see all`() {
        val sections = initialHomeSections()

        assertTrue(sections.dropLast(1).all { it.browseEquivalent })
        assertFalse(sections.last().browseEquivalent)
    }

    @Test
    fun `a plain rail has no sort and keeps see all`() {
        val section = HomeSection(key = "movie", title = "Movies", type = "movie")

        assertNull(section.sort)
        assertTrue(section.browseEquivalent)
    }

    @Test
    fun `merge keeps most sources when the panel owns no such key`() {
        val (sections, _) = mergePanelFeed(
            initialHomeSections(),
            VipRemoteConfig(
                sections = listOf(
                    PanelSection(key = "picks", title = "Picks", items = listOf(post(9))),
                ),
            ),
            dismissedBroadcastIds = emptySet(),
        )

        assertEquals(
            listOf("panel:picks", "recent", "movie", "series", "season", "most_sources"),
            sections.map { it.key },
        )
        assertEquals("trending", sections.last().sort)
    }

    @Test
    fun `a panel section keyed most sources replaces the built-in rail`() {
        val (sections, _) = mergePanelFeed(
            initialHomeSections(),
            VipRemoteConfig(
                sections = listOf(
                    PanelSection(key = "most_sources", title = "Most Sources", items = listOf(post(7))),
                ),
            ),
            dismissedBroadcastIds = emptySet(),
        )

        assertEquals(
            listOf("panel:most_sources", "recent", "movie", "series", "season"),
            sections.map { it.key },
        )
        assertTrue(sections.first().panelManaged)
    }

    private fun post(id: Int) = Post(id = id, title = "Title $id", cleanTitle = "Title $id")
}
