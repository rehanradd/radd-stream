package com.raddstream.app.data.local

import androidx.room.Database
import androidx.room.RoomDatabase

@Database(entities = [FavoritePost::class], version = 1, exportSchema = false)
abstract class AppDatabase : RoomDatabase() {
    abstract fun favoriteDao(): FavoriteDao
}
