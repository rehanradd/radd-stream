package com.raddstream.app.repository

import com.raddstream.app.data.cache.AdmitDecision
import com.raddstream.app.data.cache.CacheCoordinator
import com.raddstream.app.data.cache.CacheOrigin
import com.raddstream.app.data.cache.CachePriority
import com.raddstream.app.data.cache.CacheTaskDao
import com.raddstream.app.data.cache.CacheTaskEntity
import com.raddstream.app.data.cache.CacheTaskState
import com.raddstream.app.data.cache.EvictionPlanner
import com.raddstream.app.data.cache.KeepSourceFactory
import com.raddstream.app.data.cache.StorageGate
import com.raddstream.app.data.cache.UptimeClock
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.Flow

/**
 * The one thing a caller asked to keep, and the honest verdict of the storage gate on it.
 *
 * The rule this type exists to enforce: a refusal is NEVER silently dropped. When the device
 * cannot absorb the file the caller gets [NoSpace] back and must say so out loud; a keep that
 * started gets [Enqueued]; tapping the same handle twice is [AlreadyKept], not a second download.
 */
sealed class KeepOutcome {
    /** A task row was inserted and the engine is driving it. */
    data class Enqueued(val taskId: Long) : KeepOutcome()

    /** This handle is already kept (or already downloading); nothing new started. */
    data class AlreadyKept(val taskId: Long) : KeepOutcome()

    /** The storage gate refused: free space is needed before a keep can start. */
    data class NoSpace(val requiredBytes: Long, val availableBytes: Long) : KeepOutcome()

    /** The handle could not be turned into one of our own redirector sources. */
    object Unavailable : KeepOutcome()
}

/**
 * The facade ViewModels talk to for offline keeps. It owns the enqueue decision — free-space
 * admission through [StorageGate]/[EvictionPlanner] and the retention origin that the existing
 * [com.raddstream.app.data.cache.TtlPolicy] ages out — and delegates every byte and every state
 * transition to [CacheCoordinator]. It invents no policy of its own.
 *
 * WHAT A KEEP IS HERE: priority [CachePriority.USER_REQUESTED] (an explicit ask downloads eagerly
 * and is never pre-empted by opportunistic preview work) with origin [CacheOrigin.AUTO_PREVIEW],
 * so it still ages out through the injected retention window after it finishes — exactly what the
 * owner asked for ("auto-delete after the configured window"), and deliberately NOT
 * [com.raddstream.app.data.cache.CacheCoordinator.keepNow], which would make it permanent.
 *
 * NO PROVENANCE LEAKS THROUGH: a keep is keyed by our own opaque handle. The only address ever
 * stored is [CacheTaskEntity.currentUrl], and the factory that produced it
 * ([KeepSourceFactory]) only ever builds our redirector. No site, hoster, or upstream URL is
 * accepted, stored, or returned here.
 */
@Singleton
class CacheRepository @Inject constructor(
    private val coordinator: CacheCoordinator,
    private val taskDao: CacheTaskDao,
    private val factory: KeepSourceFactory,
    private val storage: StorageGate,
    private val clock: UptimeClock,
) {

    /** Every keep that has not been auto-deleted or cancelled, newest first — the list UI feeds on. */
    fun tasksFlow(): Flow<List<CacheTaskEntity>> = taskDao.observeAllActive()

    /** A one-shot snapshot of the same list, for callers that are not observing. */
    suspend fun list(): List<CacheTaskEntity> = taskDao.listAllActive()

    /**
     * Keep one opaque handle for offline playback. Seeds it through our redirector, asks the
     * storage gate whether the device can absorb it, and only then inserts a task and hands it to
     * the engine. A refusal returns [KeepOutcome.NoSpace] instead of quietly doing nothing.
     */
    suspend fun keep(
        handle: String,
        title: String,
        sizeBytes: Long?,
        resumable: Boolean,
        printLabel: String = "",
    ): KeepOutcome {
        val seed = factory.seedForKeep(handle, sizeBytes, resumable) ?: return KeepOutcome.Unavailable

        val existing = taskDao.getBySourceKey(seed.sourceKey)
        if (existing != null && existing.stateEnum != CacheTaskState.DELETED) {
            // Already kept, or still downloading: re-arm the engine, never start a second copy.
            coordinator.startTask(seed.sourceKey)
            return KeepOutcome.AlreadyKept(existing.id)
        }

        when (val decision = admitGate(seed.totalSizeBytes)) {
            is AdmitDecision.Admit, is AdmitDecision.EvictThenAdmit -> Unit
            // `availableBytes` is the device's genuine free space, never the rule that
            // refused: the caller's sentence is "needs X, Y free", and a per-file cap or
            // a ceiling headroom is not free space.
            is AdmitDecision.RejectPerFileCap ->
                return KeepOutcome.NoSpace(decision.requestedBytes, storage.osFreeBytes())
            is AdmitDecision.RejectTooBigForCeiling ->
                return KeepOutcome.NoSpace(decision.requestedBytes, storage.osFreeBytes())
            is AdmitDecision.RejectNoEvictableHeadroom ->
                return KeepOutcome.NoSpace(seed.totalSizeBytes, storage.osFreeBytes())
        }

        val entity = CacheTaskEntity(
            sourceKey = seed.sourceKey,
            releaseId = seed.releaseId,
            linkKind = seed.linkKind,
            currentUrl = seed.redirectUrl,
            resourceId = seed.handle,
            title = title.trim(),
            printLabel = printLabel.trim(),
            origin = CacheOrigin.AUTO_PREVIEW.name,
            priority = CachePriority.USER_REQUESTED.name,
            state = CacheTaskState.QUEUED.name,
            totalSizeBytes = seed.totalSizeBytes,
            enqueueElapsedRealtime = clock.nowElapsedRealtime(),
            createdAtWallClock = System.currentTimeMillis(),
        )
        val insertedId = taskDao.insertIfAbsent(entity)
        val taskId = if (insertedId != -1L) insertedId
        else taskDao.getBySourceKey(seed.sourceKey)?.id ?: return KeepOutcome.Unavailable

        coordinator.startTask(seed.sourceKey)
        return KeepOutcome.Enqueued(taskId)
    }

    /** Abandon a keep: the engine stops its job, drops its bytes, and removes it from the list. */
    suspend fun cancel(taskId: Long) = coordinator.cancelTask(taskId)

    /** Re-drive a keep the engine parked (paused after a storage suspension or a retry backoff). */
    suspend fun resume(taskId: Long) {
        val task = taskDao.getById(taskId) ?: return
        coordinator.startTask(task.sourceKey)
    }

    /**
     * Run the pure [EvictionPlanner] admission against live device + workspace numbers. The engine's
     * own write-time gate re-checks every chunk; this is only the up-front "would a whole file ever
     * fit" question that lets us refuse a keep honestly BEFORE inserting a doomed row.
     */
    private suspend fun admitGate(requestedBytes: Long): AdmitDecision {
        val now = clock.nowElapsedRealtime()
        return EvictionPlanner.admit(
            requestedBytes = requestedBytes,
            currentUsedBytes = storage.workspaceUsedBytes(),
            osFreeBytes = storage.osFreeBytes(),
            limits = storage.limits(),
            candidates = storage.currentCandidates(now),
            nowElapsedRealtime = now,
        )
    }
}
