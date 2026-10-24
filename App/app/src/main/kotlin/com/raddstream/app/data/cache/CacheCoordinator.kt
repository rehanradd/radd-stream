package com.raddstream.app.data.cache

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import java.io.File
import java.util.concurrent.ConcurrentHashMap

/** A freshly (re)resolved source for one resource, produced by the app's resolver layer. */
data class ResolvedSource(
    val releaseId: Long,
    val linkKind: String,
    val url: String,
    val resourceId: String?,
    val sizeBytes: Long?,
)

/** Injected by the wiring layer so the cache never depends on `CatalogRepository` directly. */
fun interface SourceResolver {
    suspend fun reResolve(sourceKey: String, releaseId: Long): ResolvedSource?
}

/**
 * Orchestrates cache tasks: it is the single owner of the scheduler tick, the running-job set,
 * the state transitions, and the player handoff. Everything policy-heavy (which ranges, whether
 * space is available, whether a file should die) already lives in the pure classes and is
 * unit-tested; this class only sequences them against Room, OkHttp and coroutines.
 *
 * The two player-facing entry points are the whole boundary contract:
 *  - [onPlayheadAdvanced] — Media3 reports progress; we run ONE bounded auto-preview pass.
 *  - [keepNow] — the user tapped "keep this"; we adopt existing bytes and drive a full download.
 */
class CacheCoordinator(
    private val scope: CoroutineScope,
    private val taskDao: CacheTaskDao,
    private val manifestDao: ByteRangeManifestDao,
    private val fileDao: CacheFileDao,
    private val aheadFetcher: AheadExecutor,
    private val rangeFetcher: RangeByteFetcher,
    private val hlsBuffer: HlsAheadBuffer,
    private val storage: StorageGate,
    private val resolver: SourceResolver,
    private val clock: UptimeClock,
    private val policy: SchedulerPolicy,
    private val networkProvider: @JvmSuppressWildcards () -> NetworkClass,
) {

    private val jobs = ConcurrentHashMap<Long, Job>()

    /** Latest absolute playhead byte per task, fed by Media3 progress callbacks. */
    private val playheadBytes = ConcurrentHashMap<Long, Long>()

    /** One scheduling tick: decide who runs given priorities, cap, network, and budget. */
    suspend fun tick() {
        val schedulable = taskDao.listSchedulable()
        val now = clock.nowElapsedRealtime()
        val tasks = schedulable.map {
            SchedulableTask(
                taskId = it.id,
                priority = it.priorityEnum,
                estimatedRemainingBytes = remainingBytes(it),
                enqueueElapsedRealtime = it.enqueueElapsedRealtime,
                isRunning = jobs[it.id]?.isActive == true && it.stateEnum == CacheTaskState.LOADING,
            )
        }
        val decision = SchedulerPolicySelector.select(tasks, networkProvider(), policy)

        // Pre-empt: cancel the running jobs the scheduler wants to pause (bytes stay on disk).
        decision.preemptTaskIds.forEach { id ->
            jobs[id]?.cancel()
            jobs.remove(id)
            safeTransition(id, CacheTaskState.LOADING, CacheTaskState.PAUSED)
        }
        // Start / resume the chosen tasks.
        decision.startTaskIds.forEach { id -> launchTask(id) }
    }

    private fun launchTask(taskId: Long) {
        if (jobs[taskId]?.isActive == true) return
        val job = scope.launch { driveToCompletionOrSuspend(taskId) }
        jobs[taskId] = job
        job.invokeOnCompletion { jobs.remove(taskId) }
    }

    /** Drive one task until it completes, suspends on storage, or is cancelled. */
    private suspend fun driveToCompletionOrSuspend(taskId: Long) {
        val entity = taskDao.getById(taskId) ?: return
        safeTransition(taskId, entity.stateEnum, CacheTaskState.LOADING)
        taskDao.setParkReason(taskId, null)
        var task = taskDao.getById(taskId) ?: return
        var reResolveBudget = MAX_RERESOLVES
        val mode = if (task.priorityEnum == CachePriority.USER_REQUESTED) FetchMode.FULL_DOWNLOAD
        else FetchMode.AUTO_PREVIEW_AHEAD

        while (true) {
            if (!isActiveJob(taskId)) return
            val outcome = if (task.linkKind == KIND_HLS) {
                runHlsPass(task)
            } else {
                val headByte = playheadBytes[taskId] ?: task.verifiedPrefixBytes
                aheadFetcher.run(task, mode) { headByte }
            }
            when (outcome) {
                FetchOutcome.COMPLETED -> {
                    safeTransition(taskId, CacheTaskState.LOADING, CacheTaskState.COMPLETED)
                    return
                }
                FetchOutcome.ALREADY_COMPLETE -> {
                    safeTransition(taskId, CacheTaskState.LOADING, CacheTaskState.COMPLETED)
                    return
                }
                FetchOutcome.WINDOW_FILLED -> {
                    if (mode == FetchMode.FULL_DOWNLOAD) {
                        // more gaps remain; keep looping but bound by cancellation checks
                        continue
                    }
                    // auto-preview caught up to the window; park until the playhead advances
                    safeTransition(taskId, CacheTaskState.LOADING, CacheTaskState.PAUSED)
                    return
                }
                FetchOutcome.STORAGE_SUSPENDED -> {
                    safeTransition(taskId, CacheTaskState.LOADING, CacheTaskState.PAUSED)
                    taskDao.setParkReason(taskId, ERR_NO_SPACE)
                    return
                }
                FetchOutcome.NO_RANGE_FALLBACK -> {
                    // server won't do ranges: do a single sequential full fetch from 0
                    sequentialFallback(task)
                    return
                }
                FetchOutcome.NEEDS_RERESOLVE -> {
                    if (reResolveBudget-- <= 0) {
                        recordRetry(taskId, task.attempt, "ephemeral_dead")
                        return
                    }
                    val re = resolver.reResolve(task.sourceKey, task.releaseId) ?: run {
                        recordRetry(taskId, task.attempt, "no_fresh_url")
                        return
                    }
                    taskDao.reResolveWithNewUrl(task.id, re.url)
                    task = taskDao.getById(taskId) ?: return
                    safeTransition(taskId, CacheTaskState.PAUSED, CacheTaskState.LOADING)
                    continue
                }
                FetchOutcome.RETRY_LATER -> {
                    recordRetry(taskId, task.attempt, "transient")
                    return
                }
            }
        }
    }

    private suspend fun runHlsPass(task: CacheTaskEntity): FetchOutcome {
        val workDir = File(storage.openForWrite(task.sourceKey, task.totalSizeBytes.takeIf { it > 0 }).parentFile, task.sourceKey)
        val result = hlsBuffer.run(
            manifestUrl = task.currentUrl,
            workDir = workDir,
            startSegmentIndex = task.playOffsetSeconds.toInt(), // segment index tracked by player
            aheadSegments = AHEAD_SEGMENTS,
        )
        return when {
            result.sourceDead -> FetchOutcome.NEEDS_RERESOLVE
            result.error != null -> FetchOutcome.RETRY_LATER
            result.isComplete -> FetchOutcome.COMPLETED
            else -> FetchOutcome.WINDOW_FILLED
        }
    }

    /** Progressive fallback when the host ignores Range: fetch the whole file sequentially. */
    private suspend fun sequentialFallback(task: CacheTaskEntity) {
        // Reuse the range fetcher with an open-ended, offset-0 request. The committed prefix is
        // then simply the file length; we adopt nothing already held mid-file (there is nothing,
        // since the server does not support ranges).
        val file = storage.openForWrite(task.sourceKey, task.totalSizeBytes.takeIf { it > 0 })
        val raf = java.io.RandomAccessFile(file, "rw")
        val result = try {
            rangeFetcher.fetch(task.currentUrl, raf, 0, null, task.totalSizeBytes.takeIf { it > 0 })
        } finally {
            runCatching { raf.close() }
        }
        when (result) {
            is RangeFetchResult.Success -> {
                val ledger = IntervalLedger().apply { add(0, result.bytesWritten) }
                val now = clock.nowElapsedRealtime()
                manifestDao.commit(ByteRangeManifestEntity.fromLedger(task.id, ledger, now))
                taskDao.recordProgress(task.id, result.bytesWritten, result.bytesWritten, result.totalSize ?: 0, "", task.currentUrl)
                fileDao.upsert(
                    CacheFileEntity(
                        fileId = task.sourceKey, sourceKey = task.sourceKey, taskId = task.id,
                        path = file.absolutePath, sizeBytes = result.bytesWritten, origin = task.origin,
                        state = CacheTaskState.COMPLETED.name, isTemporary = false, isComplete = true,
                        createdElapsedRealtime = now, lastAccessElapsedRealtime = now,
                    )
                )
                safeTransition(task.id, CacheTaskState.LOADING, CacheTaskState.COMPLETED)
            }
            else -> recordRetry(task.id, task.attempt, "sequential_failed")
        }
    }

    // ── Player-facing boundary ─────────────────────────────────────────────────

    /**
     * Media3 progress callback. Stores the current absolute playhead byte and runs ONE bounded
     * auto-preview pass for this resource (no-op if a pass is already running or the file is
     * complete). [playheadByte] is the byte offset the player is at, derived by the wiring layer
     * from [CoverageMapping].
     */
    suspend fun onPlayheadAdvanced(sourceKey: String, playheadByte: Long) {
        val task = taskDao.getBySourceKey(sourceKey) ?: return
        playheadBytes[task.id] = playheadByte
        if (task.stateEnum == CacheTaskState.COMPLETED) return
        if (task.stateEnum == CacheTaskState.LOADING) return // a pass is already running
        launchTask(task.id)
    }

    /**
     * The zero-waste handoff. Promotes the auto-preview task to user-requested so it continues
     * to 100% from its existing bytes, and returns a [LocalPlaybackHandle] the player can open
     * immediately (the file already on disk is playable up to its verified prefix).
     */
    suspend fun keepNow(sourceKey: String): LocalPlaybackHandle? {
        val task = taskDao.getBySourceKey(sourceKey) ?: return null
        taskDao.promoteToUserKeep(task.id)
        val prefix = manifestDao.contiguousPrefix(task.id)
        val handle = LocalPlaybackHandle(
            sourceKey = sourceKey,
            taskId = task.id,
            file = storage.openForWrite(sourceKey, task.totalSizeBytes.takeIf { it > 0 }),
            verifiedPrefixProvider = { manifestDao.contiguousPrefix(task.id) },
            initialVerifiedPrefixBytes = prefix,
        )
        // ensure it keeps driving to full now that the user committed to it
        launchTask(task.id)
        return handle
    }

    /**
     * The Downloads-screen enqueue entry point: start (or resume) driving an EXISTING task to its
     * full window without changing its retention origin. A keep tapped from the detail screen is
     * already enqueued by [com.raddstream.app.repository.CacheRepository] with user priority and
     * an auto-preview origin, so it downloads eagerly yet still ages out through [TtlPolicy] —
     * this method only makes the engine move it. No-op when a pass is already running.
     */
    suspend fun startTask(sourceKey: String) {
        val task = taskDao.getBySourceKey(sourceKey) ?: return
        if (task.stateEnum == CacheTaskState.COMPLETED) return
        launchTask(task.id)
    }

    /** True when this resource already has a live pass (used to keep the handoff idempotent). */
    fun isDriving(taskId: Long): Boolean = jobs[taskId]?.isActive == true

    /**
     * Cancel a keep the user aborted: stop its job, drop its held bytes and ledger, and remove the
     * row so it disappears from the list. Safe to call on a completed or already-gone task.
     */
    suspend fun cancelTask(taskId: Long) {
        jobs[taskId]?.cancel()
        jobs.remove(taskId)
        playheadBytes.remove(taskId)
        val task = taskDao.getById(taskId) ?: return
        manifestDao.deleteForTask(taskId)
        runCatching { storage.deleteOnDisk(task.sourceKey) }
        fileDao.listByTask(taskId).forEach { fileDao.deleteById(it.fileId) }
        taskDao.deleteById(taskId)
    }

    // ── internals ──────────────────────────────────────────────────────────────

    private suspend fun safeTransition(id: Long, from: CacheTaskState, to: CacheTaskState) {
        if (from == to) return
        val current = taskDao.getById(id)?.stateEnum ?: return
        if (!CacheTaskStateMachine.canTransition(current, to)) return
        taskDao.transition(id, current.name, to.name)
    }

    private suspend fun recordRetry(id: Long, attempt: Int, reason: String) {
        val next = attempt + 1
        if (RetryPolicy.isExhausted(next)) {
            val cur = taskDao.getById(id)?.stateEnum ?: return
            if (CacheTaskStateMachine.canTransition(cur, CacheTaskState.FAILED)) {
                taskDao.transition(id, cur.name, CacheTaskState.FAILED.name)
            }
            taskDao.markFailedWithRetry(id, next, 0, reason)
        } else {
            val delay = RetryPolicy.nextRetryDelayMs(next, id)
            val cur = taskDao.getById(id)?.stateEnum ?: return
            if (CacheTaskStateMachine.canTransition(cur, CacheTaskState.PAUSED)) {
                taskDao.transition(id, cur.name, CacheTaskState.PAUSED.name)
            }
            taskDao.markFailedWithRetry(id, next, clock.nowElapsedRealtime() + delay, reason)
        }
    }

    private fun isActiveJob(id: Long): Boolean = jobs[id]?.isActive == true

    private suspend fun remainingBytes(task: CacheTaskEntity): Long {
        val committed = manifestDao.committedBytes(task.id)
        return if (task.totalSizeBytes > 0) (task.totalSizeBytes - committed).coerceAtLeast(0)
        else DEFAULT_UNKNOWN_REMAINING
    }

    companion object {
        const val KIND_HLS = "hls_manifest"
        const val AHEAD_SEGMENTS = 20
        const val MAX_RERESOLVES = 2
        const val DEFAULT_UNKNOWN_REMAINING = 64L * 1024 * 1024

        /** Stable park-reason token for a keep the device had no room for. Never UI text. */
        const val ERR_NO_SPACE = "no_space"
    }
}

/** A resolved "bytes already owned" playback handoff for the player. */
data class LocalPlaybackHandle(
    val sourceKey: String,
    val taskId: Long,
    val file: File,
    val verifiedPrefixProvider: suspend () -> Long,
    val initialVerifiedPrefixBytes: Long,
)
