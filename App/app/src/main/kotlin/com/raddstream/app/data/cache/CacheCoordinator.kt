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

    /**
     * Pre-resolve better (2026-11-13) — source keys whose NEXT fill is a
     * detail-open first seed, capped at [AheadFetcher.FIRST_SEED_AHEAD_BYTES]
     * instead of the full ahead window. The set is the only place the small
     * window lives: the task row carries no window column (no Room schema
     * change), and the fetcher reads the mode, not this set. A key is
     * consumed once its first fill reaches the small window; a key left
     * behind by a refused or abandoned seed is harmless — it only ever
     * makes a later re-seed of the same source take the small window first,
     * which is what a first seed is.
     */
    private val firstSeedWindows = ConcurrentHashMap.newKeySet<String>()

    /**
     * Pre-resolve better (2026-11-13): mark [sourceKey]'s next fill as a
     * detail-open first seed. Called by the repository inside the enqueue,
     * before the drive the enqueue starts, so the first pass already sees it.
     */
    fun setFirstSeedWindow(sourceKey: String) {
        firstSeedWindows.add(sourceKey)
    }

    /** One scheduling tick: decide who runs given priorities, cap, network, and budget. */
    suspend fun tick() {
        val now = clock.nowElapsedRealtime()
        val schedulable = taskDao.listSchedulable(now)
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
        var mode = fetchModeFor(task)

        while (true) {
            if (!isActiveJob(taskId)) return
            // Re-read the row before every pass. A pass can move a hundred megabytes, and a Keep
            // tapped inside one changes both what this job is supposed to do (fill the window ahead
            // of the playhead versus fetch the whole file) and what retention origin the committed
            // file must carry. Neither may come from what was true when the job launched.
            task = taskDao.getById(taskId) ?: return
            mode = fetchModeFor(task)
            val outcome = if (task.linkKind == KIND_HLS) {
                runHlsPass(task, mode)
            } else {
                val headByte = playheadBytes[taskId] ?: task.verifiedPrefixBytes
                aheadFetcher.run(task, mode) { headByte }
            }
            when (outcome) {
                FetchOutcome.COMPLETED -> {
                    consumeFirstSeedWindow(task.sourceKey)
                    safeTransition(taskId, CacheTaskState.LOADING, CacheTaskState.COMPLETED)
                    return
                }
                FetchOutcome.ALREADY_COMPLETE -> {
                    consumeFirstSeedWindow(task.sourceKey)
                    safeTransition(taskId, CacheTaskState.LOADING, CacheTaskState.COMPLETED)
                    return
                }
                FetchOutcome.WINDOW_FILLED -> {
                    // Pre-resolve better (2026-11-13): a first-seed fill
                    // that reached its small window has spent its cap — the
                    // next drive (the playhead advancing on Play) takes the
                    // full ahead window. A normal preview pass has no cap
                    // to consume; the remove is a no-op for it.
                    consumeFirstSeedWindow(task.sourceKey)
                    if (mode == FetchMode.FULL_DOWNLOAD) {
                        // more gaps remain; keep looping but bound by cancellation checks
                        continue
                    }
                    // The same promotion the re-read above would pick up next turn, checked here so
                    // a just-kept title is not parked at the preview window until the next tick.
                    if (taskDao.getById(taskId)?.priorityEnum == CachePriority.USER_REQUESTED) continue
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
                FetchOutcome.GATED -> {
                    // Salaar (2026-11-12): our redirector refused this rung
                    // (the quality gate's 402). Not transient, not an engine
                    // failure — a preview of a rung that cannot play is
                    // dropped silently, a keep parks with the reason.
                    handleGated(task)
                    return
                }
            }
        }
    }

    /**
     * A task whose rung the server refused. An auto-preview is dropped outright
     * (row, manifest, bytes and file rows — the mirror of [cancelTask] without
     * the job cancel, since this runs inside the drive job itself), so no FAILED
     * chip ever names it; a user-requested keep parks with the reason instead,
     * so a VIP upgrade can resume it and the list can say why it waits.
     */
    private suspend fun handleGated(task: CacheTaskEntity) {
        playheadBytes.remove(task.id)
        if (task.priorityEnum == CachePriority.AUTO_PREVIEW) {
            consumeFirstSeedWindow(task.sourceKey)
            manifestDao.deleteForTask(task.id)
            runCatching { storage.deleteOnDisk(task.sourceKey) }
            fileDao.listByTask(task.id).forEach { fileDao.deleteById(it.fileId) }
            taskDao.deleteById(task.id)
        } else {
            safeTransition(task.id, task.stateEnum, CacheTaskState.PAUSED)
            taskDao.setParkReason(task.id, ERR_GATED)
        }
    }

    /**
     * What one pass is for. A user-requested row fetches the whole file; an opportunistic preview
     * fills only the window ahead of the playhead and then parks. The single owner of that choice
     * is the row's priority, read fresh — never remembered from the last read.
     *
     * Pre-resolve better (2026-11-13): a preview whose source is marked as a first seed fills
     * only the small first-seed window on its first pass; once that fill reaches the window the
     * mark is consumed and later passes take the full ahead window like any other preview.
     */
    private fun fetchModeFor(task: CacheTaskEntity): FetchMode =
        if (task.priorityEnum == CachePriority.USER_REQUESTED) FetchMode.FULL_DOWNLOAD
        else if (firstSeedWindows.contains(task.sourceKey)) FetchMode.AUTO_PREVIEW_FIRST_SEED
        else FetchMode.AUTO_PREVIEW_AHEAD

    /** Drop a first-seed mark once its window is filled, the file is done, or the seed is gone. */
    private fun consumeFirstSeedWindow(sourceKey: String) {
        firstSeedWindows.remove(sourceKey)
    }

    /**
     * One HLS pass. A preview fills the window ahead of the playhead and parks; a full
     * download fetches the whole playlist in one pass, from segment 0. The old code always
     * started at the playhead and always took 20 segments, so a keep that was never played
     * re-covered segments 0..20 forever and never reached segment 21.
     */
    private suspend fun runHlsPass(task: CacheTaskEntity, mode: FetchMode): FetchOutcome {
        val workDir = File(storage.openForWrite(task.sourceKey, task.totalSizeBytes.takeIf { it > 0 }).parentFile, task.sourceKey)
        val result = hlsBuffer.run(
            manifestUrl = task.currentUrl,
            workDir = workDir,
            startSegmentIndex = if (mode == FetchMode.FULL_DOWNLOAD) 0 else task.playOffsetSeconds.toInt(), // segment index tracked by player
            aheadSegments = if (mode == FetchMode.FULL_DOWNLOAD) Int.MAX_VALUE else AHEAD_SEGMENTS,
        )
        return when {
            result.gated -> FetchOutcome.GATED
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
                        path = file.absolutePath, sizeBytes = result.bytesWritten, origin = liveOrigin(task),
                        state = CacheTaskState.COMPLETED.name, isTemporary = false, isComplete = true,
                        createdElapsedRealtime = now, lastAccessElapsedRealtime = now,
                    )
                )
                safeTransition(task.id, CacheTaskState.LOADING, CacheTaskState.COMPLETED)
            }
            is RangeFetchResult.GateRefused -> handleGated(task)
            else -> recordRetry(task.id, task.attempt, "sequential_failed")
        }
    }

    /**
     * The retention origin a committed file is stamped with, read at the moment the file is
     * committed rather than from the [CacheTaskEntity] this pass was handed. A sequential fetch is
     * one open-ended request that can run for the whole file, and a Keep tapped partway through it
     * promotes the row; a commit that replays the stale origin would quietly un-pin the copy the
     * viewer just asked to keep, and [TtlPolicy] would age out bytes the list still calls kept.
     */
    private suspend fun liveOrigin(task: CacheTaskEntity): String =
        taskDao.getById(task.id)?.origin ?: task.origin

    // ── Player-facing boundary ─────────────────────────────────────────────────

    /**
     * Media3 progress callback. Stores the current absolute playhead byte and runs ONE bounded
     * auto-preview pass for this resource (no-op if a pass is already running or the file is
     * complete). [playheadByte] is the byte offset the player is at, derived by the wiring layer
     * from [CoverageMapping].
     *
     * The byte is recorded BEFORE the permission check: where the viewer has watched to is a fact
     * the next scheduler tick needs even when this tick may not move bytes. A roaming phone that
     * later joins Wi-Fi must resume from the playhead the viewer actually reached, not from the one
     * it last downloaded to.
     */
    suspend fun onPlayheadAdvanced(sourceKey: String, playheadByte: Long) {
        val task = taskDao.getBySourceKey(sourceKey) ?: return
        playheadBytes[task.id] = playheadByte
        if (task.stateEnum == CacheTaskState.COMPLETED) return
        if (task.stateEnum == CacheTaskState.LOADING) return // a pass is already running
        startIfAllowed(task)
    }

    /**
     * Whether the player may ask for opportunistic ahead-of-playback bytes at all right now.
     *
     * This is the seed-time question, and it is the same rule [onPlayheadAdvanced] applies at
     * start time rather than a paraphrase of it: [SchedulerPolicySelector] owns both halves. It is
     * exposed because the answer decides whether a task row is worth creating — a QUEUED preview
     * that the scheduler will never start is not an invisible no-op, it is a row the Downloads
     * screen would show for a file that was never going to move.
     */
    fun mayPreview(requestedBytes: Long): Boolean = SchedulerPolicySelector.mayStartAutoPreview(
        networkProvider(),
        policy,
        requestedBytes.coerceAtLeast(0L),
    )

    /**
     * The zero-waste handoff. Promotes the auto-preview task to user-requested so it continues
     * to 100% from its existing bytes, and returns a [LocalPlaybackHandle] the player can open
     * immediately (the file already on disk is playable up to its verified prefix).
     */
    suspend fun keepNow(sourceKey: String): LocalPlaybackHandle? {
        val task = taskDao.getBySourceKey(sourceKey) ?: return null
        taskDao.promoteToUserKeep(task.id)
        // Pre-resolve better (2026-11-13): a promoted row fetches the whole
        // file from here on, so a first-seed mark on it is meaningless —
        // drop it rather than letting a later re-read mistake it for a cap.
        consumeFirstSeedWindow(sourceKey)
        // Both rows, not just the task. TtlPolicy rule 1 and EvictionCandidate.isProtected read the
        // FILE's origin, so a promoted task whose file row still says AUTO_PREVIEW is a keep the
        // Downloads screen calls permanent while the sweeper is timing its delete and the low-storage
        // pass has it in the eviction list. The tap has to move the bytes' status too or it pins
        // nothing but a label.
        fileDao.promoteOriginForTask(task.id)
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
     * The Downloads-screen enqueue entry point: start (or resume) driving an EXISTING task without
     * changing its retention origin. A keep tapped from the detail screen is already enqueued by
     * [com.raddstream.app.repository.CacheRepository] with user priority and an auto-preview
     * origin, so it downloads eagerly yet still ages out through [TtlPolicy] — this method only
     * makes the engine move it. No-op when a pass is already running, and no-op for an
     * opportunistic preview the scheduler would not start on this network anyway.
     */
    suspend fun startTask(sourceKey: String) {
        val task = taskDao.getBySourceKey(sourceKey) ?: return
        if (task.stateEnum == CacheTaskState.COMPLETED) return
        startIfAllowed(task)
    }

    /**
     * Start one already-loaded row if the policy allows it, which is the whole reason this exists as
     * one function instead of two callers: [com.raddstream.app.repository.CacheRepository] starts a
     * row from BOTH the tap path and the watch path, and the tick starts rows by itself, so
     * opportunistic bytes would move on a mobile or roaming network through whichever entry point
     * forgot to ask. A user-requested row is never gated — the viewer asked for it, and [tick]
     * starts those on any network too.
     */
    private suspend fun startIfAllowed(task: CacheTaskEntity) {
        if (task.priorityEnum == CachePriority.AUTO_PREVIEW &&
            !SchedulerPolicySelector.mayStartAutoPreview(networkProvider(), policy, remainingBytes(task))
        ) {
            return
        }
        launchTask(task.id)
    }

    /**
     * Pre-resolve better (2026-11-13) — cancel a preview seed the viewer
     * abandoned: stop its job, drop its held bytes and ledger, and remove
     * the row, exactly like [cancelTask] — but ONLY when the row is still
     * an opportunistic auto-preview. The distinction is the row's priority,
     * read fresh: a row the viewer promoted to a keep
     * ([CachePriority.USER_REQUESTED], whether tapped on the detail screen
     * or in the player) is never touched, and neither is a row that is
     * already gone. A preview that never started downloading has no bytes
     * to drop; removing its row is still the right answer, so no QUEUED
     * seed lingers for a title the viewer left.
     */
    suspend fun cancelPreview(sourceKey: String) {
        val task = taskDao.getBySourceKey(sourceKey) ?: return
        if (task.priorityEnum != CachePriority.AUTO_PREVIEW) return
        consumeFirstSeedWindow(sourceKey)
        cancelTask(task.id)
    }

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
            taskDao.recordRetryState(id, CacheTaskState.FAILED.name, next, 0, reason)
        } else {
            val delay = RetryPolicy.nextRetryDelayMs(next, id)
            val cur = taskDao.getById(id)?.stateEnum ?: return
            val parked = CacheTaskStateMachine.canTransition(cur, CacheTaskState.PAUSED)
            val target = if (parked) CacheTaskState.PAUSED else CacheTaskState.FAILED
            taskDao.recordRetryState(id, target.name, next, clock.nowElapsedRealtime() + delay, reason)
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

        /** Stable park-reason token for a rung the server refused (quality gate 402). Never UI text. */
        const val ERR_GATED = "gated"
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
