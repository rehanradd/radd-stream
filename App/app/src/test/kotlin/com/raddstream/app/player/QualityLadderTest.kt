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
    ) = LadderLink(
        streamId = id,
        playUrl = "http://127.0.0.1:8080/api/v1/stream?id=$id",
        kind = if (playable) "direct" else "download",
        playable = playable,
        status = if (dead) "dead" else "active",
        fileSizeBytes = size,
        isResumable = true,
        label = if (playable) "Fast direct" else "Standard",
    )

    private fun tier(
        band: String,
        label: String,
        link: LadderLink?,
        playable: Boolean = link?.playable == true,
        backups: List<String> = emptyList(),
        copies: Int = 3,
    ) = LadderTier(
        band = band,
        quality = band,
        label = label,
        mode = if (playable) "play" else "download_only",
        playable = playable,
        copies = copies,
        link = link,
        backupHandles = backups,
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
}
