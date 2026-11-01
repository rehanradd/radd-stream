package com.raddstream.app.data.downloads

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Audit critical 9 — a download may only be marked READY when the bytes provably arrived
 * complete and as video. Every other outcome must be refused with a stated reason.
 */
class DownloadCompletionGateTest {

    @Test
    fun `a full video download passes the gate`() {
        assertNull(DownloadService.completionDefect(1_000, 1_000, "video/mp4"))
    }

    @Test
    fun `case and parameters in the content type still count as video`() {
        assertNull(DownloadService.completionDefect(500, 500, "VIDEO/H264; charset=binary"))
    }

    @Test
    fun `an empty download is refused`() {
        assertNotNull(DownloadService.completionDefect(0, 1_000, "video/mp4"))
        assertNotNull(DownloadService.completionDefect(-1, 1_000, "video/mp4"))
    }

    @Test
    fun `a partial download is refused and names the shortfall`() {
        val defect = DownloadService.completionDefect(400, 1_000, "video/mp4")
        assertEquals("Incomplete: 400 of 1000 bytes.", defect)
    }

    @Test
    fun `an unknown total cannot prove coverage and is refused`() {
        assertNotNull(DownloadService.completionDefect(400, 0, "video/mp4"))
    }

    @Test
    fun `a non-video content type is refused and names what arrived`() {
        assertEquals(
            "Unexpected content type: text/html.",
            DownloadService.completionDefect(1_000, 1_000, "text/html"),
        )
        assertEquals(
            "Unexpected content type: none.",
            DownloadService.completionDefect(1_000, 1_000, ""),
        )
    }

    @Test
    fun `emptiness outranks every other defect`() {
        assertEquals(
            "Downloaded nothing.",
            DownloadService.completionDefect(0, 0, "text/html"),
        )
    }
}
