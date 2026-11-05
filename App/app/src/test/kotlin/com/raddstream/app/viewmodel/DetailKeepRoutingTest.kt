package com.raddstream.app.viewmodel

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The keep-routing decision for the P0 download fix (2026-11-06): a segmented playlist
 * goes to the keep engine, which fetches segments; everything else stays a device file.
 * The rule is the engine's own link-kind mapping, so the detail screen and the engine
 * can never disagree about what HLS is.
 */
class DetailKeepRoutingTest {

    @Test
    fun `hls mime goes to the keep engine`() {
        assertEquals(KeepTarget.EngineHls, keepTargetFor("application/vnd.apple.mpegurl"))
        assertEquals(KeepTarget.EngineHls, keepTargetFor("application/x-mpegURL"))
        assertEquals(KeepTarget.EngineHls, keepTargetFor("video/mp2t"))
        assertEquals(KeepTarget.EngineHls, keepTargetFor("APPLICATION/X-MPEGURL"))
    }

    @Test
    fun `progressive mime stays a device file`() {
        assertEquals(KeepTarget.DeviceFile, keepTargetFor("video/mp4"))
        assertEquals(KeepTarget.DeviceFile, keepTargetFor("video/x-matroska"))
        assertEquals(KeepTarget.DeviceFile, keepTargetFor("video/webm"))
        assertEquals(KeepTarget.DeviceFile, keepTargetFor("application/octet-stream"))
    }

    @Test
    fun `unknown mime stays a device file`() {
        assertEquals(KeepTarget.DeviceFile, keepTargetFor(null))
        assertEquals(KeepTarget.DeviceFile, keepTargetFor(""))
        assertEquals(KeepTarget.DeviceFile, keepTargetFor("text/html"))
    }
}
