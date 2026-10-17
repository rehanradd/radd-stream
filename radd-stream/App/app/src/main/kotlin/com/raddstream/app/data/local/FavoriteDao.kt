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
}
