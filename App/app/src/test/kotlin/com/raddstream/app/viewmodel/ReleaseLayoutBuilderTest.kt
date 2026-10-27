package com.raddstream.app.viewmodel

import com.raddstream.app.network.models.Codec
import com.raddstream.app.network.models.CoverageType
import com.raddstream.app.network.models.HdrFormat
import com.raddstream.app.network.models.LinkState
import com.raddstream.app.network.models.ReleaseDetail
import com.raddstream.app.network.models.Resolution
import com.raddstream.app.network.models.SeasonArtwork
import com.raddstream.app.network.models.SourceDetail
import com.raddstream.app.network.models.SourceTag
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pins the SURVIVING presentation layer: `RankedPrint` fields read off the surviving
 * [com.raddstream.app.network.models.PrintDescriptor], the ranking (a CAM can never beat an
 * official print; rank = the print's own score on the 0..1000 print scale), the season/episode
 * grouping, the link health, and the capability chips.
 *
 * This test REPLACES the deleted `ReleaseParserTest`, so it also pins the behaviour that file
 * covered — the ranking, the season grouping, the size parsing, the language detection, the
 * hdr detection, the link health, and the capability chips — now asserted against the surviving
 * model so the collapse is provably behaviour-preserving (except the two documented deltas:
 * binary size units, and no fabricated resolution from a bare quality word).
 *
 * The tests feed the v1 free-TEXT columns (`release_title`, `quality`, `codec`, `size`,
 * `season`, `episode`, `languages`) exactly as `GET /api/v1/posts/{id}` serves them; every
 * structured field is derived by [ReleaseLabelParsing], never handed in.
 */
class ReleaseLayoutBuilderTest {

    /** One v1 release row: `ReleaseLayoutBuilder` reads every print field off its descriptor. */
    private fun release(
        id: Int,
        releaseTitle: String? = null,
        quality: String? = null,
        codec: String? = null,
        size: String? = null,
        season: String? = null,
        episode: String? = null,
        languages: String? = null,
        sources: List<SourceDetail> = emptyList(),
    ) = ReleaseDetail(
        id = id,
        releaseTitle = releaseTitle,
        quality = quality,
        codec = codec,
        size = size,
        season = season,
        episode = episode,
        languages = languages,
        sources = sources,
    )

    /** One link, built the way the v1 link view answers — classify() derives the rest. */
    private fun source(
        linkId: Int,
        status: String? = "active",
        kind: String = "direct",
        playability: String = "stream",
        ephemeral: Boolean = false,
        resumable: Boolean = true,
    ): SourceDetail = SourceDetail(
        streamId = "stream-$linkId",
        linkId = linkId,
        playUrl = "https://redirector.invalid/stream?id=stream-$linkId",
        label = "Fast direct",
        kind = kind,
        playability = playability,
        status = status,
        isTemporary = if (ephemeral) true else null,
        isResumable = if (resumable) true else null,
    )

    /** Movie prints land in [com.raddstream.app.viewmodel.ReleaseLayout.workPrints]. */
    private fun moviePrint(vararg releases: ReleaseDetail) =
        ReleaseLayoutBuilder.build(contentType = "movie", releases = releases.toList()).workPrints

    @Test
    fun `official prints rank above cam regardless of resolution`() {
        val layout = ReleaseLayoutBuilder.build(
            contentType = "movie",
            releases = listOf(
                release(id = 1, releaseTitle = "Movie 2160p CAM Telecine", quality = "2160p"),
                release(id = 2, releaseTitle = "Movie 1080p WEB-DL", quality = "1080p"),
            ),
        )
        val best = layout.workPrints.first()
        assertEquals(2, best.releaseId)
        assertFalse(best.isCam)
        // The print axis IS the surviving 0..1000 quality_score — a CAM is capped below any
        // official print there, and comparing it with the official print's own score is the
        // single ranking surface now (the deleted parser's tier-sum rankKey is gone).
        assertTrue(best.qualityScore > layout.workPrints.last().qualityScore)
        assertTrue(layout.workPrints.last().isCam)
        assertFalse(layout.isSeriesLike)
    }

    @Test
    fun `cam detection from telecine and hdts tokens`() {
        val layout = ReleaseLayoutBuilder.build(
            contentType = "movie",
            releases = listOf(
                release(id = 1, releaseTitle = "Movie 720p HDTS", quality = "720p"),
                release(id = 2, releaseTitle = "Movie 720p WEBRip", quality = "720p"),
            ),
        )
        val cam = layout.workPrints.first { it.isCam }
        assertEquals(1, cam.releaseId)
        assertEquals(1, layout.camPrintCount)
        assertEquals(1, layout.officialPrintCount)
    }

    @Test
    fun `a 4k cam still cannot outrank an official sd print`() {
        val layout = ReleaseLayoutBuilder.build(
            contentType = "movie",
            releases = listOf(
                release(id = 1, releaseTitle = "Big 2160p Telecine", quality = "2160p"),
                release(id = 2, releaseTitle = "Big 480p WEBRip", quality = "480p"),
            ),
        )
        val best = layout.workPrints.first()
        assertEquals(2, best.releaseId)
        assertFalse(best.isCam)
        assertEquals(Resolution.R480, best.resolution)
        assertTrue(layout.workPrints.first { it.releaseId == 1 }.isCam)
    }

    @Test
    fun `series prints group into seasons and episodes`() {
        val layout = ReleaseLayoutBuilder.build(
            contentType = "tv",
            releases = listOf(
                release(id = 1, releaseTitle = "Alpha S01 E01", season = "1", episode = "1"),
                release(id = 2, releaseTitle = "Alpha S01 E02", season = "1", episode = "2"),
                release(id = 3, releaseTitle = "Alpha S02 E01", season = "2", episode = "1"),
            ),
        )
        assertTrue(layout.isSeriesLike)
        assertEquals(2, layout.seasons.size)
        val s1 = layout.seasons.first { it.number == 1 }
        assertEquals(2, s1.episodes.size)
        assertEquals(1, s1.episodes.first().numberWithinSeason)
        assertEquals(3, layout.seasons.first { it.number == 2 }.episodes.first().absoluteNumber)
        assertTrue(layout.workPrints.isEmpty())
        assertEquals(3, layout.totalPrints)
    }

    @Test
    fun `season pack prints land in packedSeasons not seasons`() {
        val layout = ReleaseLayoutBuilder.build(
            contentType = "tv",
            releases = listOf(
                release(id = 1, releaseTitle = "Bob S01 Netflix Pack", season = "1"),
                release(id = 2, releaseTitle = "Bob S01 E01", season = "1", episode = "1"),
            ),
        )
        assertEquals(1, layout.seasons.size)
        val s1 = layout.seasons.first()
        assertEquals(1, s1.episodes.size)
        assertEquals(1, s1.packedPrints.size)
        assertEquals(listOf(1), layout.packedSeasons)
    }

    @Test
    fun `season pack with no per-episode rows stays honest and unparsed`() {
        val layout = ReleaseLayoutBuilder.build(
            contentType = "tv",
            releases = listOf(
                release(id = 1, releaseTitle = "Keanu Reeves Bombee Season Pack", season = "1"),
            ),
        )
        val season = layout.seasons.first()
        assertEquals(1, season.packedPrints.size)
        // We must NOT invent an episode count we don't have.
        assertTrue(season.episodes.isEmpty())
        assertEquals(0, season.episodeCount)
    }

    @Test
    fun `scope columns drive coverage and the season list stays populated`() {
        val layout = ReleaseLayoutBuilder.build(
            contentType = "series",
            releases = listOf(
                release(id = 1, releaseTitle = "Alice Season 1 Complete", season = "1"),
                release(id = 2, releaseTitle = "Alice S02 Ep 3-7", season = "2"),
                release(id = 3, releaseTitle = "Alice S02", season = "2", episode = "4"),
            ),
        )
        fun find(id: Int) = (layout.seasons.flatMap { it.packedPrints + it.episodes.flatMap { e -> e.prints } } +
            layout.workPrints).first { it.releaseId == id }
        val packed = find(1)
        assertEquals(CoverageType.SEASON_PACK, packed.coverage)
        assertTrue(packed.isPacked)
        assertEquals(1, packed.season)
        val range = find(2)
        assertEquals(CoverageType.EPISODE_RANGE, range.coverage)
        assertEquals(2, range.season)
        val ep = find(3)
        assertEquals(CoverageType.SINGLE_EPISODE, ep.coverage)
        assertEquals(4, ep.episodeFrom)
        assertEquals(4, ep.episodeTo)
        assertEquals(listOf(1), layout.packedSeasons)
    }

    @Test
    fun `link health maps status and ephemerality`() {
        val layout = ReleaseLayoutBuilder.build(
            contentType = "movie",
            releases = listOf(
                release(
                    id = 1, releaseTitle = "Movie 1080p", quality = "1080p",
                    sources = listOf(
                        source(linkId = 10, status = "dead", kind = "resolve", playability = "stream"),
                        source(linkId = 11, status = "active", kind = "direct", playability = "stream"),
                    ),
                ),
                release(
                    id = 2, releaseTitle = "Movie 720p", quality = "720p",
                    sources = listOf(
                        source(linkId = 12, status = "active", kind = "direct", playability = "stream", ephemeral = true),
                        source(linkId = 13, status = "active", kind = "download", playability = "download"),
                    ),
                ),
            ),
        )
        val print = layout.workPrints.first { it.releaseId == 1 }
        assertEquals(1, print.availableLinks) // dead link excluded
        val active = print.links.first { it.linkId == 11 }
        assertEquals(LinkState.ACTIVE, active.health)
        assertTrue(active.resumable)
        assertFalse(active.ephemeral)
        assertTrue(active.playableHere)
        // The download link counts as available (not dead) but is NOT playable here.
        val playable = layout.workPrints.first { it.releaseId == 2 }
        assertEquals(2, playable.availableLinks)
        assertTrue(playable.playableHere)
        assertFalse(playable.links.first { it.linkId == 13 }.playableHere)
        assertTrue(playable.links.first { it.linkId == 12 }.ephemeral)
    }

    @Test
    fun `an unseen status word degrades to UNKNOWN instead of a guess`() {
        val layout = ReleaseLayoutBuilder.build(
            contentType = "movie",
            releases = listOf(
                release(
                    id = 1, releaseTitle = "Movie 1080p", quality = "1080p",
                    sources = listOf(source(linkId = 90, status = "smouldering")),
                ),
                release(
                    id = 2, releaseTitle = "Movie 720p", quality = "720p",
                    sources = listOf(source(linkId = 91, status = "expired", kind = "download", playability = "download")),
                ),
            ),
        )
        val print = layout.workPrints.first { it.releaseId == 1 }
        // "smouldering" is not in the grammar — never silently "active".
        assertEquals(LinkState.UNKNOWN, print.links.first().health)
        assertEquals(1, print.availableLinks) // UNKNOWN is not DEAD
        // ...and an UNKNOWN-status link is still presentable by our one player: health != DEAD.
        assertTrue(print.playableHere)
        // `expired` degrades honestly too, and an EXPIRED link is not available.
        val expired = layout.workPrints.first { it.releaseId == 2 }
        assertEquals(LinkState.EXPIRED, expired.links.first().health)
        assertTrue(expired.links.first().health.isDead)
        assertEquals(0, expired.availableLinks)
    }

    @Test
    fun `size comes from the surviving grammar in binary units`() {
        // v1 serves size as TEXT; `ReleaseLabelParsing.detectSize` parses it BINARY (1024), the
        // server-faithful rule. `parseSizeBytes` is gone with the deleted parser.
        val print = moviePrint(release(id = 1, releaseTitle = "Film", size = "2.4GB")).first()
        assertEquals(2_576_980_378L, print.sizeBytes)
        assertNull(moviePrint(release(id = 2, releaseTitle = "Film", size = "unknown")).first().sizeBytes)
    }

    @Test
    fun `the size a print shows matches the size the print carries`() {
        // sizeBytes is BINARY, so the formatter that shows it must divide by 1024 too.
        // Dividing by 1000 printed the same file two ways: the release row's own "2.4 GB"
        // and a detail line claiming "2.6 GB" — and the download card, which reads sizeBytes
        // directly, agreed with neither.
        val print = moviePrint(release(id = 1, releaseTitle = "Film", size = "2.4GB")).first()
        assertTrue(
            "detailLine read \"${print.detailLine}\" for a 2.4GB print",
            print.detailLine.contains("2.4 GB"),
        )
    }

    @Test
    fun `languages come from the surviving grammar`() {
        val print = moviePrint(release(id = 1, releaseTitle = "Film", languages = "Hindi English Dual Audio")).first()
        assertTrue(print.languages.contains("Hindi"))
        assertTrue(print.languages.contains("English"))
        // No synthetic "Multi-audio" any more — the surviving grammar carries a real dualAudio flag.
        assertFalse(print.languages.contains("Multi-audio"))
        assertTrue(print.dualAudio)
    }

    @Test
    fun `hdr capability detected`() {
        val layout = ReleaseLayoutBuilder.build(
            contentType = "movie",
            releases = listOf(
                release(
                    id = 1,
                    releaseTitle = "Movie 2160p BluRay HDR10 Dolby Vision",
                    quality = "2160p",
                    codec = "x265",
                ),
            ),
        )
        assertTrue(layout.capabilities.contains("HDR"))
        val print = layout.workPrints.first()
        assertTrue(print.hasHdr)
        assertTrue(print.hdr.contains(HdrFormat.DOLBY_VISION))
        assertEquals(Resolution.R2160, print.resolution)
        assertEquals(Codec.H265, print.codec)
        assertEquals(SourceTag.UHD_BLURAY, print.sourceTag)
    }

    @Test
    fun `capability chips aggregate honestly across prints`() {
        val layout = ReleaseLayoutBuilder.build(
            contentType = "movie",
            releases = listOf(
                release(id = 1, releaseTitle = "Big 2160p WEB-DL", quality = "2160p", sources = listOf(source(1))),
                release(id = 2, releaseTitle = "Big 1080p BluRay HDR", quality = "1080p", languages = "Hindi English",
                    sources = listOf(source(2))),
            ),
        )
        assertTrue(layout.capabilities.contains("4K"))
        assertTrue(layout.capabilities.contains("HDR"))
        assertTrue(layout.capabilities.contains("1080p"))
        assertTrue(layout.capabilities.any { it.contains("audio", true) })
    }

    @Test
    fun `a bare hd label no longer fabricates a resolution`() {
        // The deleted ReleaseParser mapped a bare "HD" to 720p and "576"/"sd" to 480p by
        // guessing. The surviving model follows the server's rules and reports UNKNOWN instead
        // of inventing a rung.
        val print = moviePrint(release(id = 1, releaseTitle = "Some Movie", quality = "HD")).first()
        assertEquals(Resolution.UNKNOWN, print.resolution)
        // A plain "HD" quality token does NOT fabricate a resolution rung any more — the server
        // only recognises an explicit "720p". The badge still shows "HD" as the quality LABEL,
        // because `release_descriptor._quality_label` maps a bare hd word to the label "HD"
        // WITHOUT inventing a resolution — an honest label, not a fabricated rung.
        assertEquals("HD", print.qualityLabel)
        assertNull(print.codec)
        assertNull(print.edition)
    }

    @Test
    fun `the suspicious hd label keeps its rank and its work-level scope`() {
        // COLLAPSE PARITY. The deleted ReleaseParser read the free-text "HD" as 720p
        // (V1Resolution.fromText: wordMatch "hd" -> R720) and, with no season/episode/pack in
        // the label, gave it work-level scope (CoverageType.UNKNOWN -> a work print). The
        // surviving server-faithful grammar refuses to invent a resolution rung from a bare
        // "HD" (it stays Resolution.UNKNOWN) but STILL keeps the quality LABEL "HD"
        // (release_descriptor._quality_label does exactly this) and STILL treats it as a
        // whole-work film placed in workPrints. What must not change under the collapse is the
        // behaviour the parser was actually relied on for: the print keeps its WORK-LEVEL scope
        // and keeps its RANK below the official 1080p print — the ranking is never lost.
        val official = release(id = 2, quality = "1080p", releaseTitle = "WEB-DL x264")
        val streamed = release(id = 1, quality = "HD", releaseTitle = "Pathaan () Stream Server Cineverse")
        val layout = ReleaseLayoutBuilder.build(contentType = "movie", releases = listOf(streamed, official))

        // work-level, exactly as the deleted parser placed it (never routed into a season list).
        assertFalse(layout.isSeriesLike)
        assertEquals(2, layout.workPrints.size)
        assertTrue(layout.seasons.isEmpty())

        val rankedSuspicious = layout.workPrints.first { it.releaseId == 1 }
        // The quality WORD survives as an honest label even though no rung is invented.
        assertEquals("HD", rankedSuspicious.qualityLabel)
        assertEquals(Resolution.UNKNOWN, rankedSuspicious.resolution) // documented divergence
        // The whole-work film scope is the survivor's work-level marker (was MULTI/UNKNOWN before).
        assertEquals(CoverageType.WHOLE_WORK, rankedSuspicious.coverage)
        assertTrue(rankedSuspicious.isPacked) // one file for the whole work — not a bootleg pack

        // RANKING preserved: the official 1080p print leads, the suspicious HD was never promoted
        // above it — the collapse cannot silently lose the ordering the deleted parser produced.
        assertEquals(2, layout.workPrints.first().releaseId)
        assertEquals(1, layout.workPrints.last().releaseId)
        assertTrue(layout.workPrints.first().rankKey > rankedSuspicious.rankKey)
        assertTrue(layout.workPrints.first().isOfficialPrint)
    }

    @Test
    fun `a label naming a bridge server still renders no provenance`() {
        // Bridge-site tokens that once fed the removed service table must not leak into any
        // badge field; the badge stays a pure quality label.
        val print = moviePrint(
            release(id = 1, releaseTitle = "Movie 1080p Via Fastdl Com Vipe Common", quality = "1080p"),
        ).first()
        assertEquals("Full HD", print.qualityLabel)
        assertFalse(print.qualityLabel.lowercase().contains("fastdl"))
        assertFalse(print.qualityLabel.lowercase().contains("vipe"))
        assertFalse(print.qualityLabel.lowercase().contains("common"))
        assertFalse(print.detailLine.lowercase().contains("fastdl"))
        assertFalse(print.detailLine.lowercase().contains("vipe"))
        assertFalse(print.detailLine.lowercase().contains("common"))
        assertTrue(print.isOfficialPrint)
    }

    @Test
    fun `seasons receive distinct artwork and episodes get stills only from a real pool`() {
        val layout = ReleaseLayoutBuilder.build(
            contentType = "series",
            releases = listOf(
                release(id = 1, releaseTitle = "Show S01E01 1080p", season = "S01", episode = "E01"),
                release(id = 2, releaseTitle = "Show S02E01 1080p", season = "S02", episode = "E01"),
            ),
            artwork = listOf(
                "https://art.invalid/one.jpg",
                "https://art.invalid/two.jpg",
            ),
        )
        val seasons = layout.seasons.sortedBy { it.number }
        assertEquals(listOf("https://art.invalid/one.jpg", "https://art.invalid/two.jpg"), seasons.map { it.artworkUrl })
        assertEquals(
            listOf("https://art.invalid/one.jpg", "https://art.invalid/two.jpg"),
            seasons.sortedBy { it.number }.map { it.episodes.first().stillUrl },
        )
    }

    @Test
    fun `a single wide image never repeats down an episode list`() {
        val layout = ReleaseLayoutBuilder.build(
            contentType = "series",
            releases = listOf(
                release(id = 1, releaseTitle = "Show S01E01 1080p", season = "S01", episode = "E01"),
                release(id = 2, releaseTitle = "Show S01E02 1080p", season = "S01", episode = "E02"),
            ),
            artwork = listOf("https://art.invalid/only.jpg"),
        )
        val season = layout.seasons.single()
        assertEquals("https://art.invalid/only.jpg", season.artworkUrl)
        // One image cannot make distinct stills; null lets the row draw its branded fallback.
        assertTrue(season.episodes.all { it.stillUrl == null })
    }

    @Test
    fun `published season posters and episode stills beat the work pool`() {
        val layout = ReleaseLayoutBuilder.build(
            contentType = "series",
            releases = listOf(
                release(id = 1, releaseTitle = "Show S01E01 1080p", season = "S01", episode = "E01"),
                release(id = 2, releaseTitle = "Show S01E02 1080p", season = "S01", episode = "E02"),
                release(id = 3, releaseTitle = "Show S02E01 1080p", season = "S02", episode = "E01"),
            ),
            artwork = listOf("https://art.invalid/work-backdrop.jpg"),
            seasonArtwork = listOf(
                SeasonArtwork(kind = "season_poster", season = 1, url = "https://image.tmdb.org/s1.jpg"),
                SeasonArtwork(kind = "season_poster", season = 2, url = "https://image.tmdb.org/s2.jpg"),
                SeasonArtwork(kind = "episode_still", season = 1, episode = 1, url = "https://image.tmdb.org/e1.jpg"),
                SeasonArtwork(kind = "episode_still", season = 1, episode = 2, url = "https://image.tmdb.org/e2.jpg"),
                SeasonArtwork(kind = "episode_still", season = 2, episode = 1, url = "https://image.tmdb.org/e3.jpg"),
            ),
        )
        val s1 = layout.seasons.first { it.number == 1 }
        val s2 = layout.seasons.first { it.number == 2 }
        assertEquals("https://image.tmdb.org/s1.jpg", s1.artworkUrl)
        assertEquals("https://image.tmdb.org/s2.jpg", s2.artworkUrl)
        assertEquals(
            listOf("https://image.tmdb.org/e1.jpg", "https://image.tmdb.org/e2.jpg"),
            s1.episodes.sortedBy { it.numberWithinSeason }.map { it.stillUrl },
        )
        assertEquals("https://image.tmdb.org/e3.jpg", s2.episodes.single().stillUrl)
    }

    @Test
    fun `seasons without published art still fall back to the work pool`() {
        val layout = ReleaseLayoutBuilder.build(
            contentType = "series",
            releases = listOf(
                release(id = 1, releaseTitle = "Show S01E01 1080p", season = "S01", episode = "E01"),
                release(id = 2, releaseTitle = "Show S02E01 1080p", season = "S02", episode = "E01"),
            ),
            artwork = listOf(
                "https://art.invalid/one.jpg",
                "https://art.invalid/two.jpg",
            ),
            seasonArtwork = listOf(
                SeasonArtwork(kind = "season_poster", season = 2, url = "https://image.tmdb.org/s2.jpg"),
            ),
        )
        val s1 = layout.seasons.first { it.number == 1 }
        val s2 = layout.seasons.first { it.number == 2 }
        assertEquals("https://art.invalid/one.jpg", s1.artworkUrl)
        assertEquals("https://image.tmdb.org/s2.jpg", s2.artworkUrl)
        // The un-named season still draws from the pool; the named one uses its own still.
        assertNotNull(s1.episodes.single().stillUrl)
        assertEquals("https://art.invalid/two.jpg", s2.episodes.single().stillUrl)
    }
}
