package com.raddstream.app.data

import com.google.gson.Gson
import com.raddstream.app.network.models.VipRemoteConfig
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The board the app obeys is a copy of the board the server publishes, and the copy is what
 * every entry point reads. So the two must default the same way: a deployment whose remote-config
 * body says nothing at all gets the app it shipped with, with nothing switched off.
 */
class RemoteFeaturesTest {

    @Test
    fun `a board nobody has filled in turns nothing off`() {
        val board = RemoteFeatures()
        assertTrue(board.downloads)
        assertTrue(board.sharing)
        assertTrue(board.search)
        assertTrue(board.pureCinema)
    }

    @Test
    fun `the board defaults exactly where the wire defaults`() {
        val wire = Gson().fromJson("""{"success": true}""", VipRemoteConfig::class.java).featureFlags
        val board = RemoteFeatures()
        assertEquals(wire.downloads, board.downloads)
        assertEquals(wire.sharing, board.sharing)
        assertEquals(wire.search, board.search)
        assertEquals(wire.pureCinema, board.pureCinema)
    }

    @Test
    fun `one switch off is exactly one feature off`() {
        val board = RemoteFeatures(search = false)
        assertFalse(board.search)
        assertTrue(board.downloads)
        assertTrue(board.sharing)
        assertTrue(board.pureCinema)
    }
}
