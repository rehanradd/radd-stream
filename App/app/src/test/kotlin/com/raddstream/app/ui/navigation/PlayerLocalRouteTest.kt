package com.raddstream.app.ui.navigation

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The offline route must carry a finished download's own content/file URI through
 * the back stack unchanged, and it must encode the URI so its slashes cannot be
 * mistaken for path separators by Navigation.
 */
class PlayerLocalRouteTest {

    private val title = "Example Film (2024) 1080p"

    @Test
    fun contentUriRoundTrips() {
        val uri = "content://media/external/video/media/42"
        val route = Screen.PlayerLocal.createRoute(uri, title)
        assertEquals(2, route.count { it == '/' })
        val encoded = route.removePrefix("player_local/")
        val parts = encoded.split('/')
        assertEquals(uri, Screen.PlayerLocal.decode(parts[0]))
        assertEquals(title, Screen.PlayerLocal.decode(parts[1]))
    }

    @Test
    fun fileUriRoundTrips() {
        val uri = "file:///storage/emulated/0/Movies/RaddStream/Example%20Film.mp4"
        val route = Screen.PlayerLocal.createRoute(uri, title)
        val parts = route.removePrefix("player_local/").split('/')
        assertEquals(uri, Screen.PlayerLocal.decode(parts[0]))
        assertTrue(parts[0].startsWith("file%3A%2F%2F"))
    }
}
