package com.raddstream.app.data.local

import androidx.room.Database
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

@Database(entities = [FavoritePost::class], version = 2, exportSchema = false)
abstract class AppDatabase : RoomDatabase() {
    abstract fun favoriteDao(): FavoriteDao

    companion object {
        /**
         * Version 1 stored `sourceSite`. The public edge stopped serving it, so the local
         * store must not keep it either — a column nothing can display is a column somebody
         * will display by accident later. SQLite below 3.35 cannot DROP COLUMN, so the table
         * is rebuilt and every row, including its `addedAt`, survives.
         */
        val MIGRATION_1_2: Migration = object : Migration(1, 2) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL(
                    "CREATE TABLE IF NOT EXISTS favorite_posts_new (" +
                        "id INTEGER NOT NULL, title TEXT NOT NULL, cleanTitle TEXT, " +
                        "year TEXT, contentType TEXT, posterUrl TEXT, imdbRating TEXT, " +
                        "addedAt INTEGER NOT NULL, PRIMARY KEY(id))",
                )
                db.execSQL(
                    "INSERT INTO favorite_posts_new " +
                        "(id, title, cleanTitle, year, contentType, posterUrl, imdbRating, addedAt) " +
                        "SELECT id, title, cleanTitle, year, contentType, posterUrl, imdbRating, addedAt " +
                        "FROM favorite_posts",
                )
                db.execSQL("DROP TABLE favorite_posts")
                db.execSQL("ALTER TABLE favorite_posts_new RENAME TO favorite_posts")
            }
        }
    }
}
