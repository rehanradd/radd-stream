package com.raddstream.app.data.cache

import com.raddstream.app.di.CacheScope
import com.raddstream.app.player.AdoptRequest
import com.raddstream.app.player.CacheSessionKey
import com.raddstream.app.player.CacheSnapshot
import com.raddstream.app.player.CacheState
import com.raddstream.app.player.KeepResult
import com.raddstream.app.player.PlayheadTick
import com.raddstream.app.player.ProgressiveCacheEngine
import com.raddstream.app.player.StoragePressure
import com.raddstream.app.repository.CacheRepository
import com.raddstream.app.repository.KeepOutcome
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import java.util.concurrent.ConcurrentHashMap

/**
 * The single implementation of the player's [ProgressiveCacheEngine] boundary, bridged onto the
 * real [CacheCoordinator] and [CacheRepository]. The player was already coded against this
 * interface; before this class existed [com.raddstream.app.player.CacheEngineHolder.engine] was
 * always null, so the "keep this" affordance could only ever say "unavailable". Assigning an
 * instance to the holder at app start is what makes play-while-downloading real.
 *
 * PROVENANCE: every session the player hands us is keyed by OUR OWN redirector address, which we
 * reduce to an opaque handle here ([KeepIdentity.handleFromRedirectorUrl]) and then to a task key
 * ([KeepIdentity.sourceKeyFor]). A non-redirector address simply has no task, so the engine reports
 * null rather than inventing progress or touching a foreign host.
 */
@Singleton
class OfflineCacheEngine @Inject constructor(
    private val coordinator: CacheCoordinator,
    private val repository: CacheRepository,
    private val taskDao: CacheTaskDao,
    private val fileDao: CacheFileDao,
    private val storage: StorageGate,
    private val ttlHours: TtlHours,
    @CacheScope private val scope: CoroutineScope,
) : ProgressiveCacheEngine {

    private val observed = ConcurrentHashMap<String, StateFlow<CacheSnapshot?>>()

    @Volatile
    private var lastFreeBytes: Long = Long.MAX_VALUE

    override fun observe(key: CacheSessionKey): StateFlow<CacheSnapshot?> {
        val sourceKey = key.sourceKeyOrNull() ?: return emptySnapshot()
        return observed.getOrPut(sourceKey) {
            taskDao.observeBySourceKey(sourceKey)
                .map { task -> refreshPressure(task); task?.toSnapshot() }
                .stateIn(scope, SharingStarted.WhileSubscribed(stopTimeoutMillis = 5_000L), null)
        }
    }

    override suspend fun adopt(request: AdoptRequest): KeepResult {
        val handle = KeepIdentity.handleFromRedirectorUrl(request.url) ?: return KeepResult.EngineNotWired
        val outcome = repository.keep(
            handle = handle,
            title = "",
            sizeBytes = request.expectedTotalBytes,
            resumable = request.resumable,
            printLabel = request.printLabel,
        )
        return when (outcome) {
            is KeepOutcome.NoSpace ->
                KeepResult.StorageFull(requiredBytes = outcome.requiredBytes, availableBytes = outcome.availableBytes)
            KeepOutcome.Unavailable ->
                KeepResult.Failed("This copy can't be kept on the connected server.")
            is KeepOutcome.Enqueued, is KeepOutcome.AlreadyKept -> {
                val task = taskDao.getBySourceKey(KeepIdentity.sourceKeyFor(handle))
                if (task?.stateEnum == CacheTaskState.COMPLETED) {
                    KeepResult.Stored(localHandle = task.sourceKey, playableOffline = hasCommittedFile(task.sourceKey))
                } else {
                    // An offline keep is app-private and ages out on the retention window — say so
                    // honestly instead of claiming a permanent stored file.
                    KeepResult.OnlyPlayableInApp(
                        reason = "Saved for offline playback in this app only",
                        ttlSeconds = ttlHours.millis / 1000L,
                    )
                }
            }
        }
    }

    override suspend fun cancelKeep(key: CacheSessionKey) {
        val sourceKey = key.sourceKeyOrNull() ?: return
        taskDao.getBySourceKey(sourceKey)?.let { coordinator.cancelTask(it.id) }
    }

    override suspend fun release(key: CacheSessionKey) {
        key.sourceKeyOrNull()?.let(observed::remove)
    }

    override fun storagePressure(): StoragePressure = when {
        lastFreeBytes <= 0L -> StoragePressure.FULL
        lastFreeBytes < PRESSURE_NEAR_FULL_BYTES -> StoragePressure.NEAR_FULL
        else -> StoragePressure.OK
    }

    /** For an already-stored file, hand the player a local URI it can open; null = nothing complete. */
    override suspend fun playableUri(key: CacheSessionKey): String? {
        val sourceKey = key.sourceKeyOrNull() ?: return null
        val committed = fileDao.getBySourceKey(sourceKey).firstOrNull { it.isComplete && !it.isTemporary }
        return committed?.toLocalUri()?.toString()
    }

    /**
     * Feed the player's current position (in time) into the engine as an absolute byte offset, so
     * an opportunistic preview pass buffers ahead of the playhead. Only a redirector address with a
     * known total size maps to a byte; everything else is a no-op, never a guess.
     */
    suspend fun pumpPlayhead(tick: PlayheadTick) {
        val handle = KeepIdentity.handleFromRedirectorUrl(tick.url) ?: return
        val task = taskDao.getBySourceKey(KeepIdentity.sourceKeyFor(handle)) ?: return
        if (task.totalSizeBytes <= 0L || tick.durationMs <= 0L) return
        val byte = CoverageMapping.simple(task.totalSizeBytes, tick.durationMs / 1000.0)
            .fileByteAt(tick.positionMs / 1000.0)
        coordinator.onPlayheadAdvanced(task.sourceKey, byte)
    }

    private suspend fun refreshPressure(task: CacheTaskEntity?) {
        task ?: return
        lastFreeBytes = runCatching { storage.osFreeBytes() }.getOrDefault(lastFreeBytes)
    }

    private suspend fun hasCommittedFile(sourceKey: String): Boolean =
        fileDao.getBySourceKey(sourceKey).any { it.isComplete && !it.isTemporary }

    private fun CacheSessionKey.sourceKeyOrNull(): String? =
        KeepIdentity.handleFromRedirectorUrl(url)?.let { KeepIdentity.sourceKeyFor(it) }

    private fun emptySnapshot(): StateFlow<CacheSnapshot?> = MutableStateFlow<CacheSnapshot?>(null)

    private fun CacheTaskEntity.toSnapshot(): CacheSnapshot {
        val expires = if (originEnum == CacheOrigin.USER_KEEP) null else createdAtWallClock + ttlHours.millis
        val pausedForSpace = stateEnum == CacheTaskState.PAUSED && lastError == CacheCoordinator.ERR_NO_SPACE
        val state = when (stateEnum) {
            CacheTaskState.QUEUED, CacheTaskState.LOADING -> CacheState.KEEPING
            CacheTaskState.PAUSED -> if (pausedForSpace) CacheState.STORAGE_FULL else CacheState.INTERRUPTED
            CacheTaskState.COMPLETED -> CacheState.APP_PRIVATE_ONLY
            CacheTaskState.FAILED -> CacheState.FAILED
            CacheTaskState.EXPIRED -> CacheState.EXPIRED
            CacheTaskState.DELETED -> CacheState.EXPIRED
        }
        return CacheSnapshot(
            bytesSaved = downloadedBytes,
            totalBytes = totalSizeBytes.takeIf { it > 0 },
            bytesPerSec = 0L,
            isEstimate = false,
            resumable = true,
            previewExpiresAt = expires,
            state = state,
        )
    }

    companion object {
        private const val PRESSURE_NEAR_FULL_BYTES = 1L * 1024 * 1024 * 1024
    }
}
