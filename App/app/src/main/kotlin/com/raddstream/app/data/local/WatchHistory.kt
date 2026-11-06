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

    /**
     * Every scope this device watched of one work, newest first. The detail
     * screen reads this once per title: the latest resumable row is the
     * Resume button, and the rest are the progress marks on episode rows.
     */
    @Query("SELECT * FROM watch_history WHERE workRef = :workRef ORDER BY updatedAt DESC")
    suspend fun findWork(workRef: String): List<WatchHistoryEntity>

    /**
     * Movie rows only — a series row is one episode, never the whole keep, so
     * it cannot say the keep is finished. The watched-ness itself is judged
     * in Kotlin against the same end-guard the rail uses.
     */
    @Query("SELECT * FROM watch_history WHERE seasonNumber = 0 AND episodeNumber = 0 AND durationMs > 0")
    suspend fun findMovieRows(): List<WatchHistoryEntity>

    /**
     * Every row with a known duration, as a flow: the My List sort re-reads
     * it, so a title finished on another screen moves down the list while
     * this screen is still open. The finished-ness itself is judged in
     * Kotlin ([watchedTitles]) against the rail's end-guard.
     */
    @Query("SELECT * FROM watch_history WHERE durationMs > 0")
    fun observeDurations(): Flow<List<WatchHistoryEntity>>

    @Query("DELETE FROM watch_history")
    suspend fun clear()

    /**
     * Phase 7 (D1): forget one scope — the local half of "Remove from Continue
     * Watching". The server half is `POST /api/v2/account/progress/remove`;
     * deleting here first would let the next sync pull the row straight back.
     */
    @Query("DELETE FROM watch_history WHERE workRef = :workRef AND seasonNumber = :season AND episodeNumber = :episode")
    suspend fun remove(workRef: String, season: Int, episode: Int)
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
    ): List<WatchHistoryEntity> =
        fold(local, synced).values
            .filter { it.resumable }
            .sortedByDescending { it.updatedAt }
            .take(limit)

    /**
     * The same newest-wins fold, without the resumable filter: the history screen lists
     * everything this device watched, newest first — including a title watched to the end,
     * which the rail correctly hides because there is nothing left to resume. Sharing the
     * fold means the two surfaces can never disagree about *where* a title stopped, only
     * about whether it is worth resuming.
     */
    fun mergeAll(
        local: List<WatchHistoryEntity>,
        synced: List<SyncedProgressEntity>,
        limit: Int = HISTORY_LIMIT,
    ): List<WatchHistoryEntity> =
        fold(local, synced).values
            .sortedByDescending { it.updatedAt }
            .take(limit)

    private fun fold(
        local: List<WatchHistoryEntity>,
        synced: List<SyncedProgressEntity>,
    ): Map<String, WatchHistoryEntity> {
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
        return byScope
    }

    private fun scopeOf(workRef: String, season: Int, episode: Int): String =
        "$workRef|$season|$episode"

    const val DEFAULT_LIMIT = 12
    const val HISTORY_LIMIT = 100
}
