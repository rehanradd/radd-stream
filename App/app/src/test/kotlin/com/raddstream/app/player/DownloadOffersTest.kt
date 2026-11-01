package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * What the download sheet may promise. Three exclusions and one row shape, all of them the kind of
 * rule a viewer only discovers by tapping a row that cannot be downloaded.
 */
class DownloadOffersTest {

    private fun rung(
        band: String,
        handle: String = "h-$band",
        resumable: Boolean = true,
        page: Boolean = false,
        sizeBytes: Long? = 1_400_000_000,
        title: String = band,
    ) = QualityOption(
        band = band,
        title = title,
        streamId = handle,
        playUrl = "http://127.0.0.1:8080/api/v1/stream?id=$handle",
        sizeBytes = sizeBytes,
        backupHandles = emptyList(),
        playsHere = true,
        resumable = resumable,
        copies = 1,
        isProviderPage = page,
    )

    @Test
    fun `a provider page is never offered as a download`() {
        // A page is not a file. The ladder already knows which rung's winner is one.
        assertEquals(emptyList<String>(), DownloadOffers.eligible(listOf(rung("720p", page = true))).map { it.label })
        assertFalse(DownloadOffers.canOffer(listOf(rung("720p", page = true))))
    }

    @Test
    fun `a rung with no winner is never offered`() {
        // A blank handle is what the ladder documents for "this band had no link at all", which is
        // also exactly what a dead or unverified address looks like from here: nothing to fetch.
        assertTrue(DownloadOffers.eligible(listOf(rung("720p", handle = "  "))).isEmpty())
    }

    @Test
    fun `a file that cannot resume is never offered`() {
        assertTrue(DownloadOffers.eligible(listOf(rung("720p", resumable = false))).isEmpty())
    }

    @Test
    fun `the same file under two labels is offered once`() {
        val rows = DownloadOffers.eligible(listOf(rung("720p", handle = "one"), rung("1080p", handle = "one")))
        assertEquals(listOf("720p"), rows.map { it.label })
    }

    @Test
    fun `two spellings of one picture are one row`() {
        val rows = DownloadOffers.eligible(listOf(rung("2160p", handle = "a"), rung("4K", handle = "b")))
        assertEquals(listOf("4K"), rows.map { it.label })
    }

    @Test
    fun `the sheet is ordered cheapest picture first`() {
        val rows = DownloadOffers.eligible(listOf(rung("1080p"), rung("480p"), rung("720p")))
        assertEquals(listOf("480p", "720p", "1080p"), rows.map { it.label })
    }

    @Test
    fun `a row shows the picture and the size and nothing else`() {
        val row = DownloadOffers.eligible(listOf(rung("720p", sizeBytes = 1_400_000_000))).single()
        assertEquals("720p", row.label)
        assertEquals(QualityOption.formatBytes(1_400_000_000), row.size)
        assertEquals("720p", row.option.band)
    }

    @Test
    fun `an unmeasured file is still offered, without a size`() {
        val row = DownloadOffers.eligible(listOf(rung("480p", sizeBytes = null))).single()
        assertNull(row.size)
        assertEquals("480p", row.label)
    }

    @Test
    fun `no row of the sheet repeats the sentence that used to label the row`() {
        // "Download only" was the capability label the spec bans: it told the viewer what a row was
        // instead of offering it. Nothing a row shows may carry it, or any protocol word.
        val banned = listOf("download only", "hls", "not playable", "external", "embed")
        val rows = DownloadOffers.eligible(
            listOf(rung("720p", title = "HD · HLS"), rung("480p", title = "Not playable here")),
        )
        for (row in rows) {
            for (word in banned) {
                assertFalse("the sheet painted '${row.label}' / '${row.size}' for '$word'",
                    row.label.contains(word, ignoreCase = true))
                assertFalse("the sheet painted '${row.label}' / '${row.size}' for '$word'",
                    row.size?.contains(word, ignoreCase = true) == true)
            }
        }
        assertTrue(rows.isNotEmpty())
    }

    @Test
    fun `the download button exists only when something can be kept`() {
        assertFalse(DownloadOffers.canOffer(emptyList()))
        assertTrue(DownloadOffers.canOffer(listOf(rung("720p"), rung("720p", page = true))))
    }
}
