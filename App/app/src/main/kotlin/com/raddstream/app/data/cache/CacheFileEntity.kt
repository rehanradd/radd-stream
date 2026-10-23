package com.raddstream.app.data.cache

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * Inventory of physical cache files on disk (final files and temp/partial files). This is what
 * the TTL sweep and the eviction planner walk. The *bytes* live in [ByteRangeManifestEntity];
 * this row is about the file handle, its size, its lifecycle origin, and the access signals
 * eviction orders by.
 *
 * A file is either:
 *  - a temp/partial file (`isTemporary = true`) owned by a running task, or
 *  - a committed playable file (`isTemporary = false`).
 * A partial download that was interrupted keeps its temp file (never garbage — it is resumable)
 * with its owning [taskId]; if that task dies, the TTL sweep reclaims it as an orphaned temp leak.
 *
 * Inert until registered — see `docs/HANDOFF_appcache.md`.
 */
@Entity(
    tableName = CacheFileEntity.TABLE,
    indices = [
        Index(value = ["sourceKey"]),
        Index(value = ["state"]),
        Index(value = ["origin", "createdElapsedRealtime"]),
    ],
)
data class CacheFileEntity(
    /** [SourceIdentity.digestHex] plus a suffix for temp files. Doubles as the on-disk name. */
    @PrimaryKey val fileId: String,
    val sourceKey: String,
    val taskId: Long?,
    /** Absolute path inside the app's PRIVATE files dir (never external, never world-readable). */
    val path: String,
    val sizeBytes: Long,
    val origin: String = CacheOrigin.AUTO_PREVIEW.name,
    val state: String = CacheTaskState.QUEUED.name,
    val isTemporary: Boolean = true,
    val isComplete: Boolean = false,
    /** Monotonic creation stamp driving [TtlPolicy]. */
    val createdElapsedRealtime: Long,
    val lastAccessElapsedRealtime: Long,
    /** Number of times the player opened this file — an eviction usefulness signal. */
    val watchCount: Int = 0,
    val ttlHours: Int = TtlHours.THREE.hours,
) {
    val originEnum: CacheOrigin get() = CacheOrigin.valueOf(origin)
    val stateEnum: CacheTaskState get() = CacheTaskState.valueOf(state)

    fun toSnapshot(referencedByRunningTask: Boolean): FileSnapshot = FileSnapshot(
        fileId = fileId,
        origin = originEnum,
        createdElapsedRealtime = createdElapsedRealtime,
        lastAccessElapsedRealtime = lastAccessElapsedRealtime,
        sizeBytes = sizeBytes,
        isTemporary = isTemporary,
        referencedByRunningTask = referencedByRunningTask,
    )

    fun toEvictionCandidate(referencedByRunningTask: Boolean): EvictionCandidate = EvictionCandidate(
        fileId = fileId,
        sizeBytes = sizeBytes,
        origin = originEnum,
        lastAccessElapsedRealtime = lastAccessElapsedRealtime,
        watchCount = watchCount,
        referencedByRunningTask = referencedByRunningTask,
        isTemporary = isTemporary,
        isComplete = isComplete,
    )

    companion object {
        const val TABLE = "cache_files"
    }
}
