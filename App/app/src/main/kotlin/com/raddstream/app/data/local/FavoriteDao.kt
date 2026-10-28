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
