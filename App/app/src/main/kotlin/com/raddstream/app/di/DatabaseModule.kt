package com.raddstream.app.di

import android.content.Context
import androidx.room.Room
import com.raddstream.app.data.cache.ByteRangeManifestDao
import com.raddstream.app.data.cache.CacheFileDao
import com.raddstream.app.data.cache.CacheTaskDao
import com.raddstream.app.data.local.AppDatabase
import com.raddstream.app.data.local.FavoriteDao
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object DatabaseModule {

    @Provides
    @Singleton
    fun provideAppDatabase(@ApplicationContext context: Context): AppDatabase {
        return Room.databaseBuilder(
            context,
            AppDatabase::class.java,
            "radd_stream_local.db",
        )
            .addMigrations(AppDatabase.MIGRATION_1_2)
            // Version 3 adds the offline cache tables for the first time. They have never shipped
            // on any device, so a destructive fallback lets Room generate their schema verbatim
            // from the entities instead of hand-written DDL that could drift out of sync and
            // crash at open. Existing favorites are untouched on the 1 → 2 step above.
            .fallbackToDestructiveMigration()
            .build()
    }

    @Provides
    fun provideFavoriteDao(database: AppDatabase): FavoriteDao {
        return database.favoriteDao()
    }

    @Provides
    fun provideCacheTaskDao(database: AppDatabase): CacheTaskDao {
        return database.cacheTaskDao()
    }

    @Provides
    fun provideCacheFileDao(database: AppDatabase): CacheFileDao {
        return database.cacheFileDao()
    }

    @Provides
    fun provideByteRangeManifestDao(database: AppDatabase): ByteRangeManifestDao {
        return database.byteRangeManifestDao()
    }
}

