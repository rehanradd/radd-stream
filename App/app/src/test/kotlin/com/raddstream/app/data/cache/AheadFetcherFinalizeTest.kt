package com.raddstream.app.data.cache

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.runBlocking
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.shadows.ShadowStatFs

/**
 * The finalize contract for one finished keep, run against the REAL [AheadFetcher] and the REAL
 * [AndroidStorageGate]: when a pass reports [FetchOutcome.COMPLETED], the `.part` must already be
 * renamed to its committed name and registered in `cache_files` — otherwise the Downloads list
 * says "Saved" over bytes the player cannot open (overview finding 1, trunk 26c9b52: both the
 * per-pass byte-cap return and the exhausted-plan return answered COMPLETED while only the
 * start-of-pass check ever called finalize).
 *
 * The HTTP layer is an OkHttp application interceptor that answers every Range with a slice of a
 * fixed in-memory payload — no socket, no MockWebServer. Plain JVM fakes cannot reach this
 * behaviour at all: `finalize` resolves the temp/committed names through [AndroidStorageGate]
 * itself, so the gate must be the production one.
 *
 * x86_64-only like every Robolectric suite (see the arm64 exclusion in `app/build.gradle.kts`).
 */
@RunWith(RobolectricTestRunner::class)
class AheadFetcherFinalizeTest {

    private val payload = ByteArray(8 * 1024) { (it % 251).toByte() }
    private val sourceKey = "sk-finish-1"

    // ── fakes ───────────────────────────────────────────────────────────────────

    private class FakeTaskDao : CacheTaskDao {
        val rows = LinkedHashMap<Long, CacheTaskEntity>()
        private val live = MutableStateFlow<List<CacheTaskEntity>>(emptyList())

        fun seed(task: CacheTaskEntity): CacheTaskEntity {
            rows[task.id] = task
            live.value = rows.values.toList()
            return task
        }

        override suspend fun insertIfAbsent(task: CacheTaskEntity): Long =
            rows.values.firstOrNull { it.sourceKey == task.sourceKey }?.id ?: task.id.also { seed(task) }

        override suspend fun upsert(task: CacheTaskEntity): Long { seed(task); return task.id }
        override suspend fun update(task: CacheTaskEntity) { seed(task) }
        override suspend fun getById(id: Long): CacheTaskEntity? = rows[id]
        override suspend fun getBySourceKey(sourceKey: String): CacheTaskEntity? =
            rows.values.firstOrNull { it.sourceKey == sourceKey }

        override fun observeBySourceKey(sourceKey: String): Flow<CacheTaskEntity?> =
            MutableStateFlow(rows.values.firstOrNull { it.sourceKey == sourceKey })

        override suspend fun listByStates(states: List<String>): List<CacheTaskEntity> =
            rows.values.filter { it.state in states }

        override suspend fun listSchedulable(nowElapsed: Long): List<CacheTaskEntity> =
            rows.values.filter {
                it.state in listOf("QUEUED", "LOADING", "PAUSED", "FAILED") &&
                    it.nextRetryAtElapsedRealtime <= nowElapsed
            }

        override suspend fun listLoading(): List<CacheTaskEntity> = rows.values.filter { it.state == "LOADING" }
        override fun observeAllActive(): Flow<List<CacheTaskEntity>> = live
        override suspend fun listAllActive(): List<CacheTaskEntity> = rows.values.toList()

        override suspend fun transition(id: Long, from: String, to: String): Int {
            val row = rows[id] ?: return 0
            if (row.state != from) return 0
            rows[id] = row.copy(state = to)
            return 1
        }

        override suspend fun recordProgress(
            id: Long,
            downloadedBytes: Long,
            verifiedPrefixBytes: Long,
            totalSizeBytes: Long,
            resumeToken: String,
            currentUrl: String,
        ) {
            rows[id]?.let { rows[id] = it.copy(
                downloadedBytes = downloadedBytes,
                verifiedPrefixBytes = verifiedPrefixBytes,
                totalSizeBytes = totalSizeBytes,
                resumeToken = resumeToken,
                currentUrl = currentUrl,
            ) }
        }

        override suspend fun recordRetryState(
            id: Long,
            state: String,
            attempt: Int,
            nextRetryAt: Long,
            error: String?,
        ) {
            rows[id]?.let { rows[id] = it.copy(
                state = state,
                attempt = attempt,
                nextRetryAtElapsedRealtime = nextRetryAt,
                lastError = error,
            ) }
        }

        override suspend fun setParkReason(id: Long, reason: String?) {
            rows[id]?.let { rows[id] = it.copy(lastError = reason) }
        }

        override suspend fun promoteToUserKeep(id: Long) {
            rows[id]?.let { rows[id] = it.copy(priority = CachePriority.USER_REQUESTED.name, origin = CacheOrigin.USER_KEEP.name) }
        }

        override suspend fun reResolveWithNewUrl(id: Long, newUrl: String) {
            rows[id]?.let { rows[id] = it.copy(currentUrl = newUrl) }
        }

        override suspend fun deleteById(id: Long) { rows.remove(id) }
        override suspend fun countRunning(): Int = rows.values.count { it.state == "LOADING" }
    }

    private class FakeManifestDao : ByteRangeManifestDao {
        val committed = MutableStateFlow<List<ByteRangeManifestEntity>>(emptyList())
        override suspend fun insertAll(rows: List<ByteRangeManifestEntity>) { committed.value = rows }
        override suspend fun deleteForTask(taskId: Long) {
            committed.value = committed.value.filterNot { it.taskId == taskId }
        }
        override suspend fun getForTask(taskId: Long): List<ByteRangeManifestEntity> =
            committed.value.filter { it.taskId == taskId }
        override suspend fun contiguousPrefix(taskId: Long): Long =
            getForTask(taskId).sortedBy { it.start }.fold(0L) { acc, r -> if (r.start == acc) r.end else acc }
        override suspend fun committedBytes(taskId: Long): Long = getForTask(taskId).sumOf { it.end - it.start }
        override suspend fun clear(taskId: Long) { deleteForTask(taskId) }
    }

    private inner class FakeFileDao : CacheFileDao {
        val rows = LinkedHashMap<String, CacheFileEntity>()
        override suspend fun upsert(file: CacheFileEntity) { rows[file.fileId] = file }
        override suspend fun update(file: CacheFileEntity) { rows[file.fileId] = file }
        override suspend fun getById(fileId: String): CacheFileEntity? = rows[fileId]
        override suspend fun getBySourceKey(sourceKey: String): List<CacheFileEntity> =
            rows.values.filter { it.sourceKey == sourceKey }
        override suspend fun listByTask(taskId: Long): List<CacheFileEntity> =
            rows.values.filter { it.taskId == taskId }
        override suspend fun listLive(): List<CacheFileEntity> = rows.values.filter { it.state != "DELETED" }
        override suspend fun totalBytesUsed(): Long = rows.values.filter { it.state != "DELETED" }.sumOf { it.sizeBytes }
        override suspend fun runningTaskFileIds(): List<String> = emptyList()
        override suspend fun touchOnPlay(fileId: String, now: Long) {
            rows[fileId]?.let { rows[fileId] = it.copy(lastAccessElapsedRealtime = now, watchCount = it.watchCount + 1) }
        }
        override suspend fun promoteOriginForTask(taskId: Long) {
            rows.values.filter { it.taskId == taskId }.forEach { rows[it.fileId] = it.copy(origin = CacheOrigin.USER_KEEP.name) }
        }
        override suspend fun setState(fileId: String, state: String) {
            rows[fileId]?.let { rows[fileId] = it.copy(state = state) }
        }
        override suspend fun deleteById(fileId: String) { rows.remove(fileId) }
    }

    /** Answers every Range header with the matching slice of [payload]; no socket involved. */
    private fun slicingClient(): OkHttpClient = OkHttpClient.Builder()
        .addInterceptor { chain ->
            val request = chain.request()
            // HTTP Range ends are INCLUSIVE: "bytes=0-1023" asks for 1024 bytes.
            val range = request.header("Range") ?: "bytes=0-${payload.size - 1}"
            val bounds = range.removePrefix("bytes=").split("-")
            val start = bounds[0].toLong().coerceAtMost(payload.size.toLong())
            val lastByte = bounds.getOrNull(1)?.takeIf { it.isNotBlank() }?.toLong()
                ?: (payload.size - 1L)
            val end = lastByte.coerceIn(start, (payload.size - 1L).coerceAtLeast(start))
            val slice = payload.copyOfRange(start.toInt(), (end + 1).toInt())
            Response.Builder()
                .request(request)
                .protocol(Protocol.HTTP_1_1)
                .code(206)
                .message("Partial Content")
                .header("Content-Range", "bytes $start-$end/${payload.size}")
                .body(slice.toResponseBody("application/octet-stream".toMediaType()))
                .build()
        }
        .build()

    // ── harness ─────────────────────────────────────────────────────────────────

    private inner class Fixture(chunkBytes: Int, maxBytesPerPass: Long) {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val taskDao = FakeTaskDao()
        val manifestDao = FakeManifestDao()
        val fileDao = FakeFileDao()
        val cacheRoot = java.io.File(context.filesDir, "media_cache")

        init {
            // ShadowStatFs keys stats off the path string handed to `new StatFs(path)`; the gate
            // asks about its own cacheRoot, so register there before anything constructs one.
            cacheRoot.mkdirs()
            val bs = ShadowStatFs.BLOCK_SIZE
            val blocks = (512L * 1024 * 1024 / bs).toInt() // 512 MiB free — far above every floor
            ShadowStatFs.registerStats(cacheRoot.absolutePath, blocks, blocks, blocks)
        }

        val storage = AndroidStorageGate(
            context = context,
            fileDao = fileDao,
            clock = UptimeClock { 1_000L },
        )

        val fetcher = AheadFetcher(
            fetcher = RangeByteFetcher(slicingClient()),
            taskDao = taskDao,
            manifestDao = manifestDao,
            fileDao = fileDao,
            storage = storage,
            clock = UptimeClock { 1_000L },
            maxBytesPerPass = maxBytesPerPass,
            chunkBytes = chunkBytes,
        )

        fun freshTask(): CacheTaskEntity = taskDao.seed(
            CacheTaskEntity(
                id = 1L,
                sourceKey = sourceKey,
                releaseId = 9L,
                linkKind = "direct",
                currentUrl = "https://cache.test/part",
                totalSizeBytes = payload.size.toLong(),
                priority = CachePriority.USER_REQUESTED.name,
                origin = CacheOrigin.USER_KEEP.name,
                state = CacheTaskState.LOADING.name,
            ),
        )

        val tempFile get() = java.io.File(cacheRoot, "$sourceKey.part")
        val committedFile get() = java.io.File(cacheRoot, sourceKey)
    }

    // ── tests ───────────────────────────────────────────────────────────────────

    @Test
    fun `a gate-refused range maps to GATED, never to a retry or a dead source`() {
        // Salaar (2026-11-12): our redirector refused the rung with the quality
        // gate's 402 before any redirect. The range fetcher must classify it
        // GateRefused (not HttpError, not SourceDead) and the ahead fetcher must
        // surface FetchOutcome.GATED, so the coordinator drops the preview
        // silently instead of retrying a rung that cannot play for this viewer.
        val refusingClient = OkHttpClient.Builder()
            .addInterceptor { chain ->
                Response.Builder()
                    .request(chain.request())
                    .protocol(Protocol.HTTP_1_1)
                    .code(402)
                    .message("Payment Required")
                    .body("".toResponseBody("text/plain".toMediaType()))
                    .build()
            }
            .build()
        val fx = Fixture(chunkBytes = 4 * 1024, maxBytesPerPass = 64L * 1024 * 1024)
        val gatedFetcher = AheadFetcher(
            fetcher = RangeByteFetcher(refusingClient),
            taskDao = fx.taskDao,
            manifestDao = fx.manifestDao,
            fileDao = fx.fileDao,
            storage = fx.storage,
            clock = UptimeClock { 1_000L },
            maxBytesPerPass = 64L * 1024 * 1024,
            chunkBytes = 4 * 1024,
        )

        val outcome = runBlocking {
            gatedFetcher.run(fx.freshTask(), FetchMode.FULL_DOWNLOAD) { 0L }
        }

        assertEquals(FetchOutcome.GATED, outcome)
        assertFalse("a gated rung must not publish a committed file", fx.committedFile.exists())
        assertNull(fx.fileDao.rows[sourceKey])
    }

    @Test
    fun `the exhausted-plan finish commits the file before reporting COMPLETED`() {
        // The common keep: smaller than the per-pass cap, so the loop runs out of ranges and the
        // tail of run() decides. Before the fix this returned COMPLETED over a bare .part.
        val fx = Fixture(chunkBytes = 4 * 1024, maxBytesPerPass = 64L * 1024 * 1024)
        val outcome = runBlocking { fx.fetcher.run(fx.freshTask(), FetchMode.FULL_DOWNLOAD) { 0L } }

        assertEquals(FetchOutcome.COMPLETED, outcome)
        assertTrue("COMPLETED without a committed file is the exact defect", fx.committedFile.exists())
        assertFalse("the .part must be renamed away", fx.tempFile.exists())
        fx.assertContentMatches()
        val row = fx.fileDao.rows[sourceKey]
        assertNotNull("a COMPLETED keep must be in the inventory offline-play can read", row)
        row!!
        assertEquals(CacheTaskState.COMPLETED.name, row.state)
        assertTrue(row.isComplete)
        assertFalse(row.isTemporary)
        assertEquals(fx.committedFile.absolutePath, row.path)
        assertEquals(payload.size.toLong(), row.sizeBytes)
    }

    @Test
    fun `the byte-cap finish commits too when the last chunk completes the file`() {
        // Chunk size × cap is tuned so the file fills EXACTLY on the pass-budget branch.
        val fx = Fixture(chunkBytes = 1024, maxBytesPerPass = 8 * 1024L)
        val outcome = runBlocking { fx.fetcher.run(fx.freshTask(), FetchMode.FULL_DOWNLOAD) { 0L } }

        assertEquals(FetchOutcome.COMPLETED, outcome)
        assertTrue(fx.committedFile.exists())
        assertFalse(fx.tempFile.exists())
        fx.assertContentMatches()
        assertNotNull(fx.fileDao.rows[sourceKey])
    }

    @Test
    fun `a cap stop that leaves gaps open stays WINDOW_FILLED and keeps its bytes resumable`() {
        // The fix must not invent completion: half a file stays a .part with a ledger, zero waste.
        val fx = Fixture(chunkBytes = 1024, maxBytesPerPass = 4 * 1024L)
        val outcome = runBlocking { fx.fetcher.run(fx.freshTask(), FetchMode.FULL_DOWNLOAD) { 0L } }

        assertEquals(FetchOutcome.WINDOW_FILLED, outcome)
        assertFalse("an incomplete fetch must not publish a committed file", fx.committedFile.exists())
        assertTrue("the .part stays for the next pass", fx.tempFile.exists())
        val task = fx.taskDao.rows[1L]!!
        assertEquals(4 * 1024L, task.downloadedBytes)
        assertEquals(4 * 1024L, task.verifiedPrefixBytes)
        assertNull(fx.fileDao.rows[sourceKey])
    }

    @Test
    fun `a second pass on an already-committed task re-finalizes idempotently`() {
        val fx = Fixture(chunkBytes = 4 * 1024, maxBytesPerPass = 64L * 1024 * 1024)
        runBlocking { fx.fetcher.run(fx.freshTask(), FetchMode.FULL_DOWNLOAD) { 0L } }
        val outcome = runBlocking {
            fx.fetcher.run(fx.taskDao.getById(1L)!!, FetchMode.FULL_DOWNLOAD) { 0L }
        }
        assertEquals(FetchOutcome.ALREADY_COMPLETE, outcome)
        assertTrue(fx.committedFile.exists())
        assertEquals(1, fx.fileDao.rows.size)
    }

    private fun Fixture.assertContentMatches() {
        assertTrue(
            "committed bytes must equal what the source served",
            payload.contentEquals(committedFile.readBytes()),
        )
    }
}
