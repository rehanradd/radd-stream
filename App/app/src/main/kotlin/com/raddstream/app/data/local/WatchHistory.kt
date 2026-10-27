package com.raddstream.app.data.local

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

/**
 * One locally watched scope, with everything the Continue watching rail needs to show a
 * real card: the catalog row it came from, its art, and where it stopped.
 *
 * The metadata lives here rather than being looked up on read because a row pulled from
 * the sync account names only a `work_ref`. Without a local title there is nothing honest
 * to put on a card, so a server row is only ever shown when this device already knows what
 * that handle is — the merge below never invents a label.
 */
@Entity(tableName = "watch_history", primaryKeys = ["workRef", "seasonNumber", "episodeNumber"])
data class WatchHistoryEntity(
    val workRef: String,
    val postId: Int,
    val title: String,
    val posterUrl: String?,
    val seasonNumber: Int,
    val episodeNumber: Int,
    val positionMs: Long,
    val durationMs: Long,
    /** This device's clock at the last position write, in epoch milliseconds. */
    val updatedAt: Long,
) {
    /** Worth offering as "continue": started, and not within the last few seconds of the end. */
    val resumable: Boolean
        get() = positionMs >= MIN_RESUME_MS &&
            (durationMs <= 0L || positionMs < durationMs - END_GUARD_MS)

    companion object {
        const val MIN_RESUME_MS = 1_000L
        const val END_GUARD_MS = 10_000L
    }
}

@Dao
interface WatchHistoryDao {

    /** Opening a scope for the first time. An existing row keeps its position. */
    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertIfAbsent(row: WatchHistoryEntity)

    /** Playback actually started here: refresh metadata and move the row to the top. */
    @Query(
        "UPDATE watch_history SET postId = :postId, title = :title, posterUrl = :posterUrl," +
            " updatedAt = :updatedAt" +
            " WHERE workRef = :workRef AND seasonNumber = :season AND episodeNumber = :episode",
    )
    suspend fun touch(
        workRef: String,
        season: Int,
        episode: Int,
        postId: Int,
        title: String,
        posterUrl: String?,
        updatedAt: Long,
    )

    /** Only an existing row moves: a position without a title could never be displayed. */
    @Query(
        "UPDATE watch_history SET positionMs = :positionMs, durationMs = :durationMs," +
            " updatedAt = :updatedAt" +
            " WHERE workRef = :workRef AND seasonNumber = :season AND episodeNumber = :episode",
    )
    suspend fun recordPosition(
        workRef: String,
        season: Int,
        episode: Int,
        positionMs: Long,
        durationMs: Long,
        updatedAt: Long,
    )

    @Query("SELECT * FROM watch_history ORDER BY updatedAt DESC LIMIT :limit")
    fun observeRecent(limit: Int): Flow<List<WatchHistoryEntity>>

    /**
     * Where this device last stopped in one exact scope. The rail reads [observeRecent] to
     * show a position; this is the same number read by the player, so a tile and the tape it
     * promises are the same row rather than two answers to one question.
     */
    @Query(
        "SELECT * FROM watch_history WHERE workRef = :workRef AND seasonNumber = :season " +
            "AND episodeNumber = :episode",
    )
    suspend fun findScope(workRef: String, season: Int, episode: Int): WatchHistoryEntity?

    @Query("DELETE FROM watch_history")
    suspend fun clear()
}

/**
 * The read-side rule for the Continue watching rail, kept pure so it is testable on a JVM.
 *
 * Local rows are the only rows that can be rendered (they carry a title and a poster). A
 * synced row is folded in only when it names a scope this device already knows, and only
 * when the saving device's clock says it is newer than the local write — the same
 * newest-wins comparison [com.raddstream.app.sync.SyncContract] applies to the mirror.
 * Everything else is dropped rather than given a guessed label.
 */
object WatchHistoryMerge {

    fun merge(
        local: List<WatchHistoryEntity>,
        synced: List<SyncedProgressEntity>,
        limit: Int = DEFAULT_LIMIT,
    ): List<WatchHistoryEntity> {
        val byScope = local.associateBy { scopeOf(it.workRef, it.seasonNumber, it.episodeNumber) }
            .toMutableMap()
        for (row in synced) {
            val key = scopeOf(row.workRef, row.seasonNumber, row.episodeNumber)
            val known = byScope[key] ?: continue
            val syncedUpdatedAt = (row.clientUpdatedAt * 1000.0).toLong()
            if (syncedUpdatedAt <= known.updatedAt) continue
            byScope[key] = known.copy(
                positionMs = (row.positionSeconds * 1000.0).toLong().coerceAtLeast(0L),
                durationMs = (row.durationSeconds * 1000.0).toLong().coerceAtLeast(0L),
                updatedAt = syncedUpdatedAt,
            )
        }
        return byScope.values
            .filter { it.resumable }
            .sortedByDescending { it.updatedAt }
            .take(limit)
    }

    private fun scopeOf(workRef: String, season: Int, episode: Int): String =
        "$workRef|$season|$episode"

    const val DEFAULT_LIMIT = 12
}
