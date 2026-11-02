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
 * Version 2 held only favorites; version 3 adds the three cache tables. The 2 → 3 step is real
 * DDL like every step after it: leaving it to the destructive fallback in the DI layer would
 * drop `favorite_posts` too, so an upgrade may never depend on that fallback — it is a last
 * resort for an unknown future version only. The favorite migration from 1 is preserved for
 * anyone already on that schema.
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
 * Version 7 adds `ad_cadence`, the three rows that make an ad cap survive a process death. It is
 * a new table with no prior data and no nullable column: every field is written by this build the
 * moment it is meaningful, and an absent stamp is expressed as zero rather than as NULL so
 * [com.raddstream.app.data.local.AdCadenceRows] has one shape to read. Real DDL again, because the
 * destructive fallback on this builder would still take `favorite_posts` with it.
 *
 * Version 8 is the two answers a saved row never kept: `checkedAt`, the stamp of the last time the
 * server said anything about this id, and `is18Plus`, the adult flag if a payload ever carried it.
 * Both are nullable because every row on every device was saved by a build that asked neither —
 * a stamp invented at migration time would make a never-checked row look checked, and that is
 * precisely the row the revalidation pass is supposed to find first. The same step adds
 * `unavailable_works`, the ledger of ids this device has been *refused* by name. It is real DDL
 * for the same reason 4 through 7 are: the destructive fallback on this builder would take the
 * viewer's saved list with it, and a rule about hidden rows that costs a library to install is
 * not a rule the app should ship.
 */
@Database(
    entities = [
        FavoritePost::class,
        CacheTaskEntity::class,
        CacheFileEntity::class,
        ByteRangeManifestEntity::class,
        SyncedProgressEntity::class,
        WatchHistoryEntity::class,
        AdCadenceEntity::class,
        UnavailableWorkEntity::class,
    ],
    version = 8,
    exportSchema = false,
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun favoriteDao(): FavoriteDao
    abstract fun cacheTaskDao(): CacheTaskDao
    abstract fun cacheFileDao(): CacheFileDao
    abstract fun byteRangeManifestDao(): ByteRangeManifestDao
    abstract fun syncedProgressDao(): SyncedProgressDao
    abstract fun watchHistoryDao(): WatchHistoryDao
    abstract fun adCadenceDao(): AdCadenceDao
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
         * 2 → 3: the three offline-cache tables, created from nothing. This is hand-written DDL
         * that must equal Room's own output for the cache entities — column types and nullability
         * implied by the Kotlin types, AUTOINCREMENT for the generated key, and the index names
         * Room derives from table plus columns. A drift is caught the first time a device opens
         * the migrated database (Room validates the result against the entities and throws), and
         * [com.raddstream.app.data.local.AppDatabaseMigrationTest] plus the schema-guard tests
         * hold that contract on CI.
         */
        val MIGRATION_2_3: Migration = object : Migration(2, 3) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL(
                    "CREATE TABLE IF NOT EXISTS cache_tasks (" +
                        "id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, sourceKey TEXT NOT NULL, " +
                        "releaseId INTEGER NOT NULL, linkKind TEXT NOT NULL, currentUrl TEXT NOT NULL, " +
                        "resourceId TEXT, title TEXT NOT NULL, printLabel TEXT NOT NULL, " +
                        "origin TEXT NOT NULL, priority TEXT NOT NULL, state TEXT NOT NULL, " +
                        "totalSizeBytes INTEGER NOT NULL, downloadedBytes INTEGER NOT NULL, " +
                        "verifiedPrefixBytes INTEGER NOT NULL, resumeToken TEXT NOT NULL, " +
                        "attempt INTEGER NOT NULL, nextRetryAtElapsedRealtime INTEGER NOT NULL, " +
                        "enqueueElapsedRealtime INTEGER NOT NULL, createdAtWallClock INTEGER NOT NULL, " +
                        "playOffsetSeconds REAL NOT NULL, packTotalDurationSeconds REAL NOT NULL, " +
                        "lastError TEXT)",
                )
                db.execSQL(
                    "CREATE UNIQUE INDEX IF NOT EXISTS index_cache_tasks_sourceKey " +
                        "ON cache_tasks (sourceKey)",
                )
                db.execSQL(
                    "CREATE INDEX IF NOT EXISTS index_cache_tasks_state ON cache_tasks (state)",
                )
                db.execSQL(
                    "CREATE INDEX IF NOT EXISTS index_cache_tasks_priority_enqueueElapsedRealtime " +
                        "ON cache_tasks (priority, enqueueElapsedRealtime)",
                )
                db.execSQL(
                    "CREATE TABLE IF NOT EXISTS cache_files (" +
                        "fileId TEXT NOT NULL, sourceKey TEXT NOT NULL, taskId INTEGER, " +
                        "path TEXT NOT NULL, sizeBytes INTEGER NOT NULL, origin TEXT NOT NULL, " +
                        "state TEXT NOT NULL, isTemporary INTEGER NOT NULL, isComplete INTEGER NOT NULL, " +
                        "createdElapsedRealtime INTEGER NOT NULL, lastAccessElapsedRealtime INTEGER NOT NULL, " +
                        "watchCount INTEGER NOT NULL, ttlHours INTEGER NOT NULL, PRIMARY KEY(fileId))",
                )
                db.execSQL(
                    "CREATE INDEX IF NOT EXISTS index_cache_files_sourceKey ON cache_files (sourceKey)",
                )
                db.execSQL(
                    "CREATE INDEX IF NOT EXISTS index_cache_files_state ON cache_files (state)",
                )
                db.execSQL(
                    "CREATE INDEX IF NOT EXISTS index_cache_files_origin_createdElapsedRealtime " +
                        "ON cache_files (origin, createdElapsedRealtime)",
                )
                db.execSQL(
                    "CREATE TABLE IF NOT EXISTS byte_range_manifests (" +
                        "taskId INTEGER NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL, " +
                        "committedElapsedRealtime INTEGER NOT NULL, PRIMARY KEY(taskId, start))",
                )
                db.execSQL(
                    "CREATE INDEX IF NOT EXISTS index_byte_range_manifests_taskId " +
                        "ON byte_range_manifests (taskId)",
                )
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
         * 6 → 7: the ad cadence table. Three rows, one per surface, and the column names and
         * nullability are Room's own for [AdCadenceEntity] — the entities declare `TEXT NOT NULL`
         * / `INTEGER NOT NULL` for all three, so a `surface TEXT` here would throw Room's runtime
         * schema validation the first time a device opened its own database.
         */
        val MIGRATION_6_7: Migration = object : Migration(6, 7) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL(
                    "CREATE TABLE IF NOT EXISTS ad_cadence (" +
                        "surface TEXT NOT NULL, lastShownAtMs INTEGER NOT NULL, " +
                        "postersScrolled INTEGER NOT NULL, PRIMARY KEY(surface))",
                )
            }
        }

        /**
         * 7 → 8: the two answer columns on `favorite_posts` and the refusal ledger. One ADD
         * COLUMN per statement, because SQLite has never supported adding two at once, and both
         * nullable with no default: an existing row was saved by a build that never asked, and a
         * stamp written here would be a fact about a round-trip that never happened.
         *
         * Nothing in this step may rebuild or empty `favorite_posts`, and the pin in
         * [com.raddstream.app.tooling.FavoritesSchemaGuardTest] keeps it that way — the row a
         * viewer saved is the one thing in this database they would notice losing.
         */
        val MIGRATION_7_8: Migration = object : Migration(7, 8) {
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
