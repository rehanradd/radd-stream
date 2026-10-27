package com.raddstream.app.viewmodel

import com.raddstream.app.data.local.WatchHistoryEntity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * The Continue watching rail is the only row set in the app that knows where a viewer stopped,
 * and it used to throw that away on the way to the screen. These are the rules the tile now
 * renders, kept pure so no device is needed to check them.
 */
class ContinueWatchingTileTest {

    @Test
    fun `an episode names its scope`() {
        assertEquals("S2:E5", ContinueWatchingTile.scopeLabel(2, 5))
    }

    @Test
    fun `a whole work invents no season`() {
        assertNull(ContinueWatchingTile.scopeLabel(0, 0))
        assertNull(ContinueWatchingTile.scopeLabel(2, 0))
        assertNull(ContinueWatchingTile.scopeLabel(0, 4))
    }

    @Test
    fun `progress is a fraction of the file that exists`() {
        assertEquals(
            0.25f,
            ContinueWatchingTile.progressFraction(30_000L, 120_000L)!!,
            0.0001f,
        )
    }

    @Test
    fun `an unknown duration draws no bar instead of a fake one`() {
        assertNull(ContinueWatchingTile.progressFraction(45_000L, 0L))
        assertNull(ContinueWatchingTile.progressFraction(45_000L, -1L))
    }

    @Test
    fun `a position past the end is clamped and promises no time left`() {
        assertEquals(1f, ContinueWatchingTile.progressFraction(130_000L, 120_000L)!!, 0.0001f)
        assertNull(ContinueWatchingTile.progressLabel(130_000L, 120_000L))
    }

    @Test
    fun `remaining time is spoken in the unit a viewer can use`() {
        assertEquals("Less than a minute left", ContinueWatchingTile.progressLabel(115_000L, 120_000L))
        assertEquals("23 min left", ContinueWatchingTile.progressLabel(7_000_000L, 8_380_000L))
        assertEquals("1 h 40 m left", ContinueWatchingTile.progressLabel(600_000L, 6_600_000L))
        assertEquals("2 h left", ContinueWatchingTile.progressLabel(0L, 7_200_000L))
        assertNull(ContinueWatchingTile.progressLabel(600_000L, 0L))
    }

    @Test
    fun `a tile carries both the bar and the words`() {
        val tile = ResumeTile.of(
            row(season = 1, episode = 9, positionMs = 601_000L, durationMs = 2_761_000L),
        )!!
        assertEquals("S1:E9", tile.scopeLabel)
        assertEquals("36 min left", tile.progressLabel)
        assertEquals("S1:E9 · 36 min left", tile.resumeLabel)
        assertEquals(0.2177f, tile.progressFraction!!, 0.001f)
    }

    @Test
    fun `a row the app cannot route to is no tile at all`() {
        assertNull(ResumeTile.of(row(season = 0, episode = 0).copy(postId = 0)))
    }

    @Test
    fun `a movie tile says time left without a scope`() {
        val tile = ResumeTile.of(
            row(season = 0, episode = 0, positionMs = 1_800_000L, durationMs = 9_000_000L),
        )!!
        assertNull(tile.scopeLabel)
        assertEquals("2 h left", tile.progressLabel)
        assertEquals("2 h left", tile.resumeLabel)
    }

    @Test
    fun `the stored title and art are what the tile shows`() {
        val tile = ResumeTile.of(row(season = 0, episode = 0))!!
        assertEquals(4241, tile.post.id)
        assertEquals("Circuit Breaker", tile.post.cleanTitle)
        assertEquals("Circuit Breaker", tile.post.title)
        assertEquals("https://art/CircuitBreaker.jpg", tile.post.posterUrl)
    }

    private fun row(
        season: Int,
        episode: Int,
        positionMs: Long = 5_000L,
        durationMs: Long = 60_000L,
    ) = WatchHistoryEntity(
        workRef = "wm:4241",
        postId = 4241,
        title = "Circuit Breaker",
        posterUrl = "https://art/CircuitBreaker.jpg",
        seasonNumber = season,
        episodeNumber = episode,
        positionMs = positionMs,
        durationMs = durationMs,
        updatedAt = 1_730_000_000_000L,
    )
}
