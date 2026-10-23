package com.raddstream.app.data.cache

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction

/**
 * Data access for the persisted byte ledger ([ByteRangeManifestEntity]). The pure
 * [IntervalLedger] is the in-memory view; these calls are the durable view that lets a resume
 * after process death rebuild exactly what is already on disk, so no byte is ever re-fetched.
 *
 * Table names are literal strings (compile-time-constant safe for Room annotations). DB
 * registration + migration live in `docs/HANDOFF_appcache.md`.
 */
@Dao
interface ByteRangeManifestDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(rows: List<ByteRangeManifestEntity>)

    @Query("DELETE FROM byte_range_manifests WHERE taskId = :taskId")
    suspend fun deleteForTask(taskId: Long)

    @Query("SELECT * FROM byte_range_manifests WHERE taskId = :taskId ORDER BY start ASC")
    suspend fun getForTask(taskId: Long): List<ByteRangeManifestEntity>

    /** Highest `end` among intervals that begin at 0 — a cheap SQL proxy for the verified prefix. */
    @Query("SELECT COALESCE(MAX(end), 0) FROM byte_range_manifests WHERE taskId = :taskId AND start = 0")
    suspend fun contiguousPrefix(taskId: Long): Long

    /** Total committed bytes for a task (progress in BYTES, not percent). */
    @Query("SELECT COALESCE(SUM(end - start), 0) FROM byte_range_manifests WHERE taskId = :taskId")
    suspend fun committedBytes(taskId: Long): Long

    /**
     * Atomically replace a task's manifest with the current in-memory ledger. The ledger already
     * guarantees a disjoint, sorted canonical list, so we delete then re-insert inside one
     * transaction.
     */
    @Transaction
    @Query("DELETE FROM byte_range_manifests WHERE taskId = :taskId")
    suspend fun clear(taskId: Long)

    @Transaction
    suspend fun commit(rows: List<ByteRangeManifestEntity>) {
        if (rows.isEmpty()) return
        val taskId = rows.first().taskId
        clear(taskId)
        insertAll(rows)
    }
}
