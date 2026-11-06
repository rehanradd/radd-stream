package com.raddstream.app.viewmodel

import com.raddstream.app.data.downloads.DeviceDownload
import com.raddstream.app.data.downloads.DeviceDownloadState
import com.raddstream.app.data.local.WatchHistoryEntity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The Downloads rules: one list with files first, a keep-confirm size that
 * never guesses, and watched auto-delete that only ever names a finished
 * movie — never a half-watched film, never a series keep.
 */
class DownloadsRulesTest {

    private fun movieRow(
        title: String = "Example Film",
        positionMs: Long = 3_590_000L,
        durationMs: Long = 3_600_000L,
    ) = WatchHistoryEntity(
        workRef = "imdb:tt9999999",
        postId = 101,
        title = title,
        posterUrl = null,
        seasonNumber = 0,
        episodeNumber = 0,
        positionMs = positionMs,
        durationMs = durationMs,
        updatedAt = 1_000L,
    )

    @Test
    fun `a finished movie is a watched title, a half-watched one is not`() {
        val watched = watchedTitles(
            listOf(
                movieRow("Finished Film"),
                movieRow("Half Film", positionMs = 1_800_000L),
                movieRow("Unknown Length", durationMs = 0L),
                movieRow("", positionMs = 3_600_000L),
            ),
        )
        assertEquals(setOf("Finished Film"), watched)
    }

    @Test
    fun `the end guard is the same ten seconds the rail uses`() {
        // 9 seconds short of the end is still watching, not finished.
        val watched = watchedTitles(listOf(movieRow(positionMs = 3_600_000L - 9_000L)))
        assertEquals(setOf("Example Film"), watched)
        val notYet = watchedTitles(listOf(movieRow(positionMs = 3_600_000L - 11_000L)))
        assertTrue(notYet.isEmpty())
    }

    @Test
    fun `the keep-confirm size is a real size or an honest unknown`() {
        assertEquals("Size unknown", keepSizeLabel(null))
        assertEquals("Size unknown", keepSizeLabel(0L))
        assertEquals("2.5 MB", keepSizeLabel(2_500_000L))
        assertEquals("1.50 GB", keepSizeLabel(1_500_000_000L))
    }

    @Test
    fun `one list puts files first, then keeps`() {
        val state = DownloadsUiState(
            deviceDownloads = listOf(
                DeviceDownload(
                    id = "d1",
                    title = "A File",
                    printLabel = "720p",
                    state = DeviceDownloadState.READY,
                    bytesDownloaded = 10L,
                    bytesTotal = 10L,
                    localUri = null,
                    mimeType = "video/mp4",
                    fileName = "a.mp4",
                ),
            ),
            items = listOf(
                KeptItem(
                    id = "7",
                    title = "A Keep",
                    printLabel = "1080p",
                    bytesDownloaded = 10L,
                    bytesTotal = 10L,
                    state = KeepState.READY,
                    expiresAtMillis = null,
                ),
            ),
        )
        val rows = state.allDownloads
        assertEquals(2, rows.size)
        assertTrue(rows[0] is DownloadRow.Device)
        assertTrue(rows[1] is DownloadRow.Keep)
    }
}
