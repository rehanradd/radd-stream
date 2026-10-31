package com.raddstream.app.data.local

import androidx.room.Database
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import com.raddstream.app.data.cache.ByteRangeManifestDao
import com.raddstream.app.data.cache.ByteRangeManifestEntity
import com.raddstream.app.data.cache.CacheFileDao
import com.raddstream.app.data.cache.CacheFileEntity
import com.raddstream.app.data.cache.CacheTaskDao
import com.raddstream.app.data.cache.CacheTaskEntity

/**
 * The app's single Room database: favorites plus the offline cache engine (tasks, byte ledgers
 * and the file inventory the TTL sweep and eviction planner walk).
 *
 * Version 2 held only favorites; version 3 adds the three cache tables. Because the cache tables
 * are brand new (they have never shipped on any device), the 2 → 3 step is handled by a
 * destructive fallback registered in the DI layer, which lets Room generate the cache schema
 * verbatim from these entities rather than hand-writing DDL that could drift from them. The
 * favorite migration from 1 is preserved for anyone already on that schema.
 *
 * Version 4 is the optional sync account. It adds two columns to `favorite_posts` (the
 * server-minted handle, and the stamp of the write that last succeeded) and the
 * `synced_progress` mirror, and it is written as real DDL rather than left to the destructive
 * fallback on purpose: a saved list is the one table in this app a viewer would notice losing,
 * and an app that wipes it because a feature was switched on has broken a promise the feature
 * never made.
 *
 * Version 5 adds `watch_history`, the local Continue watching rows. It is a new table with no
 * prior data, but it is still real DDL: the destructive fallback on this builder would take
 * `favorite_posts` with it.
 *
 * Version 6 adds the two per-work presentation facts to `favorite_posts` — `isAnimated` and
 * `subtitled`. Both are nullable with no default on purpose: an existing row was saved by a
 * build that never asked, and a saved list may not be made to claim the server told it something
 * it never sent. This is one more nullable ADD COLUMN on the table a viewer would notice losing,
 * so it is DDL like 4 and 5 rather than the destructive fallback.
 *
 * Version 7 is the app half of the adult invariant. `favorite_posts` gains the restricted flag
 * itself and the stamp of the last server answer, and the new `unavailable_works` table records
 * the ids the server has refused by name. All three are additive and every existing row survives
 * unchanged — which is the point of writing it as DDL: the row that must stop *showing* is still
 * a row the viewer chose to keep, and a compliance fix that empties a saved list is a second bug.
 */
@Database(
    entities = [
        FavoritePost::class,
        CacheTaskEntity::class,
        CacheFileEntity::class,
        ByteRangeManifestEntity::class,
        SyncedProgressEntity::class,
        WatchHistoryEntity::class,
        UnavailableWorkEntity::class,
    ],
    version = 7,
    exportSchema = false,
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun favoriteDao(): FavoriteDao
    abstract fun cacheTaskDao(): CacheTaskDao
    abstract fun cacheFileDao(): CacheFileDao
    abstract fun byteRangeManifestDao(): ByteRangeManifestDao
    abstract fun syncedProgressDao(): SyncedProgressDao
    abstract fun watchHistoryDao(): WatchHistoryDao
    abstract fun unavailableWorkDao(): UnavailableWorkDao

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

        /**
         * 3 → 4: the sync-account columns and the resume-point mirror. Both favorite columns
         * are nullable, so an existing row means "local only" the moment it lands and nothing
         * in this step can change what a signed-out viewer sees.
         *
         * The second statement is one ADD COLUMN per statement because SQLite has never
         * supported adding two columns at once; a reader that expects one line here throws
         * "near ,: SQL syntax error" at open instead of telling anybody what went wrong.
         */
        val MIGRATION_3_4: Migration = object : Migration(3, 4) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE favorite_posts ADD COLUMN workRef TEXT")
                db.execSQL("ALTER TABLE favorite_posts ADD COLUMN syncedAt INTEGER")
                db.execSQL(
                    "CREATE TABLE IF NOT EXISTS synced_progress (" +
                        "workRef TEXT NOT NULL, seasonNumber INTEGER NOT NULL, " +
                        "episodeNumber INTEGER NOT NULL, positionSeconds REAL NOT NULL, " +
                        "durationSeconds REAL NOT NULL, clientUpdatedAt REAL NOT NULL, " +
                        "pulledAt INTEGER NOT NULL, PRIMARY KEY(workRef, seasonNumber, episodeNumber))",
                )
            }
        }

        /** 4 → 5: the local Continue watching rows. One statement, no existing row touched. */
        val MIGRATION_4_5: Migration = object : Migration(4, 5) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL(
                    "CREATE TABLE IF NOT EXISTS watch_history (" +
                        "workRef TEXT NOT NULL, postId INTEGER NOT NULL, title TEXT NOT NULL, " +
                        "posterUrl TEXT, seasonNumber INTEGER NOT NULL, " +
                        "episodeNumber INTEGER NOT NULL, positionMs INTEGER NOT NULL, " +
                        "durationMs INTEGER NOT NULL, updatedAt INTEGER NOT NULL, " +
                        "PRIMARY KEY(workRef, seasonNumber, episodeNumber))",
                )
            }
        }

        /**
         * 5 → 6: the two facts a tile needs and this table did not keep. Two statements because
         * SQLite has never supported adding two columns at once, and no existing row is
         * touched: a favourite saved last month arrives as undetermined, which is what it was.
         */
        val MIGRATION_5_6: Migration = object : Migration(5, 6) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE favorite_posts ADD COLUMN isAnimated INTEGER")
                db.execSQL("ALTER TABLE favorite_posts ADD COLUMN subtitled INTEGER")
            }
        }

        /**
         * 6 → 7: the adult half. Two nullable columns on `favorite_posts` (the flag when a
         * payload ever carried it, and the stamp of the last server answer) plus the refusal
         * ledger, and exactly as in 5 → 6 no existing row is touched: a favourite saved by an
         * older build arrives undetermined and unanswered, which is what it is, and the first
         * revalidation pass is what turns that into an answer.
         *
         * `unavailable_works` is created rather than rebuilt, so the whole step is additive.
         * Three statements because SQLite has never supported more than one ADD COLUMN per
         * statement, and a table's DDL must match the entity Room generated from or open
         * throws a schema-mismatch the viewer sees as a crash on upgrade.
         */
        val MIGRATION_6_7: Migration = object : Migration(6, 7) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE favorite_posts ADD COLUMN is18Plus INTEGER")
                db.execSQL("ALTER TABLE favorite_posts ADD COLUMN checkedAt INTEGER")
                db.execSQL(
                    "CREATE TABLE IF NOT EXISTS unavailable_works (" +
                        "postId INTEGER NOT NULL, refusedAt INTEGER NOT NULL, " +
                        "reason TEXT NOT NULL, PRIMARY KEY(postId))",
                )
            }
        }
    }
}
