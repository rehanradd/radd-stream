package com.raddstream.app.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface FavoriteDao {

    @Query("SELECT * FROM favorite_posts ORDER BY addedAt DESC")
    fun getAllFavorites(): Flow<List<FavoritePost>>

    @Query("SELECT EXISTS(SELECT 1 FROM favorite_posts WHERE id = :id)")
    fun isFavorite(id: Int): Flow<Boolean>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(favorite: FavoritePost)

    @Query("DELETE FROM favorite_posts WHERE id = :id")
    suspend fun deleteById(id: Int)

    /**
     * One-off read for the sync pass, which must not observe its own writes: a flow that
     * re-emits mid-merge would run the merge against a list that already changed.
     */
    @Query("SELECT * FROM favorite_posts ORDER BY addedAt DESC")
    suspend fun favoritesOnce(): List<FavoritePost>

    @Query("SELECT * FROM favorite_posts WHERE id = :id LIMIT 1")
    suspend fun findById(id: Int): FavoritePost?

    /**
     * Record what the server said about this id. BOTH columns are written together, because an
     * answer is one event: stamping `checkedAt` while leaving a stale `is18Plus` behind would let
     * a row that came back clean keep hiding, and letting a `null` overwrite a stored `true` would
     * un-hide a flagged work on the strength of a payload that never mentioned the flag. So the
     * caller passes the flag it actually read, and a refusal that carried no body passes `null` —
     * which is why the UPDATE below coalesces instead of overwriting.
     */
    @Query(
        "UPDATE favorite_posts SET " +
            "is18Plus = COALESCE(:flag, is18Plus), checkedAt = :stamp WHERE id = :id",
    )
    suspend fun recordAnswer(id: Int, flag: Boolean?, stamp: Long)

    /** Ids only, for a caller that must not hold a copy of the viewer's whole library in memory. */
    @Query("SELECT id FROM favorite_posts ORDER BY addedAt DESC")
    suspend fun favoriteIds(): List<Int>

    /**
     * Stamp a row as confirmed on the library. Written only after the server accepted the
     * row, so a failed push leaves it eligible for the next sync instead of marking it done.
     */
    @Query("UPDATE favorite_posts SET syncedAt = :stamp WHERE id = :id")
    suspend fun markSynced(id: Int, stamp: Long)

    /**
     * Backfill the handle for a row saved before this app had one — the single case where
     * a favorite can become syncable without being re-added, because the catalog only
     * names a work in the payload that carries it.
     */
    @Query("UPDATE favorite_posts SET workRef = :workRef WHERE id = :id")
    suspend fun updateWorkRef(id: Int, workRef: String)
}
