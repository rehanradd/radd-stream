package com.raddstream.app.data.cache

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Update

/**
 * Data access for the file inventory ([CacheFileEntity]) — what the TTL sweeper and the
 * eviction planner operate on. Table names are literal strings for Room-annotation safety.
 * DB registration + migration live in `docs/HANDOFF_appcache.md`.
 */
@Dao
interface CacheFileDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(file: CacheFileEntity)

    @Update
    suspend fun update(file: CacheFileEntity)

    @Query("SELECT * FROM cache_files WHERE fileId = :fileId")
    suspend fun getById(fileId: String): CacheFileEntity?

    @Query("SELECT * FROM cache_files WHERE sourceKey = :sourceKey ORDER BY createdElapsedRealtime DESC")
    suspend fun getBySourceKey(sourceKey: String): List<CacheFileEntity>

    @Query("SELECT * FROM cache_files WHERE taskId = :taskId")
    suspend fun listByTask(taskId: Long): List<CacheFileEntity>

    /** Every file the sweeper must consider (non-deleted rows). */
    @Query("SELECT * FROM cache_files WHERE state != 'DELETED'")
    suspend fun listLive(): List<CacheFileEntity>

    @Query("SELECT COALESCE(SUM(sizeBytes), 0) FROM cache_files WHERE state != 'DELETED'")
    suspend fun totalBytesUsed(): Long

    /**
     * File ids owned by tasks that are currently QUEUED or LOADING. The sweeper marks these
     * `referencedByRunningTask` so a live writer's temp file is never deleted.
     */
    @Query(
        """
        SELECT f.fileId FROM cache_files f
        INNER JOIN cache_tasks t ON f.taskId = t.id
        WHERE t.state IN ('QUEUED','LOADING')
        """
    )
    suspend fun runningTaskFileIds(): List<String>

    @Query("UPDATE cache_files SET lastAccessElapsedRealtime = :now, watchCount = watchCount + 1 WHERE fileId = :fileId")
    suspend fun touchOnPlay(fileId: String, now: Long)

    @Query("UPDATE cache_files SET isTemporary = 0, isComplete = 1, origin = 'USER_KEEP', state = 'COMPLETED' WHERE fileId = :fileId")
    suspend fun commitAsUserKeep(fileId: String)

    @Query("UPDATE cache_files SET state = :state WHERE fileId = :fileId")
    suspend fun setState(fileId: String, state: String)

    @Query("DELETE FROM cache_files WHERE fileId = :fileId")
    suspend fun deleteById(fileId: String)
}
