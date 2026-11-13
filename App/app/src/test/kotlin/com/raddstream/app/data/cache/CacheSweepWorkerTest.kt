package com.raddstream.app.data.cache

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.work.ListenableWorker
import androidx.work.WorkerFactory
import androidx.work.WorkerParameters
import androidx.work.testing.TestListenableWorkerBuilder
import com.raddstream.app.data.local.AppDatabase
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.shadows.ShadowStatFs
import javax.inject.Provider

/**
 * Session 160 — the S6 device test (2026-11-13) found the closed-app cache sweep never ran:
 * logcat at startup said "Could not create Worker com.raddstream.app.data.cache.CacheSweepWorker"
 * (NoSuchMethodException). Root cause: the app shipped `androidx.hilt:hilt-work` (the runtime)
 * but never declared the `androidx.hilt:hilt-compiler` kapt processor, so `@HiltWorker`
 * generated no `CacheSweepWorker_AssistedFactory` / `CacheSweepWorker_HiltModule`,
 * `HiltWorkerFactory`'s map was empty, and WorkManager's reflection fallback looked for a
 * `(Context, WorkerParameters)` constructor the worker does not have. The fix is that one
 * kapt line (see `app/build.gradle.kts`); this test pins it: it builds the worker through the
 * generated assisted factory — the exact call `HiltWorkerFactory` makes at runtime — so if
 * the processor is ever dropped again the test fails to compile (`CacheSweepWorker_AssistedFactory`
 * stops existing) instead of failing silently on a device.
 *
 * The store is the real one ([RoomCacheSweepStore] over an in-memory [AppDatabase] plus the
 * production [AndroidStorageGate]), not a fake: the sweep must actually delete an expired
 * auto-preview keep through Room and disk, not just construct.
 *
 * x86_64-only like every Robolectric suite (see the arm64 exclusion in `app/build.gradle.kts`).
 */
@RunWith(RobolectricTestRunner::class)
class CacheSweepWorkerTest {

    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val clock = FixedUptimeClock(4L * 3_600_000L) // 4 hours in; TTL is 3 h
    private lateinit var db: AppDatabase

    @Before
    fun setUp() {
        db = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java)
            .allowMainThreadQueries()
            .build()
        // ShadowStatFs keys stats off the path string handed to `new StatFs(path)`; the gate
        // asks about its own cacheRoot, so register there before anything sweeps.
        val cacheRoot = java.io.File(context.filesDir, "media_cache").apply { mkdirs() }
        val bs = ShadowStatFs.BLOCK_SIZE
        val blocks = (512L * 1024 * 1024 / bs).toInt() // 512 MiB free — far above every floor
        ShadowStatFs.registerStats(cacheRoot.absolutePath, blocks, blocks, blocks)
    }

    @After
    fun tearDown() {
        db.close()
    }

    private fun store(): RoomCacheSweepStore = RoomCacheSweepStore(
        fileDao = db.cacheFileDao(),
        taskDao = db.cacheTaskDao(),
        storage = AndroidStorageGate(context = context, fileDao = db.cacheFileDao(), clock = clock),
        ttlHoursProvider = Provider { TtlHours.THREE },
    )

    /**
     * What [androidx.hilt.work.HiltWorkerFactory] does at runtime: look the worker's class name
     * up in its map and call the assisted factory's `create`. (Its constructor is
     * package-private, so the test mirrors the lookup with a one-line delegating factory
     * instead of constructing it.)
     */
    private fun hiltStyleFactory(
        assistedFactory: CacheSweepWorker_AssistedFactory,
    ): WorkerFactory = object : WorkerFactory() {
        override fun createWorker(
            appContext: Context,
            workerClassName: String,
            workerParameters: WorkerParameters,
        ): ListenableWorker? =
            if (workerClassName == CacheSweepWorker::class.java.name) {
                assistedFactory.create(appContext, workerParameters)
            } else {
                null
            }
    }

    private fun buildWorker(): CacheSweepWorker {
        // The type here is the regression pin: CacheSweepWorker_AssistedFactory is generated
        // by androidx.hilt:hilt-compiler from @HiltWorker. Drop the kapt line and this file
        // stops compiling — the same silent device-only failure S6 caught.
        val assistedFactory: CacheSweepWorker_AssistedFactory =
            CacheSweepWorker_Factory(Provider { store() }, Provider { clock })
        val worker = TestListenableWorkerBuilder<CacheSweepWorker>(context, CacheSweepWorker::class.java)
            .setWorkerFactory(hiltStyleFactory(assistedFactory))
            .build()
        assertNotNull("Hilt factory must build CacheSweepWorker", worker)
        return worker
    }

    @Test
    fun `hilt factory builds the worker and an empty sweep succeeds`() {
        val worker = buildWorker()
        val result = runBlocking { worker.doWork() }
        assertTrue("empty sweep must succeed, was $result", result is ListenableWorker.Result.Success)
    }

    @Test
    fun `worker deletes an expired auto-preview keep through the real store`() {
        runBlocking {
            db.cacheFileDao().upsert(
                CacheFileEntity(
                    fileId = "auto-old", sourceKey = "src-auto-old", taskId = null,
                    path = "/private/auto-old", sizeBytes = 1000L,
                    origin = CacheOrigin.AUTO_PREVIEW.name,
                    state = CacheTaskState.COMPLETED.name,
                    isTemporary = false, isComplete = true,
                    createdElapsedRealtime = 0L, lastAccessElapsedRealtime = 0L, watchCount = 0,
                ),
            )
        }
        val worker = buildWorker()
        val result = runBlocking { worker.doWork() }
        assertTrue("sweep must succeed, was $result", result is ListenableWorker.Result.Success)
        val row = runBlocking { db.cacheFileDao().getById("auto-old") }
        assertNull("expired auto-preview keep must be deleted by the sweep", row)
    }
}
