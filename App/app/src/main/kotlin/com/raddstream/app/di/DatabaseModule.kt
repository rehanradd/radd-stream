package com.raddstream.app.di

import android.content.Context
import androidx.room.Room
import com.raddstream.app.data.cache.ByteRangeManifestDao
import com.raddstream.app.data.cache.CacheFileDao
import com.raddstream.app.data.cache.CacheTaskDao
import com.raddstream.app.data.local.AdCadenceDao
import com.raddstream.app.data.local.AppDatabase
import com.raddstream.app.data.local.FavoriteDao
import com.raddstream.app.data.local.SyncedProgressDao
import com.raddstream.app.data.local.WatchHistoryDao
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
            .addMigrations(
                AppDatabase.MIGRATION_1_2,
                AppDatabase.MIGRATION_2_3,
                AppDatabase.MIGRATION_3_4,
                AppDatabase.MIGRATION_4_5,
                AppDatabase.MIGRATION_5_6,
                AppDatabase.MIGRATION_6_7,
            )
            // The ladder 1 → 7 is continuous, so this fallback never fires for a known schema;
            // it is a last resort against an unknown future version, and no step may ever be
            // planned into it — a destructive migration drops every table, `favorite_posts`
            // included. (Flow-audit #25: the 2 → 3 gap used to make that fallback the plan.)
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

    @Provides
    fun provideSyncedProgressDao(database: AppDatabase): SyncedProgressDao {
        return database.syncedProgressDao()
    }

    @Provides
    fun provideWatchHistoryDao(database: AppDatabase): WatchHistoryDao {
        return database.watchHistoryDao()
    }

    @Provides
    fun provideAdCadenceDao(database: AppDatabase): AdCadenceDao {
        return database.adCadenceDao()
    }
}

