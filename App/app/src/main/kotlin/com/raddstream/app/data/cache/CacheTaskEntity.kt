package com.raddstream.app.data.cache

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * Room row for one progressive-download / ahead-buffer task.
 *
 * Follows the existing `data/local/FavoritePost.kt` pattern (plain data class, [PrimaryKey],
 * `exportSchema = false`). Enums are stored as their [Enum.name] text so no [androidx.room.TypeConverter]
 * is required and a future enum value never crashes a read (tolerate unknowns, per `API_V2.md` §10.5).
 *
 * NOTE: this entity is inert until registered in [com.raddstream.app.data.local.AppDatabase] —
 * the exact registration/migration code lives in `docs/HANDOFF_appcache.md`. It is deliberately
 * NOT added to the DB here because this task may not edit existing files.
 *
 * Progress is tracked in BYTES ([downloadedBytes] / [verifiedPrefixBytes]) with percent derived
 * only for display, never used for resume math.
 */
@Entity(
    tableName = CacheTaskEntity.TABLE,
    indices = [
        Index(value = ["sourceKey"], unique = true),
        Index(value = ["state"]),
        Index(value = ["priority", "enqueueElapsedRealtime"]),
    ],
)
data class CacheTaskEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    /** [SourceIdentity.key] — stable across URL rotation; the join key to the file manifest. */
    val sourceKey: String,
    val releaseId: Long,
    val linkKind: String,
    /** Latest resolved URL; may be a rotating ephemeral one. Never used as an identity. */
    val currentUrl: String,
    val resourceId: String? = null,
    val origin: String = CacheOrigin.AUTO_PREVIEW.name,
    val priority: String = CachePriority.AUTO_PREVIEW.name,
    val state: String = CacheTaskState.QUEUED.name,
    /** 0 when the server gave no Content-Length (ephemeral / unknown size). */
    val totalSizeBytes: Long = 0,
    val downloadedBytes: Long = 0,
    val verifiedPrefixBytes: Long = 0,
    val resumeToken: String = "",
    val attempt: Int = 0,
    /** Monotonic (elapsedRealtime) instant after which a failed task may retry. */
    val nextRetryAtElapsedRealtime: Long = 0,
    val enqueueElapsedRealtime: Long = 0,
    /** Wall clock, only for user-facing "saved on" text; never used for TTL math. */
    val createdAtWallClock: Long = System.currentTimeMillis(),
    /** Packed-season playback mapping: seconds into the file where this episode starts. */
    val playOffsetSeconds: Double = 0.0,
    val packTotalDurationSeconds: Double = 0.0,
    val lastError: String? = null,
) {
    val priorityEnum: CachePriority get() = CachePriority.valueOf(priority)
    val originEnum: CacheOrigin get() = CacheOrigin.valueOf(origin)
    val stateEnum: CacheTaskState get() = CacheTaskState.valueOf(state)

    /** Percent, derived for the UI only. Returns null when size is unknown. */
    fun percent(): Int? = if (totalSizeBytes > 0)
        ((downloadedBytes * 100) / totalSizeBytes).toInt().coerceIn(0, 100) else null

    companion object {
        const val TABLE = "cache_tasks"
    }
}
