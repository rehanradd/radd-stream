package com.raddstream.app.viewmodel

import com.raddstream.app.data.local.SyncedProgressEntity
import com.raddstream.app.data.local.WatchHistoryEntity
import com.raddstream.app.data.local.WatchHistoryMerge
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The history screen is a record, not a to-do list: a finished title stays listed and says
 * so, and a row the app cannot route to is shown but never tapped. These are the rules the
 * row mapping and the shared fold now render, kept pure so no device is needed to check them.
 */
class WatchHistoryRowTest {

    private fun row(
        postId: Int = 7,
        season: Int = 0,
        episode: Int = 0,
        positionMs: Long = 30_000L,
        durationMs: Long = 120_000L,
        updatedAt: Long = 1_791_000_000_000L,
    ) = WatchHistoryEntity(
        workRef = "work-7",
        postId = postId,
        title = "Test Title",
        posterUrl = "https://example.test/poster.jpg",
        seasonNumber = season,
        episodeNumber = episode,
        positionMs = positionMs,
        durationMs = durationMs,
        updatedAt = updatedAt,
    )

    @Test
    fun `an episode names its scope and a movie names none`() {
        assertEquals("S2:E5", WatchHistoryRow.of(row(season = 2, episode = 5)).scopeLabel)
        assertNull(WatchHistoryRow.of(row()).scopeLabel)
    }

    @Test
    fun `progress is a fraction and a time left, like the rail`() {
        val mapped = WatchHistoryRow.of(row())
        assertEquals(0.25f, mapped.progressFraction!!, 0.0001f)
        assertEquals("1 min left", mapped.progressLabel)
        assertEquals("1 min left", mapped.statusLabel)
        assertFalse(mapped.finished)
    }

    @Test
    fun `a title watched to the end says finished, not a time left`() {
        val mapped = WatchHistoryRow.of(row(positionMs = 115_000L))
        assertTrue(mapped.finished)
        assertEquals("Finished", mapped.statusLabel)
        assertNull(mapped.progressLabel)
    }

    @Test
    fun `a barely started title is not finished`() {
        assertFalse(WatchHistoryRow.of(row(positionMs = 0L)).finished)
        assertFalse(WatchHistoryRow.of(row(positionMs = 5_000L)).finished)
    }

    @Test
    fun `an unknown duration is never finished and draws no bar`() {
        val mapped = WatchHistoryRow.of(row(positionMs = 45_000L, durationMs = 0L))
        assertFalse(mapped.finished)
        assertNull(mapped.progressFraction)
        assertNull(mapped.statusLabel)
    }

    @Test
    fun `the date is the day it was last watched`() {
        val expected = SimpleDateFormat("d MMM yyyy", Locale.getDefault())
            .format(Date(1_791_000_000_000L))
        assertEquals(expected, WatchHistoryRow.of(row()).dateLabel)
    }

    @Test
    fun `a row without a routable work is shown but never tapped`() {
        val mapped = WatchHistoryRow.of(row(postId = 0))
        assertFalse(mapped.tappable)
        assertTrue(WatchHistoryRow.of(row()).tappable)
    }

    @Test
    fun `mergeAll keeps a finished row the rail drops`() {
        val finished = row(positionMs = 115_000L)
        val resumable = row(
            workRef = "work-8",
            postId = 8,
            positionMs = 30_000L,
            updatedAt = 1_790_000_000_000L,
        )
        assertEquals(listOf(finished, resumable), WatchHistoryMerge.mergeAll(listOf(finished, resumable), emptyList()))
        assertEquals(listOf(resumable), WatchHistoryMerge.merge(listOf(finished, resumable), emptyList()))
    }

    @Test
    fun `mergeAll folds a newer synced position onto the local row`() {
        val local = row()
        val synced = SyncedProgressEntity(
            workRef = "work-7",
            seasonNumber = 0,
            episodeNumber = 0,
            positionSeconds = 60.0,
            durationSeconds = 120.0,
            clientUpdatedAt = 1_791_000_001.0,
        )
        val merged = WatchHistoryMerge.mergeAll(listOf(local), listOf(synced))
        assertEquals(1, merged.size)
        assertEquals(60_000L, merged[0].positionMs)
        assertEquals(1_791_000_001_000L, merged[0].updatedAt)
    }

    @Test
    fun `mergeAll drops a synced scope this device never watched`() {
        val synced = SyncedProgressEntity(
            workRef = "work-unknown",
            seasonNumber = 0,
            episodeNumber = 0,
            positionSeconds = 60.0,
            durationSeconds = 120.0,
            clientUpdatedAt = 1_791_000_001.0,
        )
        assertTrue(WatchHistoryMerge.mergeAll(listOf(row()), listOf(synced)).size == 1)
        assertTrue(WatchHistoryMerge.mergeAll(emptyList(), listOf(synced)).isEmpty())
    }

    @Test
    fun `mergeAll lists newest first and honours its limit`() {
        val older = row(workRef = "work-8", postId = 8, updatedAt = 1_790_000_000_000L)
        val newer = row(updatedAt = 1_791_000_000_000L)
        assertEquals(listOf(newer, older), WatchHistoryMerge.mergeAll(listOf(older, newer), emptyList()))
        assertEquals(listOf(newer), WatchHistoryMerge.mergeAll(listOf(older, newer), emptyList(), limit = 1))
    }
}
