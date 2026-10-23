package com.raddstream.app.viewmodel

import com.raddstream.app.network.models.ReleaseDetail
import com.raddstream.app.network.models.SourceDetail
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ReleaseParserTest {

    private fun release(
        id: Int,
        quality: String? = null,
        audio: String? = null,
        size: String? = null,
        codec: String? = null,
        episodeTitle: String? = null,
        seasonNumber: Int? = null,
        episodeNumber: Int? = null,
        sources: List<SourceDetail> = emptyList(),
    ) = ReleaseDetail(
        id = id,
        quality = quality,
        languages = audio,
        size = size,
        codec = codec,
        releaseTitle = episodeTitle,
        season = seasonNumber?.toString(),
        episode = episodeNumber?.toString(),
        sources = sources,
    )

    private fun source(id: Int, status: String = "active", temp: Int = 0, resumable: Int = 0) =
        SourceDetail(
            streamId = "h$id",
            linkId = id,
            playUrl = "http://127.0.0.1:8080/api/v1/stream?id=h$id",
            kind = "direct",
            label = "Fast direct",
            status = status,
            isTemporary = temp == 1,
            isResumable = resumable == 1,
        )

    @Test
    fun `official prints rank above cam regardless of resolution`() {
        val layout = ReleaseParser.build(
            contentType = "movie",
            releases = listOf(
                release(id = 1, quality = "CAM", episodeTitle = "Movie CAM Screener"),
                release(id = 2, quality = "1080p WEB-DL"),
            ),
        )
        val best = layout.workPrints.first()
        assertEquals(2, best.releaseId)
        assertFalse(best.isCam)
        assertTrue(layout.workPrints.last().isCam)
    }

    @Test
    fun `cam detection from telecine and hdts tokens`() {
        val layout = ReleaseParser.build(
            contentType = "movie",
            releases = listOf(
                release(id = 1, quality = "720p HDTS"),
                release(id = 2, quality = "WEBRip"),
            ),
        )
        val cam = layout.workPrints.first { it.isCam }
        assertEquals(1, cam.releaseId)
        assertEquals(1, layout.camPrintCount)
        assertEquals(1, layout.officialPrintCount)
    }

    @Test
    fun `series prints group into seasons and episodes`() {
        val layout = ReleaseParser.build(
            contentType = "series",
            releases = listOf(
                release(id = 1, quality = "1080p WEB-DL", episodeTitle = "Show S01E01 Pilot"),
                release(id = 2, quality = "1080p WEB-DL", episodeTitle = "Show S01E02"),
                release(id = 3, quality = "720p WEBRip", episodeTitle = "Show S02E01"),
            ),
        )
        assertTrue(layout.isSeriesLike)
        assertEquals(2, layout.seasons.size)
        val s1 = layout.seasons.first { it.number == 1 }
        assertEquals(2, s1.episodes.size)
        assertEquals(1, s1.episodes.first().numberWithinSeason)
        val s2 = layout.seasons.first { it.number == 2 }
        assertEquals(3, s2.episodes.first().absoluteNumber) // show-wide numbering continues
    }

    @Test
    fun `season pack with no per-episode rows stays honest and unparsed`() {
        val layout = ReleaseParser.build(
            contentType = "series",
            releases = listOf(
                release(id = 1, quality = "720p WEBRip", episodeTitle = "Season 1 Complete Batch"),
            ),
        )
        val season = layout.seasons.first()
        assertEquals(1, season.packedPrints.size)
        // We must NOT invent an episode count we don't have.
        assertTrue(season.episodes.isEmpty())
    }

    @Test
    fun `parseSizeBytes handles decimal and units`() {
        assertEquals(2_400_000_000L, ReleaseParser.parseSizeBytes("2.4GB"))
        assertEquals(800_000_000L, ReleaseParser.parseSizeBytes("800 MB"))
        assertNull(ReleaseParser.parseSizeBytes("unknown"))
        assertNull(ReleaseParser.parseSizeBytes(null))
    }

    @Test
    fun `parseLanguages detects known languages and dual audio`() {
        assertEquals(listOf("Hindi", "English"), ReleaseParser.parseLanguages("Hindi English Dual Audio"))
        assertEquals(listOf("Multi-audio"), ReleaseParser.parseLanguages("Dual Audio"))
        assertTrue(ReleaseParser.parseLanguages(null).isEmpty())
    }

    @Test
    fun `hdr capability detected`() {
        val layout = ReleaseParser.build(
            contentType = "movie",
            releases = listOf(
                release(id = 1, quality = "2160p BluRay HDR10", audio = "English", codec = "HEVC"),
            ),
        )
        assertTrue(layout.capabilities.contains("4K"))
        assertTrue(layout.capabilities.contains("HDR"))
        assertTrue(layout.workPrints.first().hasHdr)
    }

    @Test
    fun `link health maps status and ephemerality`() {
        val layout = ReleaseParser.build(
            contentType = "movie",
            releases = listOf(
                release(
                    id = 1,
                    quality = "1080p WEB-DL",
                    sources = listOf(
                        source(id = 10, status = "dead"),
                        source(id = 11, status = "active", temp = 1, resumable = 1),
                    ),
                ),
            ),
        )
        val print = layout.workPrints.first()
        assertEquals(1, print.availableLinks) // dead link excluded
        val active = print.links.first { it.linkId == 11 }
        assertEquals(LinkHealth.ACTIVE, active.health)
        assertTrue(active.ephemeral)
        assertTrue(active.resumable)
    }
}
