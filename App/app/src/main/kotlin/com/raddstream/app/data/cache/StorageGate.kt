package com.raddstream.app.data.cache

import android.content.Context
import android.os.StatFs
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

/**
 * Decides, before any byte is written, whether the device can safely absorb them. Abstracted so
 * the engine depends on a small interface (and so the *decision math* in [EvictionPlanner] stays
 * pure and unit-tested while only this thin wrapper touches the Android storage APIs.
 */
interface StorageGate {
    /** Bytes free on the cache volume right now. */
    suspend fun osFreeBytes(): Long

    /** Bytes the cache workspace currently occupies (tracked via [CacheFileDao]). */
    suspend fun workspaceUsedBytes(): Long

    /** The limits (hard ceiling, low-storage floor, per-file cap) currently in force. */
    fun limits(): StorageLimits

    /** Live files the planner may consider evicting (ids a running task holds are protected). */
    suspend fun currentCandidates(nowElapsedRealtime: Long): List<EvictionCandidate>

    /** Create/return the destination file handle for [fileId], pre-allocated to [size] if known. */
    suspend fun openForWrite(fileId: String, size: Long?): File

    /** Remove a file's bytes on disk (both the temp and committed names). Best-effort. */
    fun deleteOnDisk(fileId: String)
}

/** [UptimeClock] backed by the real `SystemClock.elapsedRealtime()`. */
class AndroidUptimeClock : UptimeClock {
    override fun nowElapsedRealtime(): Long = android.os.SystemClock.elapsedRealtime()
}

/**
 * Production [StorageGate]. Uses the app's private files directory for cache files (never the
 * external/shared store), [StatFs] for genuine free-space checks, and the file DAO for the
 * workspace accounting the eviction planner needs.
 *
 * @param ceilingBytes user-configured hard ceiling on total cache size — the "we must never be
 *        the reason the phone fills up" cap. Defaults conservatively to 2 GiB.
 */
class AndroidStorageGate(
    private val context: Context,
    private val fileDao: CacheFileDao,
    private val clock: UptimeClock = AndroidUptimeClock(),
    private val ceilingBytes: Long = DEFAULT_CEILING_BYTES,
    private val lowStorageFloorBytes: Long = DEFAULT_LOW_STORAGE_FLOOR_BYTES,
    private val perFileMaxBytes: Long = DEFAULT_PER_FILE_MAX_BYTES,
) : StorageGate {

    private val cacheRoot: File by lazy {
        File(context.filesDir, "media_cache").apply { if (!exists()) mkdirs() }
    }

    override suspend fun osFreeBytes(): Long = withContext(Dispatchers.IO) {
        val stat = StatFs(cacheRoot.absolutePath)
        stat.availableBytes
    }

    override suspend fun workspaceUsedBytes(): Long = fileDao.totalBytesUsed()

    override fun limits(): StorageLimits = StorageLimits(
        hardCeilingBytes = ceilingBytes,
        lowStorageFloorBytes = lowStorageFloorBytes,
        perFileMaxBytes = perFileMaxBytes,
    )

    override suspend fun currentCandidates(nowElapsedRealtime: Long): List<EvictionCandidate> {
        val running = fileDao.runningTaskFileIds().toSet()
        return fileDao.listLive().map { it.toEvictionCandidate(referencedByRunningTask = it.fileId in running) }
    }

    override suspend fun openForWrite(fileId: String, size: Long?): File = withContext(Dispatchers.IO) {
        val f = File(cacheRoot, "$fileId.part")
        if (!f.exists()) {
            f.parentFile?.mkdirs()
            f.createNewFile()
        }
        if (size != null && size > 0 && f.length() < size) {
            RandomAccessFileCompat.setLength(f, size)
        }
        f
    }

    override fun deleteOnDisk(fileId: String) {
        runCatching { File(cacheRoot, "$fileId.part").delete() }
        runCatching { File(cacheRoot, fileId).delete() }
    }

    /** Resolve the final (non-temp) path for a committed file. */
    fun committedFile(fileId: String): File = File(cacheRoot, fileId)
    fun tempFile(fileId: String): File = File(cacheRoot, "$fileId.part")

    companion object {
        const val DEFAULT_CEILING_BYTES = 2L * 1024 * 1024 * 1024 // 2 GiB hard app ceiling
        const val DEFAULT_LOW_STORAGE_FLOOR_BYTES = 500L * 1024 * 1024 // keep >= 500 MiB free
        const val DEFAULT_PER_FILE_MAX_BYTES = 10L * 1024 * 1024 * 1024 // 10 GiB single-file cap
    }
}

/** Small indirection so the storage gate can pre-allocate without importing RandomAccessFile twice. */
private object RandomAccessFileCompat {
    fun setLength(file: File, length: Long) {
        val raf = java.io.RandomAccessFile(file, "rw")
        try {
            raf.setLength(length)
        } finally {
            raf.close()
        }
    }
}
