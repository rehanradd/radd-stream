package com.raddstream.app.data.cache

import androidx.room.Entity
import androidx.room.Index

/**
 * The persisted byte-range manifest: one row per contiguous interval `[start, end)` of a task
 * that is verified on disk. Together the rows for a [taskId] reconstruct an [IntervalLedger].
 *
 * Storing intervals as rows (rather than one opaque blob) means:
 *  - a resume query can, in SQL, find the highest verified prefix and the first gap,
 *  - the manifest survives incremental writes (append a row per completed chunk),
 *  - an interrupted-then-resumed download never re-fetches a range that already has a row.
 *
 * Composite primary key `(taskId, start)` guarantees no duplicate/overlapping starts. Inert
 * until registered — see `docs/HANDOFF_appcache.md`.
 */
@Entity(
    tableName = ByteRangeManifestEntity.TABLE,
    primaryKeys = ["taskId", "start"],
    indices = [Index(value = ["taskId"])],
)
data class ByteRangeManifestEntity(
    val taskId: Long,
    val start: Long,
    val end: Long,
    /** Monotonic instant the interval was verified written (for audit / temp sweeps). */
    val committedElapsedRealtime: Long,
) {
    fun toInterval(): ByteInterval = ByteInterval(start, end)

    companion object {
        const val TABLE = "byte_range_manifests"

        /** Serialise a whole ledger into manifest rows for one task. */
        fun fromLedger(taskId: Long, ledger: IntervalLedger, nowElapsedRealtime: Long): List<ByteRangeManifestEntity> =
            ledger.intervals.map {
                ByteRangeManifestEntity(taskId, it.start, it.end, nowElapsedRealtime)
            }
    }
}
