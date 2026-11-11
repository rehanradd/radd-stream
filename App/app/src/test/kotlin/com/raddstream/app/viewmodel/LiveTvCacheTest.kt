package com.raddstream.app.viewmodel

import com.raddstream.app.network.models.LiveTvChannel
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** App-design audit (2026-11-12, issue #13): the last good list survives a down server. */
class LiveTvCacheTest {

    private fun channel(id: Int, name: String) = LiveTvChannel(
        id = id,
        name = name,
        category = "news",
        country = "PK",
        language = "en",
        logoUrl = "",
        streamId = "stream-$id",
    )

    @Test
    fun roundTripsChannelsAndCategories() {
        val channels = listOf(channel(36, "ABC News"), channel(37, "Bloomberg TV"))
        val json = LiveTvCache.encode(channels, listOf("news"))
        val decoded = LiveTvCache.decode(json)
        assertEquals(channels, decoded?.first)
        assertEquals(listOf("news"), decoded?.second)
    }

    @Test
    fun blankOrBrokenJsonDecodesToNothing() {
        assertNull(LiveTvCache.decode(null))
        assertNull(LiveTvCache.decode(""))
        assertNull(LiveTvCache.decode("not json"))
        assertNull(LiveTvCache.decode(LiveTvCache.encode(emptyList(), emptyList())))
    }
}
