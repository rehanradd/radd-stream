package com.raddstream.app.data.local

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query

/**
 * A resume point pulled from the sync account, kept exactly as the server answered it.
 *
 * WHY A SEPARATE TABLE INSTEAD OF A COLUMN ON THE FAVORITES ROW: a resume point is a
 * fact about a scope (work, season, episode), not about a title, and the device that
 * saved it may have a title this device has never opened. Keeping the server's rows
 * untouched means a sync can hand the player a position for something with no local row
 * at all, and means a pull can never overwrite a position this device is still holding
 * for a title that simply has no handle yet.
 *
 * Everything here is keyed by the server-minted `workRef`; a raw work key, a title or a
 * row id is never stored, because none of them could be sent back.
 */
@Entity(tableName = "synced_progress", primaryKeys = ["workRef", "seasonNumber", "episodeNumber"])
data class SyncedProgressEntity(
    val workRef: String,
    val seasonNumber: Int,
    val episodeNumber: Int,
    val positionSeconds: Double,
    val durationSeconds: Double,
    /** The saving device's own clock, and the only thing a merge may compare. */
    val clientUpdatedAt: Double,
    /** This device's wall clock at the moment the row was read in — bookkeeping only. */
    val pulledAt: Long = System.currentTimeMillis(),
)

@Dao
interface SyncedProgressDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun put(row: SyncedProgressEntity)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun putAll(rows: List<SyncedProgressEntity>)

    @Query(
        "SELECT * FROM synced_progress WHERE workRef = :workRef" +
            " AND seasonNumber = :season AND episodeNumber = :episode LIMIT 1",
    )
    suspend fun find(workRef: String, season: Int, episode: Int): SyncedProgressEntity?

    @Query("SELECT * FROM synced_progress ORDER BY clientUpdatedAt DESC LIMIT :limit")
    suspend fun recent(limit: Int): List<SyncedProgressEntity>

    @Query("SELECT COUNT(*) FROM synced_progress")
    suspend fun count(): Int

    @Query("DELETE FROM synced_progress WHERE workRef = :workRef AND seasonNumber = :season AND episodeNumber = :episode")
    suspend fun remove(workRef: String, season: Int, episode: Int)

    /** Sign-out drops the mirror: a signed-out app must look exactly like it did before. */
    @Query("DELETE FROM synced_progress")
    suspend fun clear()
}
