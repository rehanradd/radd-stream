# HANDOFF — `data/cache` integration (what other agents must wire)

This package (`app/src/main/kotlin/com/raddstream/app/data/cache/`) is **self-contained and
inert**: it compiles against the existing deps but registers nothing. The owner of the
integration must apply the exact snippets below. I was not permitted to edit existing files, so
every wiring point lives here.

Scope boundaries (who owns what):
- **Player / `player/PlaybackService.kt` + `ui/screens/PlayerScreen.kt`** → call the two boundary
  methods `CacheCoordinator.onPlayheadAdvanced(...)` and `CacheCoordinator.keepNow(...)`, and open
  the returned local `Uri`/`LocalMediaProxy.baseHttpUrl` in Media3. See §5.
- **`data/local/AppDatabase.kt` + DI** → register the three entities/DAOs and the migration. §1–§3.
- **Repository / resolver** → supply `SourceResolver` (re-resolve an ephemeral URL) and the
  `ResolvedSource` used to enqueue a task. §4.
- **WorkManager owner** → add the `androidx.work` dependency and register the sweep worker. §6.

---

## 1. Room entities to register (do NOT re-declare them — they already exist)

`CacheTaskEntity` (`cache_tasks`), `ByteRangeManifestEntity` (`byte_range_manifests`),
`CacheFileEntity` (`cache_files`).

Edit `AppDatabase.kt`:

```kotlin
@Database(
    entities = [
        FavoritePost::class,
        CacheTaskEntity::class,
        ByteRangeManifestEntity::class,
        CacheFileEntity::class,
    ],
    version = 2,                 // bump from 1
    exportSchema = false,
    autoMigrations = [],         // ship the explicit migration below instead
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun favoriteDao(): FavoriteDao
    abstract fun cacheTaskDao(): CacheTaskDao
    abstract fun byteRangeManifestDao(): ByteRangeManifestDao
    abstract fun cacheFileDao(): CacheFileDao
}
```

Add imports:
`import com.raddstream.app.data.cache.CacheTaskEntity` / `ByteRangeManifestEntity` / `CacheFileEntity`
and the three `...Dao` interfaces.

## 2. Migration (1 → 2)

Room cannot auto-create these three tables across a version bump; register a `Migration`. If the
DB has already shipped at version 1 you MUST provide this or `Room` throws `IllegalStateException`.

```kotlin
val MIGRATION_1_2 = object : Migration(1, 2) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL(
            """
            CREATE TABLE IF NOT EXISTS cache_tasks (
              id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
              sourceKey TEXT NOT NULL,
              releaseId INTEGER NOT NULL,
              linkKind TEXT NOT NULL,
              currentUrl TEXT NOT NULL,
              resourceId TEXT,
              origin TEXT NOT NULL,
              priority TEXT NOT NULL,
              state TEXT NOT NULL,
              totalSizeBytes INTEGER NOT NULL,
              downloadedBytes INTEGER NOT NULL,
              verifiedPrefixBytes INTEGER NOT NULL,
              resumeToken TEXT NOT NULL,
              attempt INTEGER NOT NULL,
              nextRetryAtElapsedRealtime INTEGER NOT NULL,
              enqueueElapsedRealtime INTEGER NOT NULL,
              createdAtWallClock INTEGER NOT NULL,
              playOffsetSeconds REAL NOT NULL,
              packTotalDurationSeconds REAL NOT NULL,
              lastError TEXT
            )
            """.trimIndent()
        )
        db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS index_cache_tasks_sourceKey ON cache_tasks(sourceKey)")
        db.execSQL("CREATE INDEX IF NOT EXISTS index_cache_tasks_state ON cache_tasks(state)")
        db.execSQL("CREATE INDEX IF NOT EXISTS index_cache_tasks_priority_enqueueElapsedRealtime ON cache_tasks(priority, enqueueElapsedRealtime)")

        db.execSQL(
            """
            CREATE TABLE IF NOT EXISTS byte_range_manifests (
              taskId INTEGER NOT NULL,
              start INTEGER NOT NULL,
              end INTEGER NOT NULL,
              committedElapsedRealtime INTEGER NOT NULL,
              PRIMARY KEY (taskId, start)
            )
            """.trimIndent()
        )
        db.execSQL("CREATE INDEX IF NOT EXISTS index_byte_range_manifests_taskId ON byte_range_manifests(taskId)")

        db.execSQL(
            """
            CREATE TABLE IF NOT EXISTS cache_files (
              fileId TEXT NOT NULL PRIMARY KEY,
              sourceKey TEXT NOT NULL,
              taskId INTEGER,
              path TEXT NOT NULL,
              sizeBytes INTEGER NOT NULL,
              origin TEXT NOT NULL,
              state TEXT NOT NULL,
              isTemporary INTEGER NOT NULL,
              isComplete INTEGER NOT NULL,
              createdElapsedRealtime INTEGER NOT NULL,
              lastAccessElapsedRealtime INTEGER NOT NULL,
              watchCount INTEGER NOT NULL,
              ttlHours INTEGER NOT NULL
            )
            """.trimIndent()
        )
        db.execSQL("CREATE INDEX IF NOT EXISTS index_cache_files_sourceKey ON cache_files(sourceKey)")
        db.execSQL("CREATE INDEX IF NOT EXISTS index_cache_files_state ON cache_files(state)")
        db.execSQL("CREATE INDEX IF NOT EXISTS index_cache_files_origin_createdElapsedRealtime ON cache_files(origin, createdElapsedRealtime)")
    }
}
```

Then in `DatabaseModule` where the DB is built, add `.addMigrations(MIGRATION_1_2)`.

## 3. Hilt providers (add to a new module, e.g. `di/CacheModule.kt`)

```kotlin
@Module @InstallIn(SingletonComponent::class)
object CacheModule {

    @Provides @Singleton fun cacheTaskDao(db: AppDatabase): CacheTaskDao = db.cacheTaskDao()
    @Provides @Singleton fun byteRangeManifestDao(db: AppDatabase): ByteRangeManifestDao = db.byteRangeManifestDao()
    @Provides @Singleton fun cacheFileDao(db: AppDatabase): CacheFileDao = db.cacheFileDao()

    @Provides @Singleton fun uptimeClock(): UptimeClock = AndroidUptimeClock()

    // The OkHttp client used for media BYTES (separate from the Retrofit catalog client so a
    // multi-MB download cannot starve catalog calls; longer timeouts, no automatic retry).
    @Provides @Singleton
    fun mediaOkHttpClient(): OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .callTimeout(0, TimeUnit.MILLISECONDS) // whole-file downloads are long
        .retryOnConnectionFailure(true)
        .build()

    @Provides @Singleton
    fun storageGate(@ApplicationContext ctx: Context, dao: CacheFileDao): StorageGate =
        AndroidStorageGate(ctx, dao, AndroidUptimeClock())

    @Provides @Singleton
    fun rangeByteFetcher(client: OkHttpClient) = RangeByteFetcher(client)

    @Provides @Singleton
    fun hlsAheadBuffer(client: OkHttpClient, clock: UptimeClock) = HlsAheadBuffer(client, clock)

    @Provides @Singleton
    fun aheadFetcher(
        fetcher: RangeByteFetcher, tasks: CacheTaskDao, manifests: ByteRangeManifestDao,
        files: CacheFileDao, gate: StorageGate, clock: UptimeClock,
    ) = AheadFetcher(fetcher, tasks, manifests, files, gate, clock)

    // Provide CacheCoordinator as a @Singleton Application scope, injecting an
    // ApplicationCoroutineScope and a SourceResolver bound to the resolver layer (see §4).
}
```

`CacheCoordinator` needs a `CoroutineScope` and a `SourceResolver` — bind a `@ApplicationScope`
(`SupervisorJob() + Dispatchers.Default`) and the resolver in this module.

## 4. `SourceResolver` — bridging to the existing stream resolver

Implement this against the already-existing `CatalogRepository.resolveStream(...)`
(`/api/v1/stream?id=…&redirect=0`, see `App/AGENTS.md` §5) and return a fresh URL:

```kotlin
class StreamSourceResolver(private val repo: CatalogRepository) : SourceResolver {
    override suspend fun reResolve(sourceKey: String, releaseId: Long): ResolvedSource? {
        val s = repo.resolveStream(id = releaseId /* source id */, redirect = false).getOrNull() ?: return null
        val url = s.url ?: return null
        return ResolvedSource(
            releaseId = releaseId,
            linkKind = if (url.contains(".m3u8")) "hls_manifest" else "cdn_direct",
            url = url,
            resourceId = null,                    // the resolver returns none today; §SourceIdentity
            sizeBytes = null,                     // filled on first response via Content-Range
        )
    }
}
```

**Enqueueing a task** (called from the Detail/Player layer when playback starts): build the
identity from the PlayBundle/catalog link fields (`releaseId`, `resourceId`, `kind`, resolved
`url`, `size_bytes`) using `SourceIdentity.from(...)`, insert a `CacheTaskEntity` via
`CacheTaskDao.insertIfAbsent(...)` with `priority = AUTO_PREVIEW`, then call `coordinator.tick()`.

## 5. Player boundary contract (the differentiator)

The player must do exactly two things. All byte math lives in this package (unit-tested).

1. **As playback runs**, convert the current position to an absolute byte and report it. For a
   `season_pack` rendition, `CoverageMapping` (with the release `offset_seconds`) does
   `episodeByteAt(positionSeconds)`. Call:
   ```kotlin
   coordinator.onPlayheadAdvanced(sourceKey, playheadByte) // bounded auto-preview pass
   ```
   `AheadFetcher` then downloads the gaps in `[playhead, playhead + 40 MiB)`, recording each in
   the ledger — for `accepts_ranges=1` files (range writes) or via `HlsAheadBuffer` for
   `hls_manifest` (segment writes).

2. **When the user taps "keep this"**, call:
   ```kotlin
   val handle = coordinator.keepNow(sourceKey)
   ```
   This promotes the AUTO_PREVIEW task to USER_REQUESTED (so it drives to 100% from the bytes it
   already holds — **never from 0**) and returns a `LocalPlaybackHandle`.

   To let the player keep playing the partial file (and to play it fully offline once done), open a
   **loopback-only local source**, never a `FileProvider`/`ACTION_VIEW`:
   ```kotlin
   val proxy = LocalMediaProxy(
       file = handle.file,
       prefixProvider = { /* return manifestDao.contiguousPrefix(handle.taskId) */ runBlocking { handle.verifiedPrefixProvider() } },
       contentType = "video/mp4", // or the resolved mime_type
   )
   player.setMediaItem(MediaItem.fromUri(proxy.uriFor()))
   // ... on stop/teardown: proxy.close()
   ```
   `LocalMediaProxy` serves HTTP 206 `Range` from the private file and reports EOF (416) beyond
   the verified prefix, so Media3 plays exactly what is on disk and never reads holes. For a
   `hls_manifest` resource, point Media3 at the `local.m3u8` file produced by `HlsAheadBuffer`
   instead (it lives in the same private dir). For a fully completed file you may also use
   `Uri.fromFile(...)` (the `CacheFileEntity.toLocalUri()` helper) — still app-private, still no
   external handoff.

## 6. WorkManager — TTL sweep + eviction (requires a dependency the app does not yet have)

**Add to `libs.versions.toml` + `app/build.gradle.kts` (I could not edit Gradle):**

```toml
work = "2.9.0"
work-runtime-ktx = { group = "androidx.work", name = "work-runtime-ktx", version.ref = "work" }
```
```kotlin
implementation(libs.work.runtime.ktx)
```

The pure orchestration is `CacheSweeper` (already written and unit-tested). A real store adapter
backed by the DAOs:

```kotlin
class DaoCacheSweepStore(
    private val fileDao: CacheFileDao,
    private val clock: UptimeClock,
    private val gate: StorageGate,
    private val ttl: () -> TtlHours,
) : CacheSweepStore {
    override suspend fun liveFiles() = fileDao.listLive()
    override suspend fun runningFileIds() = fileDao.runningTaskFileIds().toSet()
    override suspend fun removeOnDisk(entity: CacheFileEntity) {
        java.io.File(entity.path).delete()
        java.io.File(entity.path + ".part").delete()
    }
    override suspend fun deleteFileRow(fileId: String) = fileDao.deleteById(fileId)
    override suspend fun workspaceUsedBytes() = gate.workspaceUsedBytes()
    override suspend fun osFreeBytes() = gate.osFreeBytes()
    override fun limits() = gate.limits()
    override fun ttlHours() = ttl()
}

class CacheSweepWorker(app: Context, params: WorkerParameters) : CoroutineWorker(app, params) {
    @Inject lateinit var store: DaoCacheSweepStoreLazy /* or construct from injected DAOs */
    override suspend fun doWork(): Result {
        // CacheSweeper is constructed with (store, AndroidUptimeClock()). Run it:
        // CacheSweeper(store, AndroidUptimeClock()).sweep()
        return Result.success()
    }
}
```

Enqueue with **battery-friendly constraints** (owner wires this at app start / on settings change):

```kotlin
WorkManager.getInstance(ctx).enqueueUniquePeriodicWork(
    "cache_ttl_sweep", ExistingPeriodicWorkPolicy.KEEP,
    PeriodicWorkRequestBuilder<CacheSweepWorker>(12, TimeUnit.HOURS)
        .setConstraints(Constraints.Builder()
            .setRequiredNetworkType(NetworkType.NOT_REQUIRED)
            .setRequiresBatteryNotLow(true)
            .setRequiresCharging(false)
            .build())
        .build()
)
```
Also trigger a one-time `CacheSweepWorker` immediately after the TTL setting changes so a "3h"
change takes effect without waiting for the next period. The periodic interval (12h) is coarser
than the TTL; the sweep uses elapsedRealtime so a file is deleted on the first sweep after its
window, and `TtlPolicy.millisUntilDue` lets the owner compute the exact next-due time if they want
a finer `OneTimeWorkRequest` chain instead.

## 7. User settings the cache reads (map from DataStore)

- `ttlHours`: 3 or 6 → `TtlHours.fromHours(...)` (used by the sweeper and `CacheFileEntity.ttlHours`).
- `cacheCeilingBytes`: the `AndroidStorageGate.ceilingBytes` hard cap (default 2 GiB).
- `allowAutoPreviewOnMobile`: → `SchedulerPolicy.allowAutoPreviewOnMobile`.
- `autoPreviewDataBudgetBytes`: → `SchedulerPolicy.autoPreviewDataBudgetBytes`.
- `maxConcurrent`: → `SchedulerPolicy.maxConcurrent` (default 2).

## 8. Permissions / manifest notes

- No new permission is required: downloads use the app's INTERNET permission and write only to
  `context.filesDir` (private storage). There is deliberately **no `FileProvider`** and **no
  `ACTION_VIEW`/external intent** anywhere in this package (app-only playback requirement).
- The `LocalMediaProxy` binds a `ServerSocket` to `InetAddress.getLoopbackAddress()` only; it is
  never reachable off-device. Cleartext is loopback HTTP, not the network — it is unaffected by the
  release-build "HTTPS only" rule and needs no network-security-config change.

## 9. What is intentionally NOT done here (flag for the integrator)

- `CacheCoordinator.runHlsPass` maps `startSegmentIndex` from `playOffsetSeconds` as a rough proxy;
  the player should pass the true current segment index once Media3 reports `positionUs` for HLS.
- `SourceResolver` uses the current `/api/v1/stream` shape; when the app moves to
  `POST /api/v2/play` (see `API_V2.md` §5) feed `renditions[].playback.{url,resource_id,ephemeral,
  expires_at,accepts_ranges,size_bytes}` + `coverage.offset_seconds` directly into
  `SourceIdentity.from(...)` and `CoverageMapping` — the cache API already matches that payload.
