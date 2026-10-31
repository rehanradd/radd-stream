package com.raddstream.app.data.cache

import com.raddstream.app.repository.CacheRepository
import com.raddstream.app.repository.KeepOutcome
import java.io.File
import javax.inject.Provider
import kotlin.coroutines.CoroutineContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.yield
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Wiring-level tests for the offline keep feature. They use hand-written fakes for the Room DAOs,
 * the storage gate, the resolver and the byte mover, but drive the REAL [CacheCoordinator],
 * [CacheRepository] and [RoomCacheSweepStore] / [CacheSweeper] — so the state machine, the free-space
 * admission, the resume identity and the TTL auto-delete are exercised exactly as the app runs them.
 *
 * Plain JUnit4 on the JVM only (no Robolectric, no device, no MockWebServer): every suspend call is
 * driven with [runBlocking], and the coordinator is given an unconfined scope so a launched task
 * completes synchronously inside the enqueue call.
 */
class OfflineCacheWiringTest {

    // ── fake DAO: tasks ────────────────────────────────────────────────────────

    private class FakeTaskDao : CacheTaskDao {
        val rows = LinkedHashMap<Long, CacheTaskEntity>()
        private var nextId = 1L
        private val snapshot = MutableStateFlow<List<CacheTaskEntity>>(emptyList())
        var reResolvedUrlSeen: String? = null

        private fun publish() { snapshot.value = rows.values.toList() }
        private fun put(task: CacheTaskEntity): Long {
            val id = if (task.id == 0L) nextId++ else task.id
            rows[id] = task.copy(id = id)
            publish()
            return id
        }

        override suspend fun insertIfAbsent(task: CacheTaskEntity): Long {
            rows.values.firstOrNull { it.sourceKey == task.sourceKey }?.let { return -1L }
            return put(task)
        }

        override suspend fun upsert(task: CacheTaskEntity): Long {
            val existing = if (task.id != 0L) rows[task.id]
            else rows.values.firstOrNull { it.sourceKey == task.sourceKey }
            return put(if (existing != null) task.copy(id = existing.id) else task)
        }

        override suspend fun update(task: CacheTaskEntity) { put(task) }

        override suspend fun getById(id: Long): CacheTaskEntity? = rows[id]

        override suspend fun getBySourceKey(sourceKey: String): CacheTaskEntity? =
            rows.values.firstOrNull { it.sourceKey == sourceKey }

        override fun observeBySourceKey(sourceKey: String) =
            snapshot.map { list -> list.firstOrNull { it.sourceKey == sourceKey } }

        override suspend fun listByStates(states: List<String>): List<CacheTaskEntity> =
            rows.values.filter { it.state in states }

        override suspend fun listSchedulable(): List<CacheTaskEntity> =
            rows.values.filter {
                it.state in setOf(
                    CacheTaskState.QUEUED.name, CacheTaskState.LOADING.name,
                    CacheTaskState.PAUSED.name, CacheTaskState.FAILED.name,
                )
            }

        override suspend fun listLoading(): List<CacheTaskEntity> =
            rows.values.filter { it.state == CacheTaskState.LOADING.name }

        override fun observeAllActive() = snapshot.map { list ->
            list.filter { it.state != CacheTaskState.DELETED.name }
                .sortedByDescending { it.createdAtWallClock }
        }

        override suspend fun listAllActive(): List<CacheTaskEntity> =
            rows.values.filter { it.state != CacheTaskState.DELETED.name }
                .sortedByDescending { it.createdAtWallClock }

        override suspend fun transition(id: Long, from: String, to: String): Int {
            val row = rows[id] ?: return 0
            if (row.state != from) return 0
            rows[id] = row.copy(state = to)
            publish()
            return 1
        }

        override suspend fun recordProgress(
            id: Long, downloadedBytes: Long, verifiedPrefixBytes: Long,
            totalSizeBytes: Long, resumeToken: String, currentUrl: String,
        ) {
            val row = rows[id] ?: return
            rows[id] = row.copy(
                downloadedBytes = downloadedBytes, verifiedPrefixBytes = verifiedPrefixBytes,
                totalSizeBytes = if (totalSizeBytes > 0) totalSizeBytes else row.totalSizeBytes,
                resumeToken = resumeToken, currentUrl = currentUrl,
            )
            publish()
        }

        override suspend fun markFailedWithRetry(id: Long, attempt: Int, nextRetryAt: Long, error: String?) {
            val row = rows[id] ?: return
            rows[id] = row.copy(state = CacheTaskState.FAILED.name, attempt = attempt, nextRetryAtElapsedRealtime = nextRetryAt, lastError = error)
            publish()
        }

        override suspend fun setParkReason(id: Long, reason: String?) {
            val row = rows[id] ?: return
            rows[id] = row.copy(lastError = reason)
            publish()
        }

        override suspend fun promoteToUserKeep(id: Long) {
            val row = rows[id] ?: return
            rows[id] = row.copy(priority = CachePriority.USER_REQUESTED.name, origin = CacheOrigin.USER_KEEP.name)
            publish()
        }

        override suspend fun reResolveWithNewUrl(id: Long, newUrl: String) {
            val row = rows[id] ?: return
            reResolvedUrlSeen = newUrl
            rows[id] = row.copy(currentUrl = newUrl, state = CacheTaskState.QUEUED.name, nextRetryAtElapsedRealtime = 0, lastError = null)
            publish()
        }

        override suspend fun deleteById(id: Long) { rows.remove(id); publish() }

        override suspend fun countRunning(): Int = rows.values.count {
            it.state == CacheTaskState.QUEUED.name || it.state == CacheTaskState.LOADING.name
        }
    }

    // ── fake DAO: files ────────────────────────────────────────────────────────

    private class FakeFileDao(private val taskDao: FakeTaskDao) : CacheFileDao {
        val rows = LinkedHashMap<String, CacheFileEntity>()
        val deleted = mutableListOf<String>()

        private fun runningIds(): Set<String> = taskDao.rows.values
            .filter { it.state == CacheTaskState.QUEUED.name || it.state == CacheTaskState.LOADING.name }
            .mapNotNull { id -> rows.values.firstOrNull { it.taskId == id.id }?.fileId }
            .toSet()

        override suspend fun upsert(file: CacheFileEntity) { rows[file.fileId] = file }
        override suspend fun update(file: CacheFileEntity) { rows[file.fileId] = file }
        override suspend fun getById(fileId: String): CacheFileEntity? = rows[fileId]
        override suspend fun getBySourceKey(sourceKey: String): List<CacheFileEntity> =
            rows.values.filter { it.sourceKey == sourceKey }
        override suspend fun listByTask(taskId: Long): List<CacheFileEntity> =
            rows.values.filter { it.taskId == taskId }
        override suspend fun listLive(): List<CacheFileEntity> =
            rows.values.filter { it.state != CacheTaskState.DELETED.name }
        override suspend fun totalBytesUsed(): Long =
            rows.values.filter { it.state != CacheTaskState.DELETED.name }.sumOf { it.sizeBytes }
        override suspend fun runningTaskFileIds(): List<String> = runningIds().toList()
        override suspend fun touchOnPlay(fileId: String, now: Long) {
            rows[fileId]?.let { rows[fileId] = it.copy(lastAccessElapsedRealtime = now, watchCount = it.watchCount + 1) }
        }
        override suspend fun commitAsUserKeep(fileId: String) {
            rows[fileId]?.let {
                rows[fileId] = it.copy(isTemporary = false, isComplete = true, origin = CacheOrigin.USER_KEEP.name, state = CacheTaskState.COMPLETED.name)
            }
        }
        override suspend fun setState(fileId: String, state: String) {
            rows[fileId]?.let { rows[fileId] = it.copy(state = state) }
        }
        override suspend fun deleteById(fileId: String) { rows.remove(fileId); deleted.add(fileId) }
    }

    // ── fake DAO: byte ledger ───────────────────────────────────────────────────

    private class FakeManifestDao : ByteRangeManifestDao {
        val rows = mutableListOf<ByteRangeManifestEntity>()
        override suspend fun insertAll(rows: List<ByteRangeManifestEntity>) { this.rows.addAll(rows) }
        override suspend fun deleteForTask(taskId: Long) { rows.removeAll { it.taskId == taskId } }
        override suspend fun getForTask(taskId: Long): List<ByteRangeManifestEntity> =
            rows.filter { it.taskId == taskId }.sortedBy { it.start }
        override suspend fun contiguousPrefix(taskId: Long): Long =
            rows.filter { it.taskId == taskId && it.start == 0L }.maxOfOrNull { it.end } ?: 0L
        override suspend fun committedBytes(taskId: Long): Long =
            rows.filter { it.taskId == taskId }.sumOf { it.end - it.start }
        override suspend fun clear(taskId: Long) { rows.removeAll { it.taskId == taskId } }
    }

    // ── fake storage gate ───────────────────────────────────────────────────────

    private class FakeStorage(
        var limits: StorageLimits = StorageLimits(hardCeilingBytes = 10L * 1024 * 1024 * 1024, lowStorageFloorBytes = 0L, perFileMaxBytes = 10L * 1024 * 1024 * 1024),
        var osFree: Long = 10L * 1024 * 1024 * 1024,
        var workspaceUsed: Long = 0L,
        var candidates: List<EvictionCandidate> = emptyList(),
    ) : StorageGate {
        val deleted = mutableListOf<String>()
        override suspend fun osFreeBytes(): Long = osFree
        override suspend fun workspaceUsedBytes(): Long = workspaceUsed
        override fun limits(): StorageLimits = limits
        override suspend fun currentCandidates(nowElapsedRealtime: Long): List<EvictionCandidate> = candidates
        override suspend fun openForWrite(fileId: String, size: Long?): File =
            File.createTempFile("cache-fake-", ".part").apply { deleteOnExit() }
        override fun deleteOnDisk(fileId: String) { deleted.add(fileId) }
    }

    // ── fake resolver + factory ─────────────────────────────────────────────────

    private class FakeResolver : SourceResolver {
        var askedSourceKey: String? = null
        var next: ResolvedSource? = null
        override suspend fun reResolve(sourceKey: String, releaseId: Long): ResolvedSource? {
            askedSourceKey = sourceKey
            return next
        }
    }

    private class FakeFactory(private val baseUrl: String) : KeepSourceFactory {
        var metaMimeType: String? = null
        var metaSize: Long? = null
        override suspend fun seedForKeep(handle: String, sizeBytes: Long?, resumable: Boolean): KeepSeed? {
            val clean = handle.trim().takeIf { it.isNotEmpty() } ?: return null
            return KeepSeed(
                sourceKey = KeepIdentity.sourceKeyFor(clean),
                handle = clean,
                redirectUrl = "$baseUrl/api/v1/stream?id=$clean",
                linkKind = KeepIdentity.linkKindFor(metaMimeType, null),
                releaseId = KeepIdentity.KEEP_RELEASE_ID,
                totalSizeBytes = sizeBytes?.takeIf { it > 0 } ?: metaSize ?: 0L,
            )
        }
        override suspend fun refreshUrl(handle: String): String = "$baseUrl/api/v1/stream?id=$handle"
    }

    // ── fake byte mover ─────────────────────────────────────────────────────────

    /** Returns the scripted [FetchOutcome]s in order, capturing the task it saw each time. */
    private class FakeAhead(private vararg val outcomes: FetchOutcome) : AheadExecutor {
        val seenTasks = mutableListOf<CacheTaskEntity>()
        var index = 0
        override suspend fun run(task: CacheTaskEntity, mode: FetchMode, playhead: PlayheadProvider): FetchOutcome {
            seenTasks.add(task)
            val outcome = outcomes.getOrElse(index) { outcomes.last() }
            index++
            return outcome
        }
    }

    private fun newTask(
        handle: String,
        id: Long,
        state: CacheTaskState,
        url: String,
        downloaded: Long = 0,
        total: Long = 1000,
    ) = CacheTaskEntity(
        id = id,
        sourceKey = KeepIdentity.sourceKeyFor(handle),
        releaseId = KeepIdentity.KEEP_RELEASE_ID,
        linkKind = KeepIdentity.KIND_PROGRESSIVE,
        currentUrl = url,
        resourceId = handle,
        totalSizeBytes = total,
        downloadedBytes = downloaded,
        origin = CacheOrigin.AUTO_PREVIEW.name,
        priority = CachePriority.USER_REQUESTED.name,
        state = state.name,
    )

    private class Wiring(
        val taskDao: FakeTaskDao,
        val fileDao: FakeFileDao,
        val manifestDao: FakeManifestDao,
        val storage: FakeStorage,
        val resolver: FakeResolver,
        val ahead: FakeAhead,
        val coordinator: CacheCoordinator,
        val factory: FakeFactory,
        val repository: CacheRepository,
    )

    private fun wiring(ctx: CoroutineContext, ahead: FakeAhead, storage: FakeStorage = FakeStorage()): Wiring {
        val taskDao = FakeTaskDao()
        val fileDao = FakeFileDao(taskDao)
        val manifestDao = FakeManifestDao()
        val resolver = FakeResolver()
        val clock = FixedUptimeClock(0L)
        // A scope sharing the runBlocking event loop (single-threaded) so the coordinator's
        // job-then-launch ordering holds exactly as it does on Dispatchers.Default in production,
        // while every fake stays on one thread (no cross-thread map races).
        val scope = CoroutineScope(ctx + SupervisorJob())
        val coordinator = CacheCoordinator(
            scope = scope,
            taskDao = taskDao,
            manifestDao = manifestDao,
            fileDao = fileDao,
            aheadFetcher = ahead,
            rangeFetcher = RangeByteFetcher(okhttp3.OkHttpClient()),
            hlsBuffer = HlsAheadBuffer(okhttp3.OkHttpClient(), clock),
            storage = storage,
            resolver = resolver,
            clock = clock,
            policy = SchedulerPolicy(maxConcurrent = 2, allowAutoPreviewOnMobile = false),
            networkProvider = { NetworkClass.WIFI },
        )
        val factory = FakeFactory("https://catalog.test")
        val repository = CacheRepository(coordinator, taskDao, factory, storage, clock)
        return Wiring(taskDao, fileDao, manifestDao, storage, resolver, ahead, coordinator, factory, repository)
    }

    /** Let the queued engine pass run to a terminal state on the shared event loop. */
    private suspend fun awaitState(dao: FakeTaskDao, id: Long, expected: CacheTaskState) {
        var guard = 0
        while (dao.getById(id)?.stateEnum != expected && guard++ < MAX_EVENT_LOOP_PUMPS) yield()
    }

    // ── (a) enqueue → task → progresses through the real state machine ──────────

    @Test
    fun `keep enqueues a task and the engine drives it to completion`() = runBlocking {
        val w = wiring(coroutineContext, FakeAhead(FetchOutcome.COMPLETED))
        val outcome = w.repository.keep(handle = "HDL-1", title = "Some Work", sizeBytes = 2000, resumable = true, printLabel = "1080p")

        val taskId = when (outcome) {
            is KeepOutcome.Enqueued -> outcome.taskId
            else -> error("expected Enqueued, got $outcome")
        }
        awaitState(w.taskDao, taskId, CacheTaskState.COMPLETED)
        val stored = w.taskDao.getById(taskId)!!
        assertEquals("the whole download ran to 100% through the real state machine", CacheTaskState.COMPLETED.name, stored.state)
        assertEquals(CachePriority.USER_REQUESTED.name, stored.priority)
        assertEquals(CacheOrigin.AUTO_PREVIEW.name, stored.origin)
        assertEquals("the redirector handle is the only source identity stored", "HDL-1", stored.resourceId)
        assertTrue(w.taskDao.listAllActive().single().id == taskId)
    }

    @Test
    fun `keep of the same handle twice does not start a second download`() = runBlocking {
        val w = wiring(coroutineContext, FakeAhead(FetchOutcome.COMPLETED))
        val first = w.repository.keep("HDL-2", "Work", 2000, true)
        assertTrue(first is KeepOutcome.Enqueued)
        (first as KeepOutcome.Enqueued).taskId.let { awaitState(w.taskDao, it, CacheTaskState.COMPLETED) }
        val second = w.repository.keep("HDL-2", "Work", 2000, true)
        assertTrue("second tap must be AlreadyKept, not a new task", second is KeepOutcome.AlreadyKept)
        assertEquals(1, w.taskDao.rows.size)
    }

    // ── (b) StorageGate refusal surfaced honestly, not silently dropped ─────────

    @Test
    fun `keep is refused honestly when the file cannot fit the ceiling`() = runBlocking {
        val tight = FakeStorage(limits = StorageLimits(hardCeilingBytes = 1000, lowStorageFloorBytes = 0, perFileMaxBytes = 100_000))
        val w = wiring(coroutineContext, FakeAhead(FetchOutcome.COMPLETED), storage = tight)
        val outcome = w.repository.keep("HDL-3", "Work", 5000, true)

        assertTrue("must surface NoSpace, not drop silently", outcome is KeepOutcome.NoSpace)
        assertEquals("a refused keep must NOT be inserted into the queue", 0, w.taskDao.rows.size)
    }

    // ── (c) resume uses stored currentUrl + identity digest, not a re-fetch ─────

    @Test
    fun `a rotted source resumes from its identity digest and adopted bytes`() = runBlocking {
        val handle = "HDL-4"
        val sourceKey = KeepIdentity.sourceKeyFor(handle)
        val oldUrl = "https://catalog.test/api/v1/stream?id=$handle"
        val newUrl = "https://catalog.test/api/v1/stream?id=$handle&fresh=1"
        val w = wiring(coroutineContext, FakeAhead(FetchOutcome.NEEDS_RERESOLVE, FetchOutcome.COMPLETED))

        w.taskDao.insertIfAbsent(newTask(handle, id = 100L, state = CacheTaskState.QUEUED, url = oldUrl, downloaded = 400, total = 1000))
        // 400 bytes already verified on disk under this identity
        w.manifestDao.insertAll(listOf(ByteRangeManifestEntity(taskId = 100L, start = 0L, end = 400L, committedElapsedRealtime = 0L)))
        w.resolver.next = ResolvedSource(releaseId = KeepIdentity.KEEP_RELEASE_ID, linkKind = KeepIdentity.KIND_PROGRESSIVE, url = newUrl, resourceId = handle, sizeBytes = 1000)

        w.coordinator.startTask(sourceKey)
        awaitState(w.taskDao, 100L, CacheTaskState.COMPLETED)

        val after = w.taskDao.getBySourceKey(sourceKey)!!
        assertEquals("re-resolve is keyed by the identity digest, never a fresh seed", sourceKey, w.resolver.askedSourceKey)
        assertEquals("resume swaps only the URL, adopting the stored identity", newUrl, after.currentUrl)
        assertEquals(CacheTaskState.COMPLETED.name, after.state)
        assertEquals("the already-held 400 bytes survive the re-resolve (no re-fetch from zero)", 400L, w.manifestDao.committedBytes(100L))
        assertNotNull(w.taskDao.reResolvedUrlSeen)
    }

    @Test
    fun `resolver recovers the opaque handle from our own redirector url`() {
        val decoded = KeepIdentity.handleFromRedirectorUrl("https://catalog.test/api/v1/stream?id=abc%2Fdef")
        assertEquals("the handle is url-decoded back to the exact server string", "abc/def", decoded)
        assertNull("a non-redirector address seeds nothing", KeepIdentity.handleFromRedirectorUrl("https://other-host.example/media.mp4"))
    }

    // ── (d) TTL / auto-delete fires against real store wiring ───────────────────

    @Test
    fun `an aged ephemeral keep is auto-deleted and its list row retired`() = runBlocking {
        val handle = "HDL-5"
        val sourceKey = KeepIdentity.sourceKeyFor(handle)
        val w = wiring(coroutineContext, FakeAhead(FetchOutcome.COMPLETED))
        w.taskDao.insertIfAbsent(newTask(handle, id = 200L, state = CacheTaskState.COMPLETED, url = "x", downloaded = 1000, total = 1000))
        w.fileDao.upsert(
            CacheFileEntity(
                fileId = sourceKey, sourceKey = sourceKey, taskId = 200L, path = "/private/$sourceKey",
                sizeBytes = 1000, origin = CacheOrigin.AUTO_PREVIEW.name, state = CacheTaskState.COMPLETED.name,
                isTemporary = false, isComplete = true, createdElapsedRealtime = 0L, lastAccessElapsedRealtime = 0L,
            )
        )
        val ttl = TtlHours.THREE
        val clock = FixedUptimeClock(ttl.millis + 1)
        val store = RoomCacheSweepStore(w.fileDao, w.taskDao, w.storage, Provider { ttl })

        val result = CacheSweeper(store, clock).sweep()

        assertEquals(listOf(sourceKey), result.expiredDeleted)
        assertTrue("the bytes were removed", w.fileDao.deleted.contains(sourceKey))
        assertEquals("the swept keep leaves the Downloads list", CacheTaskState.DELETED.name, w.taskDao.getById(200L)?.state)
        assertTrue(w.taskDao.listAllActive().isEmpty())
    }

    @Test
    fun `a keep still under a running task is deferred, not deleted`() = runBlocking {
        val handle = "HDL-6"
        val sourceKey = KeepIdentity.sourceKeyFor(handle)
        val w = wiring(coroutineContext, FakeAhead(FetchOutcome.COMPLETED))
        w.taskDao.insertIfAbsent(newTask(handle, id = 300L, state = CacheTaskState.LOADING, url = "x", downloaded = 10, total = 1000))
        w.fileDao.upsert(
            CacheFileEntity(
                fileId = sourceKey, sourceKey = sourceKey, taskId = 300L, path = "/private/$sourceKey",
                sizeBytes = 1000, origin = CacheOrigin.AUTO_PREVIEW.name, state = CacheTaskState.LOADING.name,
                isTemporary = true, isComplete = false, createdElapsedRealtime = 0L, lastAccessElapsedRealtime = 0L,
            )
        )
        val clock = FixedUptimeClock(TtlHours.THREE.millis + 1)
        val store = RoomCacheSweepStore(w.fileDao, w.taskDao, w.storage, Provider { TtlHours.THREE })

        val result = CacheSweeper(store, clock).sweep()

        assertEquals(1, result.deferredHeldByTasks)
        assertTrue(result.expiredDeleted.isEmpty())
        assertEquals(CacheTaskState.LOADING.name, w.taskDao.getById(300L)?.state)
    }

    private companion object {
        const val MAX_EVENT_LOOP_PUMPS = 500
    }
}
