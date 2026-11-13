package com.raddstream.app.data.cache

import android.net.Uri
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import java.io.RandomAccessFile
import kotlin.coroutines.coroutineContext

/** Supplies the current playback position as an absolute byte offset. The player owns this. */
fun interface PlayheadProvider {
    fun currentByte(): Long
}

/**
 * The one seam [CacheCoordinator] uses to move bytes. [AheadFetcher] is the production
 * implementation; tests inject a fake that returns chosen [FetchOutcome]s so the coordinator's
 * state machine, ledger handoff and re-resolve path can be driven without OkHttp or a disk.
 */
fun interface AheadExecutor {
    suspend fun run(task: CacheTaskEntity, mode: FetchMode, playhead: PlayheadProvider): FetchOutcome
}

enum class FetchMode {
    AUTO_PREVIEW_AHEAD,
    FULL_DOWNLOAD,
    /**
     * Pre-resolve better (2026-11-13): a detail-open first seed. Same
     * shape as [AUTO_PREVIEW_AHEAD] — fill the window ahead of the playhead
     * and park — but the window is [AheadFetcher.FIRST_SEED_AHEAD_BYTES],
     * not the full ahead window. The player extends it to the full window
     * on Play by re-driving in [AUTO_PREVIEW_AHEAD] once the playhead moves.
     */
    AUTO_PREVIEW_FIRST_SEED,
}

/** Terminal-ish outcome of one [AheadFetcher.run] pass. The coordinator drives the next step. */
enum class FetchOutcome {
    WINDOW_FILLED,     // filled the requested ahead window (auto-preview) — caller may re-invoke
    COMPLETED,         // full file verified on disk
    STORAGE_SUSPENDED, // refused by [StorageGate]; task parked until space frees
    NEEDS_RERESOLVE,   // ephemeral source died — bytes are persisted, re-resolve then resume
    NO_RANGE_FALLBACK, // server ignored Range — caller should switch to sequential full download
    RETRY_LATER,       // transient IO/HTTP error — retry with backoff
    ALREADY_COMPLETE,  // nothing to do
    GATED,             // our redirector refused this rung (402) — not this copy, not retryable
}

/**
 * The ahead-of-playback progressive fetcher. While Media3 plays, this downloads forward from the
 * playhead into the private cache file, recording every completed range in the [IntervalLedger]
 * and persisting it. It is written as a *bounded single pass* so it cooperates with the
 * scheduler (concurrency cap, priority pre-emption, pausing) and never spins unattended.
 *
 * Guarantees encoded here:
 *  - fetch only the gaps the ledger reports → a resumed or handed-off download never re-fetches
 *    a byte it already holds (the zero-waste contract).
 *  - an ephemeral source dying (403/410/404) keeps every committed byte and asks to re-resolve.
 *  - no range support degrades to a distinct outcome rather than corrupting the file by seeking.
 *  - throughput is chunked so playback buffering is not starved; work is capped per pass.
 */
class AheadFetcher(
    private val fetcher: RangeByteFetcher,
    private val taskDao: CacheTaskDao,
    private val manifestDao: ByteRangeManifestDao,
    private val fileDao: CacheFileDao,
    private val storage: StorageGate,
    private val clock: UptimeClock,
    private val aheadBytes: Long = DEFAULT_AHEAD_BYTES,
    private val maxBytesPerPass: Long = DEFAULT_MAX_BYTES_PER_PASS,
    private val chunkBytes: Int = DEFAULT_CHUNK_BYTES,
) : AheadExecutor {

    override suspend fun run(
        task: CacheTaskEntity,
        mode: FetchMode,
        playhead: PlayheadProvider,
    ): FetchOutcome {
        val ledger = IntervalLedger(manifestDao.getForTask(task.id).map { it.toInterval() })
        var totalSize = task.totalSizeBytes
        var downloaded = ledger.coveredBytes()
        var currentUrl = task.currentUrl

        // Where do we stop this pass?
        //
        // Pre-resolve better (2026-11-13): the window is per mode, not per
        // fetcher. A detail-open first seed fills only the small window —
        // 8 MiB is the container header plus roughly the first half-minute
        // of a 480p–720p stream, far more than the first frame needs, and
        // 8 chunks instead of 40 is a fifth of the stream GETs that tripped
        // the server's 429 bucket — while a normal preview still takes the
        // full 40 MiB ahead window and a keep takes the whole file.
        val windowBytes: Long = when (mode) {
            FetchMode.FULL_DOWNLOAD -> aheadBytes
            FetchMode.AUTO_PREVIEW_AHEAD -> aheadBytes
            FetchMode.AUTO_PREVIEW_FIRST_SEED -> FIRST_SEED_AHEAD_BYTES
        }
        val windowEnd: Long = when (mode) {
            FetchMode.FULL_DOWNLOAD -> if (totalSize > 0) totalSize else Long.MAX_VALUE
            FetchMode.AUTO_PREVIEW_AHEAD, FetchMode.AUTO_PREVIEW_FIRST_SEED -> {
                val head = playhead.currentByte().coerceAtLeast(0L)
                val target = head + windowBytes
                if (totalSize > 0) minOf(target, totalSize) else target
            }
        }

        // Ranges to fetch = the gaps within [0, windowEnd), fetched low-to-high so the verified
        // prefix (what a sequential player can trust) grows first.
        val planRanges = if (windowEnd == Long.MAX_VALUE) {
            // unknown size: extend the contiguous prefix forward by this mode's window.
            val start = ledger.verifiedPrefix()
            listOf(ByteInterval(start, start + windowBytes))
        } else {
            ledger.missingWithin(0, windowEnd)
        }

        if (totalSize > 0 && ledger.isComplete(totalSize)) {
            finalize(task, ledger, downloaded, totalSize, currentUrl)
            return FetchOutcome.ALREADY_COMPLETE
        }
        if (planRanges.isEmpty()) {
            return FetchOutcome.WINDOW_FILLED
        }

        val tempFile = storage.openForWrite(task.sourceKey, totalSize.takeIf { it > 0 })
        val raf = RandomAccessFile(tempFile, "rw")
        var fetchedThisPass = 0L
        try {
            for (range in planRanges) {
                coroutineContext.ensureActive()
                var cursor = range.start
                while (cursor < range.end) {
                    coroutineContext.ensureActive()
                    val pieceEnd = minOf(cursor + chunkBytes, range.end)

                    // Gate every write: never be the reason the phone fills up.
                    if (!ensureSpace(cursor, pieceEnd, task, downloaded)) {
                        persist(task, ledger, downloaded, totalSize, currentUrl)
                        return FetchOutcome.STORAGE_SUSPENDED
                    }

                    val result = fetcher.fetch(currentUrl, raf, cursor, pieceEnd, totalSize.takeIf { it > 0 })
                    when (result) {
                        is RangeFetchResult.Success -> {
                            if (result.totalSize != null && result.totalSize > 0 && totalSize <= 0) {
                                totalSize = result.totalSize
                            }
                            val wrote = result.bytesWritten
                            if (wrote <= 0) {
                                // Empty read on a non-empty gap: persist what we have and retry.
                                persist(task, ledger, downloaded, totalSize, currentUrl)
                                return FetchOutcome.RETRY_LATER
                            }
                            ledger.add(cursor, cursor + wrote)
                            downloaded += wrote
                            fetchedThisPass += wrote
                            cursor += wrote
                            persistIncremental(task.id, ledger, downloaded, totalSize, currentUrl)
                            if (!result.rangeHonored && cursor < pieceEnd) {
                                // streamed-from-0 fallback signalled mid-write
                                persist(task, ledger, downloaded, totalSize, currentUrl)
                                return FetchOutcome.NO_RANGE_FALLBACK
                            }
                            if (fetchedThisPass >= maxBytesPerPass) {
                                // A pass that fills the LAST gap at its byte cap is done, and "done"
                                // means committed: reporting COMPLETED without finalize() left the
                                // bytes in the .part, no cache_files row, and a Keep the UI called
                                // "Saved" that could never play offline.
                                val completeNow =
                                    mode == FetchMode.FULL_DOWNLOAD && totalSize > 0 && ledger.isComplete(totalSize)
                                if (completeNow) {
                                    finalize(task, ledger, downloaded, totalSize, currentUrl)
                                    return FetchOutcome.COMPLETED
                                }
                                persist(task, ledger, downloaded, totalSize, currentUrl)
                                return FetchOutcome.WINDOW_FILLED
                            }
                        }
                        is RangeFetchResult.SourceDead -> {
                            persist(task, ledger, downloaded, totalSize, currentUrl)
                            return FetchOutcome.NEEDS_RERESOLVE
                        }
                        is RangeFetchResult.GateRefused -> {
                            persist(task, ledger, downloaded, totalSize, currentUrl)
                            return FetchOutcome.GATED
                        }
                        is RangeFetchResult.NoRangeSupport -> {
                            persist(task, ledger, downloaded, totalSize, currentUrl)
                            return FetchOutcome.NO_RANGE_FALLBACK
                        }
                        is RangeFetchResult.HttpError -> {
                            persist(task, ledger, downloaded, totalSize, currentUrl)
                            return FetchOutcome.RETRY_LATER
                        }
                        is RangeFetchResult.IoError -> {
                            persist(task, ledger, downloaded, totalSize, currentUrl)
                            return FetchOutcome.RETRY_LATER
                        }
                        RangeFetchResult.Cancelled -> {
                            persist(task, ledger, downloaded, totalSize, currentUrl)
                            return FetchOutcome.RETRY_LATER
                        }
                    }
                }
            }
        } finally {
            try {
                raf.close()
            } catch (_: Throwable) {
                /* best-effort close */
            }
        }

        // The loop ran out of planned ranges. If that completed the file, this is the common
        // finish: any keep smaller than the per-pass cap lands here, and it must commit through
        // finalize() like every other COMPLETED answer.
        if (totalSize > 0 && ledger.isComplete(totalSize)) {
            finalize(task, ledger, downloaded, totalSize, currentUrl)
            return FetchOutcome.COMPLETED
        }
        persist(task, ledger, downloaded, totalSize, currentUrl)
        return FetchOutcome.WINDOW_FILLED
    }

    /** Ask the pure planner whether we may add [newBytes]; returns true to proceed. */
    private suspend fun ensureSpace(start: Long, end: Long, task: CacheTaskEntity, alreadyDownloaded: Long): Boolean {
        val need = (end - start)
        val decision = EvictionPlanner.admit(
            requestedBytes = need,
            currentUsedBytes = storage.workspaceUsedBytes(),
            osFreeBytes = storage.osFreeBytes(),
            limits = storage.limits(),
            candidates = storage.currentCandidates(clock.nowElapsedRealtime()),
            nowElapsedRealtime = clock.nowElapsedRealtime(),
        )
        return when (decision) {
            is AdmitDecision.Admit -> true
            is AdmitDecision.EvictThenAdmit -> {
                // Run the (already-pure, already-safe) eviction plan inline. The planner never
                // lists protected files (user-kept / running-task), and we re-filter defensively.
                decision.plan.deletions.filterNot { it.isProtected }.forEach { del ->
                    storage.deleteOnDisk(del.fileId)
                    fileDao.deleteById(del.fileId)
                }
                val recheck = EvictionPlanner.admit(
                    requestedBytes = need,
                    currentUsedBytes = storage.workspaceUsedBytes(),
                    osFreeBytes = storage.osFreeBytes(),
                    limits = storage.limits(),
                    candidates = storage.currentCandidates(clock.nowElapsedRealtime()),
                    nowElapsedRealtime = clock.nowElapsedRealtime(),
                )
                recheck is AdmitDecision.Admit || recheck is AdmitDecision.EvictThenAdmit
            }
            else -> false
        }
    }

    private suspend fun persistIncremental(
        taskId: Long,
        ledger: IntervalLedger,
        downloaded: Long,
        total: Long,
        url: String,
    ) {
        val now = clock.nowElapsedRealtime()
        manifestDao.commit(ByteRangeManifestEntity.fromLedger(taskId, ledger, now))
        val token = ResumeToken(
            identityDigest = urlDigest(url),
            totalSizeBytes = total,
            revision = now,
            ledger = ledger,
        ).encode()
        taskDao.recordProgress(
            id = taskId,
            downloadedBytes = downloaded,
            verifiedPrefixBytes = ledger.verifiedPrefix(),
            totalSizeBytes = total,
            resumeToken = token,
            currentUrl = url,
        )
    }

    private suspend fun persist(task: CacheTaskEntity, ledger: IntervalLedger, downloaded: Long, total: Long, url: String) {
        persistIncremental(task.id, ledger, downloaded, total, url)
    }

    /**
     * Rename the `.part` to its committed name and register it in `cache_files`. The ONE seam
     * that makes a keep playable offline: every path that returns COMPLETED must come through
     * here first, or the Downloads list advertises bytes the player cannot open.
     */
    private suspend fun finalize(task: CacheTaskEntity, ledger: IntervalLedger, downloaded: Long, total: Long, url: String) {
        persist(task, ledger, downloaded, total, url)
        val temp = (storage as? AndroidStorageGate)?.tempFile(task.sourceKey)
        val committed = (storage as? AndroidStorageGate)?.committedFile(task.sourceKey)
        if (temp != null && committed != null && temp.exists() && !committed.exists()) {
            withContext(Dispatchers.IO) { temp.renameTo(committed) }
            fileDao.upsert(
                CacheFileEntity(
                    fileId = task.sourceKey,
                    sourceKey = task.sourceKey,
                    taskId = task.id,
                    path = committed.absolutePath,
                    sizeBytes = total.coerceAtLeast(committed.length()),
                    // The live row, not the one this pass was handed: a pass can run for the whole
                    // file, and a Keep tapped inside it promotes the task. Committing the stale
                    // origin would re-stamp a pinned keep as an aging preview the moment its bytes
                    // land — the exact un-pin CacheCoordinator.keepNow exists to prevent.
                    origin = taskDao.getById(task.id)?.origin ?: task.origin,
                    state = CacheTaskState.COMPLETED.name,
                    isTemporary = false,
                    isComplete = true,
                    createdElapsedRealtime = clock.nowElapsedRealtime(),
                    lastAccessElapsedRealtime = clock.nowElapsedRealtime(),
                )
            )
        }
    }

    /** A lightweight digest of a transient URL — never an identity, only a token freshness tag. */
    private fun urlDigest(url: String): String = url.hashCode().toString(16)

    companion object {
        const val DEFAULT_AHEAD_BYTES = 40L * 1024 * 1024       // ~40 MiB ahead of the playhead
        /**
         * Pre-resolve better (2026-11-13): a detail-open first seed's window.
         * 8 MiB — the container header plus roughly the first half-minute of
         * a 480p–720p stream, far more than the first frame needs, and 8
         * stream GETs instead of 40. The player's own ahead window stays
         * [DEFAULT_AHEAD_BYTES]: this constant is honoured only for
         * [FetchMode.AUTO_PREVIEW_FIRST_SEED], never for a normal preview.
         */
        const val FIRST_SEED_AHEAD_BYTES = 8L * 1024 * 1024    // ~8 MiB first fill for a detail-open seed
        const val DEFAULT_MAX_BYTES_PER_PASS = 256L * 1024 * 1024
        const val DEFAULT_CHUNK_BYTES = 1024 * 1024              // 1 MiB pieces bound per-chunk stall
    }
}

/** Convenience for callers that just want a local Media3-openable URI of a committed file. */
fun CacheFileEntity.toLocalUri(): Uri = Uri.fromFile(java.io.File(path))
