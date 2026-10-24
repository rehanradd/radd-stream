package com.raddstream.app.data.cache

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Update
import kotlinx.coroutines.flow.Flow

/**
 * Data access for [CacheTaskEntity]. Mirrors the existing [com.raddstream.app.data.local.FavoriteDao]
 * style (Flow reads, suspend writes). Table names are hard-coded literals here (not interpolated
 * constants) because Room annotation arguments must be unambiguously compile-time constants.
 *
 * Not wired into a Room database by this task — the DB registration + migration are supplied
 * verbatim in `docs/HANDOFF_appcache.md`.
 */
@Dao
interface CacheTaskDao {

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertIfAbsent(task: CacheTaskEntity): Long

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(task: CacheTaskEntity): Long

    @Update
    suspend fun update(task: CacheTaskEntity)

    @Query("SELECT * FROM cache_tasks WHERE id = :id")
    suspend fun getById(id: Long): CacheTaskEntity?

    @Query("SELECT * FROM cache_tasks WHERE sourceKey = :sourceKey LIMIT 1")
    suspend fun getBySourceKey(sourceKey: String): CacheTaskEntity?

    @Query("SELECT * FROM cache_tasks WHERE sourceKey = :sourceKey LIMIT 1")
    fun observeBySourceKey(sourceKey: String): Flow<CacheTaskEntity?>

    @Query("SELECT * FROM cache_tasks WHERE state IN (:states) ORDER BY enqueueElapsedRealtime ASC")
    suspend fun listByStates(states: List<String>): List<CacheTaskEntity>

    /** Everything the scheduler needs for one tick: non-terminal tasks, best priority first. */
    @Query(
        """
        SELECT * FROM cache_tasks
        WHERE state IN ('QUEUED','LOADING','PAUSED','FAILED')
        ORDER BY
          CASE priority WHEN 'USER_REQUESTED' THEN 0 ELSE 1 END ASC,
          enqueueElapsedRealtime ASC
        """
    )
    suspend fun listSchedulable(): List<CacheTaskEntity>

    @Query("SELECT * FROM cache_tasks WHERE state = 'LOADING'")
    suspend fun listLoading(): List<CacheTaskEntity>

    /**
     * Everything the Downloads screen renders: every task that is not fully gone, newest keep
     * first. Terminal DELETED rows are excluded so a cancelled or auto-deleted keep disappears.
     */
    @Query(
        """
        SELECT * FROM cache_tasks
        WHERE state != 'DELETED'
        ORDER BY createdAtWallClock DESC
        """
    )
    fun observeAllActive(): Flow<List<CacheTaskEntity>>

    @Query(
        """
        SELECT * FROM cache_tasks
        WHERE state != 'DELETED'
        ORDER BY createdAtWallClock DESC
        """
    )
    suspend fun listAllActive(): List<CacheTaskEntity>

    /** The single-state write path, used only after [CacheTaskStateMachine] approved the move. */
    @Query("UPDATE cache_tasks SET state = :to WHERE id = :id AND state = :from")
    suspend fun transition(id: Long, from: String, to: String): Int

    @Query(
        """
        UPDATE cache_tasks
        SET downloadedBytes = :downloadedBytes,
            verifiedPrefixBytes = :verifiedPrefixBytes,
            totalSizeBytes = :totalSizeBytes,
            resumeToken = :resumeToken,
            currentUrl = :currentUrl
        WHERE id = :id
        """
    )
    suspend fun recordProgress(
        id: Long,
        downloadedBytes: Long,
        verifiedPrefixBytes: Long,
        totalSizeBytes: Long,
        resumeToken: String,
        currentUrl: String,
    )

    @Query(
        """
        UPDATE cache_tasks
        SET state = 'FAILED', attempt = :attempt, nextRetryAtElapsedRealtime = :nextRetryAt, lastError = :error
        WHERE id = :id
        """
    )
    suspend fun markFailedWithRetry(id: Long, attempt: Int, nextRetryAt: Long, error: String?)

    /**
     * Stamp WHY a task is parked WITHOUT moving it out of PAUSED. The Downloads list reads this to
     * tell a storage-suspension apart from a plain pause; the reason is a stable token, never UI
     * text, so nothing displayable (and nothing with provenance) lives in the row. Pass null to
     * clear the reason when a task resumes.
     */
    @Query("UPDATE cache_tasks SET lastError = :reason WHERE id = :id")
    suspend fun setParkReason(id: Long, reason: String?)

    /** Promote an auto-preview task to user-requested at handoff without losing its ledger. */
    @Query("UPDATE cache_tasks SET priority = 'USER_REQUESTED', origin = 'USER_KEEP' WHERE id = :id")
    suspend fun promoteToUserKeep(id: Long)

    @Query(
        """
        UPDATE cache_tasks
        SET currentUrl = :newUrl, state = 'QUEUED', nextRetryAtElapsedRealtime = 0, lastError = NULL
        WHERE id = :id
        """
    )
    suspend fun reResolveWithNewUrl(id: Long, newUrl: String)

    @Query("DELETE FROM cache_tasks WHERE id = :id")
    suspend fun deleteById(id: Long)

    @Query("SELECT COUNT(*) FROM cache_tasks WHERE state IN ('QUEUED','LOADING')")
    suspend fun countRunning(): Int
}
