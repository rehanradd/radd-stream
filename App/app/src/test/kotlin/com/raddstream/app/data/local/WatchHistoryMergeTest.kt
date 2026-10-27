package com.raddstream.app.data.local

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class WatchHistoryMergeTest {

    private fun local(
        workRef: String = "ref-1",
        season: Int = 1,
        episode: Int = 2,
        positionMs: Long = 60_000,
        durationMs: Long = 600_000,
        updatedAt: Long = 1_000,
    ) = WatchHistoryEntity(
        workRef = workRef,
        postId = 7,
        title = "A title",
        posterUrl = null,
        seasonNumber = season,
        episodeNumber = episode,
        positionMs = positionMs,
        durationMs = durationMs,
        updatedAt = updatedAt,
    )

    private fun synced(
        workRef: String = "ref-1",
        season: Int = 1,
        episode: Int = 2,
        positionSeconds: Double = 120.0,
        clientUpdatedAt: Double = 10.0,
    ) = SyncedProgressEntity(
        workRef = workRef,
        seasonNumber = season,
        episodeNumber = episode,
        positionSeconds = positionSeconds,
        durationSeconds = 600.0,
        clientUpdatedAt = clientUpdatedAt,
    )

    @Test
    fun `a newer synced position replaces the local one for the same scope`() {
        val merged = WatchHistoryMerge.merge(listOf(local(updatedAt = 1_000)), listOf(synced()))

        assertEquals(1, merged.size)
        assertEquals(120_000L, merged.first().positionMs)
        assertEquals("A title", merged.first().title)
    }

    @Test
    fun `an older synced position never rewinds the local row`() {
        val merged = WatchHistoryMerge.merge(
            listOf(local(updatedAt = 50_000)),
            listOf(synced(clientUpdatedAt = 10.0)),
        )

        assertEquals(60_000L, merged.first().positionMs)
    }

    @Test
    fun `a synced scope with no local metadata is dropped rather than guessed`() {
        val merged = WatchHistoryMerge.merge(
            listOf(local()),
            listOf(synced(workRef = "ref-unknown")),
        )

        assertEquals(1, merged.size)
        assertEquals("ref-1", merged.first().workRef)
    }

    @Test
    fun `finished and not-started rows leave the rail`() {
        val merged = WatchHistoryMerge.merge(
            listOf(
                local(workRef = "done", positionMs = 595_000),
                local(workRef = "fresh", positionMs = 0),
                local(workRef = "watching", positionMs = 90_000),
            ),
            emptyList(),
        )

        assertEquals(listOf("watching"), merged.map { it.workRef })
    }

    @Test
    fun `rows are newest first and capped`() {
        val merged = WatchHistoryMerge.merge(
            listOf(
                local(workRef = "a", updatedAt = 1),
                local(workRef = "b", updatedAt = 3),
                local(workRef = "c", updatedAt = 2),
            ),
            emptyList(),
            limit = 2,
        )

        assertEquals(listOf("b", "c"), merged.map { it.workRef })
        assertTrue(merged.size <= 2)
    }
}
