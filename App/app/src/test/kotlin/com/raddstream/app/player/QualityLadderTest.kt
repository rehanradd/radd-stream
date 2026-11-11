package com.raddstream.app.player

import com.raddstream.app.network.models.LadderAuto
import com.raddstream.app.network.models.LadderLink
import com.raddstream.app.network.models.LadderTier
import com.raddstream.app.network.models.OptionGroup
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The ladder is the server's decision, delivered as data; the app's only job is to
 * render it without inventing anything. These tests pin that: one row per rung, Auto
 * pointing where the server pointed, a rung that cannot play saying so, and no scope
 * ever borrowing another episode's links.
 *
 * Lives in `player` because the view-state it tests ([QualityLadder], [LadderForScope],
 * [QualityOption]) is the player-local rung model; the wire types it maps FROM
 * ([OptionGroup], [LadderTier], [LadderLink], [LadderAuto]) belong to `network/models`.
 */
class QualityLadderTest {

    private fun link(
        id: String,
        playable: Boolean = true,
        size: Long? = 1_400_000_000,
        dead: Boolean = false,
        mimeType: String? = null,
    ) = LadderLink(
        streamId = id,
        playUrl = "http://127.0.0.1:8080/api/v1/stream?id=$id",
        kind = if (playable) "direct" else "download",
        playable = playable,
        status = if (dead) "dead" else "active",
        fileSizeBytes = size,
        isResumable = true,
        mimeType = mimeType,
        label = if (playable) "Fast direct" else "Standard",
    )

    private fun tier(
        band: String,
        label: String,
        link: LadderLink?,
        playable: Boolean = link?.playable == true,
        backups: List<String> = emptyList(),
        copies: Int = 3,
        audioLanguages: List<String> = emptyList(),
    ) = LadderTier(
        band = band,
        quality = band,
        label = label,
        mode = if (playable) "play" else "download_only",
        playable = playable,
        copies = copies,
        link = link,
        backupHandles = backups,
        audioLanguages = audioLanguages,
    )

    private val ladder = OptionGroup(
        season = null,
        episode = null,
        tiers = listOf(
            tier("2160p", "4K Ultra HD", link("h-4k")),
            tier("1080p", "Full HD", link("h-1080"), backups = listOf("b-1", "b-2")),
            tier("720p", "HD", link("h-720")),
            tier("480p", "Good", link("h-480", playable = false, size = 320_000_000)),
        ),
        auto = LadderAuto(band = "1080p", reason = "best", streamId = "h-1080"),
        downloadOnlyBands = listOf("480p"),
    )

    @Test
    fun `one rung is one row and the server order is kept`() {
        val scope = QualityLadder.from(ladder)
        assertEquals(listOf("2160p", "1080p", "720p", "480p"), scope.options.map { it.band })
        assertEquals(listOf("4K Ultra HD", "Full HD", "HD", "Good"), scope.options.map { it.title })
        assertEquals("1080p", scope.autoBand)
        assertEquals("1080p", scope.autoOption?.band)
    }

    @Test
    fun `a rung whose only copy cannot play is labelled download only, never hidden`() {
        val sd = QualityLadder.from(ladder).options.last()
        assertEquals("480p", sd.band)
        assertFalse(sd.playsHere)
        assertTrue(sd.downloadOnly)
        assertTrue(sd.detailLine.contains(QualityOption.KEEPS_ONLY))
        // A rung with no winner at all cannot be offered — there is no copy to name.
        val empty = QualityLadder.from(ladder.copy(tiers = ladder.tiers + LadderTier(band = "sd")))
        assertFalse(empty.options.any { it.band == "sd" })
    }

    @Test
    fun `the runner-ups of a rung travel with it and never include the winner`() {
        val hd = QualityLadder.from(ladder).options.first { it.band == "1080p" }
        assertEquals(listOf("b-1", "b-2"), hd.backupHandles)
        assertFalse(hd.streamId in hd.backupHandles)
    }

    @Test
    fun `auto is the server pointer and an unknown band falls back to the best`() {
        val scope = QualityLadder.from(ladder)
        assertEquals("h-1080", scope.resolvedFor(LadderForScope.AUTO)?.streamId)
        assertEquals("h-4k", scope.resolvedFor("2160p")?.streamId)
        assertEquals("h-1080", scope.resolvedFor("8000p")?.streamId)
        assertEquals("h-1080", scope.resolvedFor(null)?.streamId)
    }

    @Test
    fun `sizes are ours to read and absent when the server never measured one`() {
        val hd = QualityLadder.from(ladder).options.first { it.band == "1080p" }
        assertEquals("≈ 1.3 GB", hd.detailLine.substringBefore(" · "))
        val unknown = QualityLadder.from(ladder.copy(tiers = listOf(tier("720p", "HD", link("h", size = null)))))
        assertEquals(PLAYABLE_HERE, unknown.options.single().detailLine)
        assertEquals("1.0 KB", QualityOption.formatBytes(1024))
        assertEquals("1.0 GB", QualityOption.formatBytes(1024L * 1024 * 1024))
    }

    @Test
    fun `a probe that measured bytes, not a file, shows no size at all`() {
        // Session 121 (P-8): a 3.05 GB film once arrived with sizeBytes 513 — a probe
        // that measured a redirect, not the file — and rendered as "≈ 513 B". A size
        // under 1 MB is not a video; the row shows only what the rung can do.
        val tiny = QualityLadder.from(
            ladder.copy(tiers = listOf(tier("1080p", "Full HD", link("h", size = 513))))
        ).options.single()
        assertNull(tiny.sizeLine)
        assertEquals(PLAYABLE_HERE, tiny.detailLine)
        // The boundary: exactly 1 MB is a real (if tiny) file and still shows.
        val edge = QualityLadder.from(
            ladder.copy(tiers = listOf(tier("1080p", "Full HD", link("h", size = 1_000_000))))
        ).options.single()
        assertEquals("977 KB", edge.sizeLine)
    }

    @Test
    fun `a scope is matched on the served text and never borrows another episode`() {
        val groups = listOf(
            ladder.copy(season = "1", episode = "1"),
            ladder.copy(season = "1", episode = "2", auto = LadderAuto(band = "720p")),
        )
        val second = QualityLadder.forScope(groups, "1", "2")
        assertEquals("720p", second.autoBand)
        assertEquals("1080p", QualityLadder.forScope(groups, " 1 ", "1").autoBand)
        // An episode the ladder has nothing for shows nothing — not another episode's links.
        assertTrue(QualityLadder.forScope(groups, "1", "7").isEmpty)
        assertTrue(QualityLadder.forScope(emptyList(), null, null).isEmpty)
        assertNull(QualityLadder.forScope(groups, "1", "7").autoBand)
    }

    @Test
    fun `a rung without a handle is not offered at all`() {
        val scope = QualityLadder.from(
            ladder.copy(tiers = listOf(tier("1080p", "Full HD", link("").copy(streamId = "  ")))),
        )
        assertTrue(scope.isEmpty)
    }

    @Test
    fun `a manifest mime names an instant stream, a file mime names its container`() {
        val hls = streamCategoryFor("application/vnd.apple.mpegurl", "http://127.0.0.1:8080/api/v1/stream?id=x")
        assertEquals(StreamCategory.Kind.INSTANT_STREAM, hls?.kind)
        assertEquals("Instant Stream · M3U8", hls?.label)
        val dash = streamCategoryFor("application/dash+xml", null)
        assertEquals(StreamCategory.Kind.INSTANT_STREAM, dash?.kind)
        assertEquals("Instant Stream · DASH", dash?.label)
        val mp4 = streamCategoryFor("video/mp4", null)
        assertEquals(StreamCategory.Kind.DIRECT_FILE, mp4?.kind)
        assertEquals("Direct File · MP4", mp4?.label)
        assertEquals("MKV", streamCategoryFor("video/x-matroska", null)?.container)
        assertEquals("WebM", streamCategoryFor("video/webm", null)?.container)
    }

    @Test
    fun `an unmeasured copy claims no stream category`() {
        assertNull(streamCategoryFor(null, "http://127.0.0.1:8080/api/v1/stream?id=x"))
        assertNull(streamCategoryFor("text/html", null))
        assertNull(streamCategoryFor("audio/mpeg", null))
        assertNull(streamCategoryFor("", null))
    }

    @Test
    fun `a rung carries its print's audio languages and its copy's stream shape`() {
        val scope = QualityLadder.from(
            ladder.copy(
                tiers = listOf(
                    tier(
                        "1080p", "Full HD",
                        link("h-1080", mimeType = "video/mp4"),
                        audioLanguages = listOf("Hindi", "English"),
                    ),
                    tier(
                        "720p", "HD",
                        link("h-720", mimeType = "application/vnd.apple.mpegurl"),
                        audioLanguages = listOf("English"),
                    ),
                ),
            ),
        )
        val hd = scope.options.first { it.band == "1080p" }
        assertEquals(listOf("Hindi", "English"), hd.audioLanguages)
        assertEquals("Direct File · MP4", hd.streamCategory?.label)
        val sd = scope.options.first { it.band == "720p" }
        assertEquals(listOf("English"), sd.audioLanguages)
        assertEquals("Instant Stream · M3U8", sd.streamCategory?.label)
        // A rung with neither measurement shows neither line.
        val bare = QualityLadder.from(
            ladder.copy(tiers = listOf(tier("480p", "Good", link("h-480")))),
        ).options.single()
        assertEquals(emptyList<String>(), bare.audioLanguages)
        assertNull(bare.streamCategory)
    }

    @Test
    fun `the screen counts a scope the way the ledger stamps it`() {
        // Importers write `S01`/`E05`; the screen holds 1 and 5. Both are our own columns,
        // so the lookup must join them — and must never answer with a neighbour episode.
        val groups = listOf(
            ladder.copy(season = "S01", episode = null, auto = LadderAuto(band = "2160p")),
            ladder.copy(season = "S01", episode = "E01", auto = LadderAuto(band = "1080p")),
            ladder.copy(season = "S01", episode = "E05", auto = LadderAuto(band = "720p")),
            ladder.copy(season = "S02", episode = "E01", auto = LadderAuto(band = "480p")),
        )
        assertEquals("720p", QualityLadder.forNumberedScope(groups, 1, 5).autoBand)
        assertEquals("1080p", QualityLadder.forNumberedScope(groups, 1, 1).autoBand)
        assertEquals("480p", QualityLadder.forNumberedScope(groups, 2, 1).autoBand)
        // The packed-season group is the season's own scope, never an episode's.
        assertEquals("2160p", QualityLadder.forNumberedScope(groups, 1, null).autoBand)
        assertTrue(QualityLadder.forNumberedScope(groups, 1, 9).isEmpty)
        assertTrue(QualityLadder.forNumberedScope(groups, 3, 1).isEmpty)
        // A work with no scope columns at all is still the whole title.
        assertEquals("1080p", QualityLadder.forNumberedScope(listOf(ladder), null, null).autoBand)
        // A season that shipped episode files has no season-level ladder to show.
        assertTrue(QualityLadder.forNumberedScope(groups.drop(0), 2, null).isEmpty)
    }

    // Audit #32: the quality card leads with the viewer's own audio.

    private fun option(band: String, audio: List<String>) = QualityOption(
        band = band,
        title = band,
        streamId = "h-$band",
        playUrl = null,
        sizeBytes = null,
        backupHandles = emptyList(),
        playsHere = true,
        resumable = false,
        copies = 1,
        audioLanguages = audio,
        // A playable stream rung, not a provider page.
        isProviderPage = false,
    )

    @Test
    fun `desi region leads with hindi and urdu`() {
        assertEquals(setOf("Hindi", "Urdu"), preferredAudioLanguages("desi_dubs"))
        assertEquals(setOf("Hindi", "Urdu"), preferredAudioLanguages("  DESI_DUBS "))
        assertEquals(emptySet<String>(), preferredAudioLanguages("international"))
        assertEquals(emptySet<String>(), preferredAudioLanguages("east_asian"))
        // No region stored yet falls back to the shipped default (Desi),
        // so it leads with Hindi and Urdu like any fresh install.
        assertEquals(setOf("Hindi", "Urdu"), preferredAudioLanguages(null))
    }

    @Test
    fun `preferred audio rows lead and the rest keep their order`() {
        val options = listOf(
            option("2160p", listOf("English")),
            option("1080p", listOf("Hindi", "English")),
            option("720p", listOf("English")),
            option("480p", listOf("Urdu")),
        )
        val ordered = preferredAudioFirst(options, preferredAudioLanguages("desi_dubs"))
        assertEquals(listOf("1080p", "480p", "2160p", "720p"), ordered.map { it.band })
        // No preferred audio on the wire: the server order stands.
        assertEquals(options, preferredAudioFirst(options, emptySet()))
        // Case is the catalog's, not the viewer's: "hindi" still counts.
        assertTrue(carriesPreferredAudio(option("720p", listOf("hindi")), setOf("Hindi")))
        assertFalse(carriesPreferredAudio(option("720p", listOf("English")), setOf("Hindi", "Urdu")))
    }
}
