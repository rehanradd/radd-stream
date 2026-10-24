package com.raddstream.app.data.cache

import javax.inject.Inject
import javax.inject.Provider
import javax.inject.Singleton

/**
 * The persistence seam the [CacheSweeper] needs, backed by the real Room DAOs and the
 * [StorageGate]. This is what turns the already-tested, already-pure [TtlPolicy] and
 * [EvictionPlanner] into actual auto-delete of a keep when its retention window closes, and
 * reclamation of an orphaned temp file left by a killed download — no new timer anywhere: the
 * window comes from the injected [TtlHours] and the arithmetic from [TtlPolicy].
 *
 * The retention window is provided lazily so a future user setting (3 vs 6 hours) is picked up on
 * every sweep instead of being frozen into a single constructed sweeper.
 */
@Singleton
class RoomCacheSweepStore @Inject constructor(
    private val fileDao: CacheFileDao,
    private val taskDao: CacheTaskDao,
    private val storage: StorageGate,
    private val ttlHoursProvider: Provider<TtlHours>,
) : CacheSweepStore {

    override suspend fun liveFiles(): List<CacheFileEntity> = fileDao.listLive()

    override suspend fun runningFileIds(): Set<String> = fileDao.runningTaskFileIds().toSet()

    override suspend fun removeOnDisk(entity: CacheFileEntity) {
        // A keep's fileId IS its sourceKey (set at finalize), and the gate names both the temp and
        // committed file after it, so one call clears whatever survived on disk for this row.
        storage.deleteOnDisk(entity.fileId)
    }

    override suspend fun deleteFileRow(fileId: String) {
        fileDao.deleteById(fileId)
        retireTaskForDeletedFile(fileId)
    }

    override suspend fun workspaceUsedBytes(): Long = storage.workspaceUsedBytes()

    override suspend fun osFreeBytes(): Long = storage.osFreeBytes()

    override fun limits(): StorageLimits = storage.limits()

    override fun ttlHours(): TtlHours = ttlHoursProvider.get()

    /**
     * When the sweeper deletes an auto-preview keep's bytes, that keep is no longer playable, so
     * its task row must leave the Downloads list too — retiring it here (never a new timer) is what
     * makes auto-delete honest on screen instead of leaving a phantom "ready" row. A user-keep's
     * file is protected and never reaches this path; anything still under a live task was DEFERRED
     * by [TtlPolicy] and not deleted, so we never yank bytes out from under an in-flight download.
     */
    private suspend fun retireTaskForDeletedFile(fileId: String) {
        val task = taskDao.getBySourceKey(fileId) ?: return
        if (task.originEnum != CacheOrigin.AUTO_PREVIEW) return
        val current = task.stateEnum
        if (CacheTaskStateMachine.canTransition(current, CacheTaskState.DELETED)) {
            taskDao.transition(task.id, current.name, CacheTaskState.DELETED.name)
        }
    }
}
