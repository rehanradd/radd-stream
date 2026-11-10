package com.raddstream.app.ui.screens

import com.raddstream.app.network.models.ReleaseDetail
import com.raddstream.app.network.models.SourceDetail
import com.raddstream.app.viewmodel.ReleaseLayoutBuilder
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

/**
 * Robo run 6: two SD print cards (544 MB and 379 MB) both announced the
 * identical "Standard · Plays here" line — the label is the tier plus the
 * playability, and neither names the print. The spoken line now carries the
 * print's own facts (its codec/size detail line) and its copy number, so
 * each card speaks differently while the painted text stays the short label.
 * Pins [printSpokenLabel] against real prints built the way the detail
 * screen builds them.
 */
class PrintCardSpokenLabelTest {

    /** One SD release, the way the v1 link view answers it. */
    private fun release(id: Int, size: String) = ReleaseDetail(
        id = id,
        releaseTitle = "The Stranger",
        quality = "SD",
        codec = "H.264",
        size = size,
        sources = listOf(
            SourceDetail(
                streamId = "stream-$id",
                linkId = id,
                playUrl = "https://redirector.invalid/stream?id=stream-$id",
                label = "Standard",
                kind = "direct",
                playability = "stream",
                status = "active",
                isResumable = true,
            ),
        ),
    )

    private fun moviePrints(vararg releases: ReleaseDetail) =
        ReleaseLayoutBuilder.build(contentType = "movie", releases = releases.toList()).workPrints

    @Test
    fun twoPrintsAtOneQualitySpeakDifferentLabels() {
        val prints = moviePrints(release(1, "544 MB"), release(2, "379 MB"))
        assertEquals(2, prints.size)
        // Both paint the same short label — that is the bug's raw material.
        assertEquals(prints[0].bestOptionLabel, prints[1].bestOptionLabel)
        assertEquals("Standard · Plays here", prints[0].bestOptionLabel)
        // The spoken lines differ: each carries its own size and copy number.
        val spoken = prints.mapIndexed { index, print ->
            printSpokenLabel(print, copyIndex = index + 1, copyTotal = 2)
        }
        assertNotEquals(spoken[0], spoken[1])
        assertEquals("Standard · Plays here · H.264 · 544 MB, copy 1 of 2", spoken[0])
        assertEquals("Standard · Plays here · H.264 · 379 MB, copy 2 of 2", spoken[1])
    }

    @Test
    fun singleCopyOmitsTheCopyNumber() {
        val prints = moviePrints(release(1, "544 MB"))
        assertEquals(1, prints.size)
        assertEquals(
            "Standard · Plays here · H.264 · 544 MB",
            printSpokenLabel(prints[0], copyIndex = 1, copyTotal = 1),
        )
    }
}
