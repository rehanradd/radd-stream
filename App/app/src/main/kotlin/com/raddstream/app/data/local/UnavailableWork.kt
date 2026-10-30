package com.raddstream.app.data.local

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

/**
 * A catalog id this device has been *refused* by name, and when.
 *
 * This is the mark that closes the app half of the adult invariant. The server answers 404 for an id
 * it has flagged (and for an id that never existed — deliberately indistinguishable, per
 * `Fast_Fetch/viewer.py:2677`'s "an adult title must not be distinguishable from an absent one"),
 * and for a stream handle it will no longer hand bytes for. Neither refusal removes anything from
 * this device's own tables, so without this ledger a favourite saved last month keeps rendering
 * forever after the row behind it is hidden.
 *
 * A row here is an ANSWER, never a guess: only a 404/410 or a body that says `success:false` is
 * recorded, and a later 200 for the same id clears it. That is what makes marking (rather than
 * deleting) safe — an outage writes nothing, and a reconciliation that flips a row back makes it
 * listable without the viewer re-saving anything.
 */
@Entity(tableName = "unavailable_works")
data class UnavailableWorkEntity(
    @PrimaryKey
    val postId: Int,
    /** Wall-clock millis of the refusal, so a reader can tell a stale answer from a fresh one. */
    val refusedAt: Long,
    /**
     * Which door refused, in the app's own vocabulary — [REASON_CATALOG] or [REASON_STREAM]. Not a
     * server message: the body of a 404 is never stored, because a refusal reason that quotes the
     * server is a string this app cannot render honestly and cannot compare against later.
     */
    val reason: String,
) {
    companion object {
        const val REASON_CATALOG = "catalog_refused"
        const val REASON_STREAM = "stream_refused"
    }
}

@Dao
interface UnavailableWorkDao {

    /** Every id currently under a refusal, for a cached surface to filter itself against. */
    @Query("SELECT postId FROM unavailable_works")
    fun observeRefusedIds(): Flow<List<Int>>

    @Query("SELECT EXISTS(SELECT 1 FROM unavailable_works WHERE postId = :postId)")
    suspend fun isRefused(postId: Int): Boolean

    /**
     * Record a refusal. REPLACE because a second 404 for the same id is the same fact with a newer
     * stamp, not a second row — and the stamp is what tells a reader how old the answer is.
     */
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun record(row: UnavailableWorkEntity)

    /** The server served this id after all, so nothing may keep hiding it. */
    @Query("DELETE FROM unavailable_works WHERE postId = :postId")
    suspend fun clear(postId: Int)

    @Query("SELECT COUNT(*) FROM unavailable_works")
    suspend fun count(): Int
}
