package com.raddstream.app.viewmodel

import com.raddstream.app.network.models.PanelBroadcast
import com.raddstream.app.network.models.PanelSection
import com.raddstream.app.network.models.Post
import com.raddstream.app.network.models.VipRemoteConfig
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The operator's feed, merged over the built-in rails. These pin the merge, not the
 * network: the panel sections come first in the panel's order, a built-in rail whose
 * key a panel section owns is dropped, a hidden row is dropped from both, an empty
 * panel section renders nothing, and a dismissed broadcast never comes back.
 */
class PanelFeedMergeTest {

    private val builtIn = listOf(
        HomeSection(key = "recent", title = "Recently added", type = null, items = listOf(post(1), post(2))),
        HomeSection(key = "movie", title = "Movies", type = "movie", items = listOf(post(2), post(3)), loading = true),
        HomeSection(key = "series", title = "Series", type = "series"),
    )

    @Test
    fun `panel sections come first and built-in rails follow`() {
        val (sections, _) = mergePanelFeed(
            builtIn,
            VipRemoteConfig(
                sections = listOf(
                    PanelSection(key = "picks", title = "Picks", items = listOf(post(9))),
                    PanelSection(key = "latest", title = "Latest", items = listOf(post(8))),
                ),
            ),
            dismissedBroadcastIds = emptySet(),
        )

        assertEquals(listOf("panel:picks", "panel:latest", "recent", "movie", "series"), sections.map { it.key })
        assertEquals("Picks", sections[0].title)
        assertTrue(sections[0].panelManaged)
        assertEquals(listOf(9), sections[0].items.map { it.id })
    }

    @Test
    fun `a panel section owning a built-in key replaces that rail`() {
        val (sections, _) = mergePanelFeed(
            builtIn,
            VipRemoteConfig(
                sections = listOf(PanelSection(key = "movie", title = "Movies", items = listOf(post(7)))),
            ),
            dismissedBroadcastIds = emptySet(),
        )

        assertEquals(listOf("panel:movie", "recent", "series"), sections.map { it.key })
        assertEquals(listOf(7), sections[0].items.map { it.id })
    }

    @Test
    fun `a hidden row is dropped from panel and built-in rails alike`() {
        val (sections, _) = mergePanelFeed(
            builtIn,
            VipRemoteConfig(
                sections = listOf(PanelSection(key = "picks", title = "Picks", items = listOf(post(2), post(9)))),
                hiddenWorkIds = listOf(2),
            ),
            dismissedBroadcastIds = emptySet(),
        )

        assertEquals(listOf(9), sections[0].items.map { it.id })
        assertEquals(listOf(1), sections[1].items.map { it.id })
        assertEquals(listOf(3), sections[2].items.map { it.id })
    }

    @Test
    fun `an empty panel section renders nothing and a loading rail keeps loading`() {
        val (sections, _) = mergePanelFeed(
            builtIn,
            VipRemoteConfig(
                sections = listOf(PanelSection(key = "empty", title = "Empty", items = emptyList())),
            ),
            dismissedBroadcastIds = emptySet(),
        )

        assertEquals(listOf("recent", "movie", "series"), sections.map { it.key })
        assertTrue(sections[1].loading)
    }

    @Test
    fun `a second merge never duplicates a panel rail`() {
        val first = mergePanelFeed(builtIn, configWithPicks(), dismissedBroadcastIds = emptySet()).first
        val (second, _) = mergePanelFeed(first, configWithPicks(), dismissedBroadcastIds = emptySet())

        assertEquals(listOf("panel:picks", "recent", "movie", "series"), second.map { it.key })
    }

    @Test
    fun `a dismissed broadcast and a titleless one never show`() {
        val (_, broadcasts) = mergePanelFeed(
            builtIn,
            VipRemoteConfig(
                broadcasts = listOf(
                    PanelBroadcast(id = 1, title = "Hello", body = "Welcome"),
                    PanelBroadcast(id = 2, title = "Old", body = "Dismissed"),
                    PanelBroadcast(id = 3, title = "", body = "No title"),
                ),
            ),
            dismissedBroadcastIds = setOf(2),
        )

        assertEquals(listOf(1), broadcasts.map { it.id })
    }

    @Test
    fun `targeted broadcasts reach only their audience`() {
        val config = VipRemoteConfig(
            broadcasts = listOf(
                PanelBroadcast(id = 1, title = "All", body = "Everyone"),
                PanelBroadcast(id = 2, title = "Desi", body = "Desi", target = "region", targetDetail = "pakistan"),
                PanelBroadcast(id = 3, title = "VIP", body = "VIP", target = "vip"),
                PanelBroadcast(id = 4, title = "Build", body = "Build", target = "version", targetDetail = "1.0.4"),
                PanelBroadcast(id = 5, title = "Free", body = "Free", target = "free"),
            ),
        )
        // A Desi free viewer on build 1.0.4 sees all, Desi, the build note
        // and the free offer — but not the VIP notice.
        val (_, desiFree) = mergePanelFeed(
            builtIn, config, dismissedBroadcastIds = emptySet(),
            regionId = "desi_dubs", isVip = false, appVersion = "1.0.4",
        )
        assertEquals(listOf(1, 2, 4, 5), desiFree.map { it.id })
        // An East Asian VIP on another build sees all and the VIP notice
        // only — the region, version and free rows are not theirs.
        val (_, asianVip) = mergePanelFeed(
            builtIn, config, dismissedBroadcastIds = emptySet(),
            regionId = "east_asian", isVip = true, appVersion = "1.0.3",
        )
        assertEquals(listOf(1, 3), asianVip.map { it.id })
        // Before the tier has loaded, neither tiered broadcast shows.
        val (_, unknown) = mergePanelFeed(
            builtIn, config, dismissedBroadcastIds = emptySet(),
            regionId = "desi_dubs", isVip = null, appVersion = "1.0.4",
        )
        assertEquals(listOf(1, 2, 4), unknown.map { it.id })
    }

    @Test
    fun `no panel feed leaves the built-in rails exactly as they were`() {
        val (sections, broadcasts) = mergePanelFeed(builtIn, VipRemoteConfig(), dismissedBroadcastIds = emptySet())

        assertEquals(builtIn, sections)
        assertTrue(broadcasts.isEmpty())
    }

    private fun configWithPicks() = VipRemoteConfig(
        sections = listOf(PanelSection(key = "picks", title = "Picks", items = listOf(post(9)))),
    )

    private fun post(id: Int) = Post(id = id, title = "Title $id", cleanTitle = "Title $id")
}
