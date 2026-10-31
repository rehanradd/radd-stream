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
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.withContext
import java.io.File
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
 *
 * RETENTION: two classes, and this class is where they part. A rolling auto-preview copy keeps
 * its [CacheOrigin.AUTO_PREVIEW] origin and ages out on the window read through [KeepTtlHolder] —
 * read on every use rather than injected once as a frozen [TtlHours], because this class is a
 * `@Singleton` that outlives a settings change and would otherwise keep quoting the old window to
 * the player after the sweep had moved to the new one. A keep the viewer tapped in the player is
 * promoted by [CacheCoordinator.keepNow] to `USER_KEEP`, which [TtlPolicy] never auto-deletes, so
 * [adopt] reports no expiry for it (`ttlSeconds = null`, the same "null = permanent" convention
 * [com.raddstream.app.player.CacheSnapshot.previewExpiresAt] already carries).
 */
@Singleton
class OfflineCacheEngine @Inject constructor(
    private val coordinator: CacheCoordinator,
    private val repository: CacheRepository,
    private val taskDao: CacheTaskDao,
    private val fileDao: CacheFileDao,
    private val storage: StorageGate,
    private val keepTtl: KeepTtlHolder,
    @CacheScope private val scope: CoroutineScope,
) : ProgressiveCacheEngine {

    private val observed = ConcurrentHashMap<String, StateFlow<CacheSnapshot?>>()

    /** Live loopback servers, one per kept work being served; guarded by a lock on the map. */
    private val proxies = LinkedHashMap<String, LocalMediaProxy>()

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
                val sourceKey = KeepIdentity.sourceKeyFor(handle)
                // A tap in the player is an explicit keep, not a rolling preview: hand the task to
                // the coordinator's own handoff entry point, which adopts the bytes already on disk,
                // promotes the task so the sweeper stops aging it out, and returns the handle this
                // session plays from. It answers null only when there is no task to promote — and a
                // null there is a refusal, never a keep.
                val handoff = coordinator.keepNow(sourceKey)
                val task = taskDao.getBySourceKey(sourceKey)
                when {
                    handoff == null ->
                        KeepResult.Failed("This copy can't be kept on the connected server.")
                    task?.stateEnum == CacheTaskState.COMPLETED ->
                        KeepResult.Stored(
                            localHandle = sourceKey,
                            playableOffline = hasCommittedFile(sourceKey),
                        )
                    // Still driving to 100%. The copy is app-private either way — only this app can
                    // open it — and it now has no expiry, which is what a null window says.
                    else -> KeepResult.OnlyPlayableInApp(
                        reason = "Saved for offline playback in this app only",
                        ttlSeconds = null,
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
        val sourceKey = key.sourceKeyOrNull() ?: return
        observed.remove(sourceKey)
        closeProxy(sourceKey)
    }

    override fun storagePressure(): StoragePressure = when {
        lastFreeBytes <= 0L -> StoragePressure.FULL
        lastFreeBytes < PRESSURE_NEAR_FULL_BYTES -> StoragePressure.NEAR_FULL
        else -> StoragePressure.OK
    }

    /**
     * For an already-stored file, hand the player a loopback URL it can open; null = nothing
     * complete.
     *
     * A committed cache file lives in the app's PRIVATE directory, so a `file://` URI only works
     * while this process is the reader — and it gives Media3 no Range protocol of its own. Serving
     * it through [LocalMediaProxy] puts the bytes behind a loopback HTTP server that answers
     * `Range` requests exactly like a CDN would, which is what `DefaultHttpDataSource` already
     * knows how to consume (and what makes a kept file seekable without copying it anywhere).
     *
     * One proxy per work, reused across seeks and episode restarts: binding a fresh socket on
     * every open would leak file descriptors for as long as the player keeps re-opening its
     * source. The map is bounded, because a device that has played many kept files must not
     * accumulate one listening socket per title for the life of the process.
     */
    override suspend fun playableUri(key: CacheSessionKey): String? =
        key.sourceKeyOrNull()?.let { serveUri(it) }

    /**
     * The same answer for a keep whose task identity the caller already holds, so the Downloads
     * screen never has to reconstruct a redirector URL it never stored.
     */
    suspend fun playableUriForSourceKey(sourceKey: String): String? =
        sourceKey.takeIf { it.isNotBlank() }?.let { serveUri(it) }

    private suspend fun serveUri(sourceKey: String): String? {
        val committed = fileDao.getBySourceKey(sourceKey).firstOrNull { it.isComplete && !it.isTemporary }
            ?: return null
        val file = File(committed.path)
        if (!file.isFile || file.length() <= 0L) {
            closeProxy(sourceKey)
            return null
        }
        return withContext(Dispatchers.IO) { proxyFor(sourceKey, file).baseHttpUrl }
    }

    private fun proxyFor(sourceKey: String, file: File): LocalMediaProxy = synchronized(proxies) {
        proxies[sourceKey]?.let { return it }
        val fresh = LocalMediaProxy(
            file = file,
            // A committed file is complete, so the verified prefix is the whole file. The
            // provider is read per request, so a sweep that truncates the file is answered
            // honestly (416) instead of serving bytes that no longer exist.
            prefixProvider = { file.length() },
            contentType = contentTypeFor(file),
        )
        proxies[sourceKey] = fresh
        while (proxies.size > MAX_LIVE_PROXIES) {
            val eldest = proxies.keys.firstOrNull { it != sourceKey } ?: break
            proxies.remove(eldest)?.close()
        }
        fresh
    }

    private fun closeProxy(sourceKey: String) {
        synchronized(proxies) { proxies.remove(sourceKey) }?.close()
    }

    private fun contentTypeFor(file: File): String = when (file.extension.lowercase()) {
        "mp4", "m4v" -> "video/mp4"
        "mkv" -> "video/x-matroska"
        "webm" -> "video/webm"
        "ts" -> "video/mp2t"
        "m3u8" -> "application/vnd.apple.mpegurl"
        "mp3" -> "audio/mpeg"
        "m4a" -> "audio/mp4"
        else -> "application/octet-stream"
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
        // The projected expiry uses the window live *now*, which is exactly what [TtlPolicy] will
        // apply on the next sweep — the policy ages a file against the current setting, not against
        // the one in force when the bytes landed. Two different numbers in these two places would be
        // a row that promises a delete that never happens, or the reverse.
        val expires = if (originEnum == CacheOrigin.USER_KEEP) null else createdAtWallClock + keepTtl.ttlHours().millis
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

        /** Loopback servers kept alive at once; the player opens one work at a time. */
        private const val MAX_LIVE_PROXIES = 4
    }
}
