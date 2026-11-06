package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Data Saver caps the *start*, never the ladder: a viewer on mobile data
 * begins at 480p and may still switch up. Wi-Fi-only blocks a download
 * start outright — there is no cheaper rung to fall back to.
 */
class DataSaverTest {

    private val rungs = listOf("2160p", "1080p", "720p", "480p")

    @Test
    fun `data saver pulls a high start band down to 480p on mobile data`() {
        assertEquals("480p", DataSaver.capBand("1080p", rungs, dataSaver = true, onWifi = false))
        assertEquals("480p", DataSaver.capBand("720p", rungs, dataSaver = true, onWifi = false))
    }

    @Test
    fun `data saver leaves 480p, wi-fi and switched-off starts alone`() {
        assertEquals("480p", DataSaver.capBand("480p", rungs, dataSaver = true, onWifi = false))
        assertEquals("1080p", DataSaver.capBand("1080p", rungs, dataSaver = true, onWifi = true))
        assertEquals("1080p", DataSaver.capBand("1080p", rungs, dataSaver = false, onWifi = false))
    }

    @Test
    fun `data saver never names a rung the ladder does not have`() {
        val noLowRung = listOf("2160p", "1080p", "720p")
        assertEquals("1080p", DataSaver.capBand("1080p", noLowRung, dataSaver = true, onWifi = false))
        assertEquals("Auto", DataSaver.capBand("Auto", rungs, dataSaver = true, onWifi = false))
    }

    @Test
    fun `play prefer asks for the data-saving order only on mobile data`() {
        assertEquals("data_saver", DataSaver.playPrefer(dataSaver = true, onWifi = false))
        assertNull(DataSaver.playPrefer(dataSaver = true, onWifi = true))
        assertNull(DataSaver.playPrefer(dataSaver = false, onWifi = false))
    }

    @Test
    fun `wi-fi-only blocks mobile downloads and nothing else`() {
        assertTrue(DataSaver.wifiOnlyBlocks(wifiOnly = true, onWifi = false))
        assertFalse(DataSaver.wifiOnlyBlocks(wifiOnly = true, onWifi = true))
        assertFalse(DataSaver.wifiOnlyBlocks(wifiOnly = false, onWifi = false))
    }
}
