package com.raddstream.app.ui.navigation

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

/**
 * The provider-page route carries the server's OPAQUE HANDLE, exactly like [Screen.Player]'s does,
 * and for the same reason: a route argument survives into the back stack, into saved state and into
 * a deep link, so an address put here is an address that has left the app.
 */
class EmbedRouteTest {

    private val title = "Gunday (2024) Hindi Dubbed"

    @Test
    fun `a handle carrying route separators survives the round trip`() {
        val handle = "lh/7?x=1%2F2"
        val route = Screen.Embed.createRoute(handle, title)
        assertEquals(2, route.count { it == '/' })
        val parts = route.removePrefix("embed/").split('/')
        assertEquals(handle, Screen.Embed.decodeStreamId(parts[0]))
        assertEquals(title, Screen.Embed.decodeTitle(parts[1]))
    }

    @Test
    fun `the route never carries a url`() {
        val route = Screen.Embed.createRoute("https://host.example/embed/abc", "Film")
        // Two separators, ever: the route's own, and nothing from the value put into it. A
        // scheme's `://` surviving here would mean Navigation sees a path this app never made.
        assertEquals(2, route.count { it == '/' })
        assertFalse(route.contains("://"))
        val parts = route.removePrefix("embed/").split('/')
        assertEquals(
            "https://host.example/embed/abc",
            Screen.Embed.decodeStreamId(parts[0]),
        )
    }

    @Test
    fun `the route template names the arguments the screen reads`() {
        assertEquals("embed/{streamId}/{title}", Screen.Embed.route)
        assertEquals("streamId", Screen.Embed.ARG_STREAM_ID)
        assertEquals("title", Screen.Embed.ARG_TITLE)
    }
}
