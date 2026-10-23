package com.raddstream.app.data.cache

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * End-to-end orchestration test for the sweep: TTL expiry, user-keep protection, running-task
 * deferral, orphaned-temp leak reclamation, and low-storage eviction ordering — using an in-memory
 * fake store (no Room, no Android, no WorkManager).
 */
class CacheSweeperTest {

    private class FakeStore(
        var files: MutableList<CacheFileEntity>,
        var running: Set<String>,
        var osFree: Long,
        val ttl: TtlHours = TtlHours.THREE,
        val limits: StorageLimits = StorageLimits(10_000_000, 500, 10_000_000),
    ) : CacheSweepStore {
        val deletedRows = mutableListOf<String>()
        val removedOnDisk = mutableListOf<String>()
        override suspend fun liveFiles() = files.toList()
        override suspend fun runningFileIds() = running
        override suspend fun removeOnDisk(entity: CacheFileEntity) { removedOnDisk.add(entity.fileId) }
        override suspend fun deleteFileRow(fileId: String) { deletedRows.add(fileId); files.removeAll { it.fileId == fileId } }
        override suspend fun workspaceUsedBytes() = files.sumOf { it.sizeBytes }
        override suspend fun osFreeBytes() = osFree
        override fun limits() = limits
        override fun ttlHours() = ttl
    }

    private fun file(
        id: String,
        origin: CacheOrigin,
        created: Long,
        size: Long = 1000L,
        temp: Boolean = false,
        complete: Boolean = true,
        watch: Int = 0,
        lastAccess: Long = created,
    ) = CacheFileEntity(
        fileId = id, sourceKey = "src-$id", taskId = null, path = "/private/$id",
        sizeBytes = size, origin = origin.name, state = CacheTaskState.COMPLETED.name,
        isTemporary = temp, isComplete = complete,
        createdElapsedRealtime = created, lastAccessElapsedRealtime = lastAccess, watchCount = watch,
    )

    @Test
    fun `expired auto preview files are deleted, user-kept are spared`() {
        val store = FakeStore(
            files = mutableListOf(
                file("auto-old", CacheOrigin.AUTO_PREVIEW, created = 0L),
                file("user-kept", CacheOrigin.USER_KEEP, created = 0L),
                file("auto-fresh", CacheOrigin.AUTO_PREVIEW, created = 13_000_000L), // only ~0.3h old at 4h clock
            ),
            running = emptySet(),
            osFree = 1_000_000,
        )
        val clock = FixedUptimeClock(4L * 3_600_000L) // 4 hours in
        // sweep() is a suspend function; JVM unit tests have no coroutine context, so drive it
        // synchronously with runBlocking.
        val result = runBlocking { CacheSweeper(store, clock).sweep() }

        assertEquals(listOf("auto-old"), result.expiredDeleted)
        assertFalse(store.deletedRows.contains("user-kept"))
        assertFalse(store.deletedRows.contains("auto-fresh"))
    }

    @Test
    fun `file held by a running task is deferred not deleted`() {
        val store = FakeStore(
            files = mutableListOf(file("auto-loading", CacheOrigin.AUTO_PREVIEW, created = 0L)),
            running = setOf("auto-loading"),
            osFree = 1_000_000,
        )
        val clock = FixedUptimeClock(100L * 3_600_000L)
        // sweep() is a suspend function; JVM unit tests have no coroutine context, so drive it
        // synchronously with runBlocking.
        val result = runBlocking { CacheSweeper(store, clock).sweep() }
        assertEquals(1, result.deferredHeldByTasks)
        assertTrue(store.deletedRows.isEmpty())
    }

    @Test
    fun `orphaned temp file past grace is reclaimed as a leak`() {
        val store = FakeStore(
            files = mutableListOf(file("temp-orphan", CacheOrigin.AUTO_PREVIEW, created = 0L, temp = true)),
            running = emptySet(),
            osFree = 1_000_000,
        )
        val clock = FixedUptimeClock(TtlPolicy.TEMP_GRACE_MILLIS + 1)
        // sweep() is a suspend function; JVM unit tests have no coroutine context, so drive it
        // synchronously with runBlocking.
        val result = runBlocking { CacheSweeper(store, clock).sweep() }
        assertEquals(listOf("temp-orphan"), result.orphansDeleted)
    }

    @Test
    fun `low storage evicts least useful while protecting user kept`() {
        val store = FakeStore(
            files = mutableListOf(
                file("junk", CacheOrigin.AUTO_PREVIEW, created = 0L, temp = false, complete = false, watch = 0, lastAccess = 0L),
                file("prized", CacheOrigin.USER_KEEP, created = 0L, watch = 9, lastAccess = 0L),
            ),
            running = emptySet(),
            osFree = 100, // floor is 500 → must free 400
            limits = StorageLimits(10_000_000, 500, 10_000_000),
        )
        val clock = FixedUptimeClock(0L) // no TTL expiry (all fresh)
        // sweep() is a suspend function; JVM unit tests have no coroutine context, so drive it
        // synchronously with runBlocking.
        val result = runBlocking { CacheSweeper(store, clock).sweep() }
        assertEquals(listOf("junk"), result.evicted)
        assertFalse(store.deletedRows.contains("prized"))
    }

    @Test
    fun `nothing to do leaves the workspace untouched`() {
        val store = FakeStore(
            files = mutableListOf(file("fine", CacheOrigin.AUTO_PREVIEW, created = 3_500_000L)),
            running = emptySet(),
            osFree = 5_000_000,
        )
        val clock = FixedUptimeClock(3_600_000L)
        // sweep() is a suspend function; JVM unit tests have no coroutine context, so drive it
        // synchronously with runBlocking.
        val result = runBlocking { CacheSweeper(store, clock).sweep() }
        assertTrue(result.expiredDeleted.isEmpty())
        assertTrue(result.evicted.isEmpty())
        assertTrue(store.deletedRows.isEmpty())
    }
}
