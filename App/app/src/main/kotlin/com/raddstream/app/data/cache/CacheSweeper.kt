package com.raddstream.app.data.cache

/**
 * Persistence surface the TTL / low-storage sweep needs, abstracted so the orchestration is
 * pure and unit-testable and this file has NO Android or Room or WorkManager dependency
 * (WorkManager is not yet a Gradle dependency; the worker wrapper + enqueue code are delivered
 * in `docs/HANDOFF_appcache.md`).
 */
interface CacheSweepStore {
    suspend fun liveFiles(): List<CacheFileEntity>
    /** File ids currently owned by a QUEUED/LOADING task — those are never deleted. */
    suspend fun runningFileIds(): Set<String>
    /** Delete the bytes on disk for a file. */
    suspend fun removeOnDisk(entity: CacheFileEntity)
    /** Remove the inventory row after its bytes are gone. */
    suspend fun deleteFileRow(fileId: String)
    suspend fun workspaceUsedBytes(): Long
    suspend fun osFreeBytes(): Long
    fun limits(): StorageLimits
    fun ttlHours(): TtlHours
}

data class SweepResult(
    val expiredDeleted: List<String>,
    val orphansDeleted: List<String>,
    val evicted: List<String>,
    val deferredHeldByTasks: Int,
)

/**
 * The sweep entry point WorkManager calls. Two jobs, both driven by pure, already-tested policy
 * objects:
 *  1. TTL: auto-preview files older than the user's retention window are removed; user-kept
 *     files and files a live task owns are never touched; orphaned temp files (a killed download
 *     left behind) are reclaimed as leaks after the grace window.
 *  2. Low storage: if the volume dropped below the floor, evict least-useful files first until
 *     headroom is restored — never past protected files.
 *
 * @param clock monotonic clock so an expired auto-preview file cannot survive 6 real hours just
 *        because the phone was asleep, nor die early because the user changed the wall clock.
 */
class CacheSweeper(
    private val store: CacheSweepStore,
    private val clock: UptimeClock,
) {

    suspend fun sweep(): SweepResult {
        val now = clock.nowElapsedRealtime()
        val ttl = store.ttlHours()
        val running = store.runningFileIds()

        val expired = ArrayList<String>()
        val orphans = ArrayList<String>()
        var deferred = 0
        val survivors = ArrayList<CacheFileEntity>()

        for (file in store.liveFiles()) {
            val snapshot = file.toSnapshot(referencedByRunningTask = file.fileId in running)
            val verdict = TtlPolicy.evaluate(snapshot, now, ttl)
            when (verdict.decision) {
                TtlDecision.EXPIRE -> {
                    store.removeOnDisk(file)
                    store.deleteFileRow(file.fileId)
                    if (verdict.reason == TtlReason.ORPHANED_TEMP) orphans.add(file.fileId) else expired.add(file.fileId)
                }
                TtlDecision.DEFER -> deferred++
                TtlDecision.KEEP -> survivors.add(file)
            }
        }

        // Low-storage eviction pass over what survived TTL.
        val evicted = ArrayList<String>()
        val floor = store.limits().lowStorageFloorBytes
        val deficit = (floor - store.osFreeBytes()).coerceAtLeast(0L)
        if (deficit > 0L) {
            val candidates = survivors.map { it.toEvictionCandidate(referencedByRunningTask = it.fileId in running) }
            val plan = EvictionPlanner.plan(candidates, deficit, now)
            plan.deletions.forEach { c ->
                val entity = survivors.firstOrNull { it.fileId == c.fileId } ?: return@forEach
                store.removeOnDisk(entity)
                store.deleteFileRow(entity.fileId)
                evicted.add(entity.fileId)
            }
        }

        return SweepResult(expired, orphans, evicted, deferred)
    }
}
