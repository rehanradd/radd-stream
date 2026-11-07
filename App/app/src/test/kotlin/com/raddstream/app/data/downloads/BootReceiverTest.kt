package com.raddstream.app.data.downloads

import android.app.Service
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class BootReceiverTest {

    private fun entity(
        id: String,
        state: DeviceDownloadState,
    ) = DeviceDownloadEntity(
        id = id,
        handle = "h-$id",
        url = "http://example.com/$id",
        title = "Title $id",
        printLabel = "1080p",
        mimeType = "video/mp4",
        fileName = "file-$id.mp4",
        bytesTotal = 1000L,
        bytesDownloaded = 500L,
        state = state,
        enqueuedAt = 1000L,
    )

    @Test
    fun `recoverInterruptedEntries transitions DOWNLOADING to QUEUED`() {
        val list = listOf(
            entity("1", DeviceDownloadState.DOWNLOADING),
            entity("2", DeviceDownloadState.READY),
        )

        val (recovered, changed) = recoverInterruptedEntries(list)

        assertTrue(changed)
        assertEquals(DeviceDownloadState.QUEUED, recovered[0].state)
        assertEquals(500L, recovered[0].bytesDownloaded)
        assertEquals(DeviceDownloadState.READY, recovered[1].state)
    }

    @Test
    fun `recoverInterruptedEntries preserves PAUSED and FAILED without change`() {
        val list = listOf(
            entity("1", DeviceDownloadState.PAUSED),
            entity("2", DeviceDownloadState.FAILED),
            entity("3", DeviceDownloadState.QUEUED),
        )

        val (recovered, changed) = recoverInterruptedEntries(list)

        assertFalse(changed)
        assertEquals(DeviceDownloadState.PAUSED, recovered[0].state)
        assertEquals(DeviceDownloadState.FAILED, recovered[1].state)
        assertEquals(DeviceDownloadState.QUEUED, recovered[2].state)
    }

    @Test
    fun `startCommand returns START_REDELIVER_INTENT constant`() {
        // Guard ensuring DownloadService requests redelivery (3) rather than START_NOT_STICKY (2)
        assertEquals(3, Service.START_REDELIVER_INTENT)
    }
}
