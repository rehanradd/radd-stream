package com.raddstream.app.data.cache

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The SU-1 serve rule, judged without Room: a complete committed file wins,
 * a partial progressive file still plays up to its verified prefix, and
 * anything unverifiable serves nothing.
 */
class ServeFileSelectionTest {

    private fun file(
        fileId: String,
        path: String,
        taskId: Long? = 7L,
        sizeBytes: Long = 1_000L,
        isTemporary: Boolean = true,
        isComplete: Boolean = false,
    ) = CacheFileEntity(
        fileId = fileId,
        sourceKey = "key",
        taskId = taskId,
        path = path,
        sizeBytes = sizeBytes,
        isTemporary = isTemporary,
        isComplete = isComplete,
        createdElapsedRealtime = 0L,
        lastAccessElapsedRealtime = 0L,
    )

    @Test
    fun completeFileWinsOverPartial() {
        val complete = file("c", "/x/film.mp4", isTemporary = false, isComplete = true)
        val partial = file("p", "/x/film.mp4.part", sizeBytes = 500_000L)
        val choice = selectServeFile(listOf(partial, complete))
        assertTrue(choice is ServeFileChoice.Complete)
        assertEquals(complete, (choice as ServeFileChoice.Complete).file)
    }

    @Test
    fun partialProgressiveFileServesWithItsTask() {
        val partial = file("p", "/x/film.mp4", taskId = 42L, sizeBytes = 500_000L)
        val choice = selectServeFile(listOf(partial))
        assertTrue(choice is ServeFileChoice.Partial)
        choice as ServeFileChoice.Partial
        assertEquals(42L, choice.taskId)
        assertEquals(partial, choice.file)
    }

    @Test
    fun partialPlaylistServesNothing() {
        val partial = file("p", "/x/local.m3u8", sizeBytes = 500_000L)
        assertEquals(ServeFileChoice.None, selectServeFile(listOf(partial)))
    }

    @Test
    fun partialWithoutTaskCannotProveItsPrefix() {
        val partial = file("p", "/x/film.mp4", taskId = null, sizeBytes = 500_000L)
        assertEquals(ServeFileChoice.None, selectServeFile(listOf(partial)))
    }

    @Test
    fun emptyServesNothing() {
        assertEquals(ServeFileChoice.None, selectServeFile(emptyList()))
    }

    @Test
    fun completeButTemporaryIsTrustedByNeitherBranch() {
        val suspect = file("s", "/x/film.mp4", isTemporary = true, isComplete = true)
        assertEquals(ServeFileChoice.None, selectServeFile(listOf(suspect)))
    }

    @Test
    fun largestPartialWins() {
        val small = file("s", "/x/a.mp4", taskId = 1L, sizeBytes = 100L)
        val large = file("l", "/x/b.mp4", taskId = 2L, sizeBytes = 900L)
        val choice = selectServeFile(listOf(small, large))
        assertTrue(choice is ServeFileChoice.Partial)
        assertEquals(2L, (choice as ServeFileChoice.Partial).taskId)
    }
}
