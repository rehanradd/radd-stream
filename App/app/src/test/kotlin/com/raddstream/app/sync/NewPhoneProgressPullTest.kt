package com.raddstream.app.sync

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.data.local.AppDatabase
import com.raddstream.app.data.local.SyncedProgressEntity
import com.raddstream.app.network.ApiProvider
import java.io.ByteArrayOutputStream
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketException
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.ConcurrentLinkedQueue
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * D2.1 — the new-phone progress pull, proven end to end instead of asserted in prose.
 *
 * The pull already existed (`SettingsViewModel.quickSignIn()` calls `syncNow()` on success,
 * and `syncNow()` folds `listProgress` into the `SyncedProgress` mirror, server-wins by
 * timestamp); what was missing was the proof. This file is that proof, against a fake
 * server that speaks the same wire shape as `accounts_api.py`:
 *
 *  1. Device A signs in (the fake server mints the key) and reports a position.
 *  2. Device B — a fresh in-memory Room database, zero local history — signs in with the
 *     same key and pulls.
 *  3. `resumePositionMs` on device B returns the exact millisecond device A reported.
 *
 * The fake is a hand-rolled HTTP/1.1 server on a plain `ServerSocket`, not a mock: the
 * real Retrofit client, the real Gson wire models and the real Room DAOs all run, so a
 * snake_case drift or a merge-rule regression fails here instead of on a viewer's second
 * phone. It is hand-rolled on purpose: `com.sun.net.httpserver` lives in the `jdk.httpserver`
 * module, which the unit-test compile classpath does not resolve (CI red on 42323050286),
 * and adding a MockWebServer dependency for one test would be the heavier change.
 * x86_64-only like every Robolectric suite (see the arm64 exclusion in `app/build.gradle.kts`).
 */
@RunWith(RobolectricTestRunner::class)
class NewPhoneProgressPullTest {

    /** One stored row on the fake server: the fields `listProgress` answers. */
    private data class StoredProgress(
        val workRef: String,
        val season: Int,
        val episode: Int,
        val positionSeconds: Double,
        val durationSeconds: Double,
        val clientUpdatedAt: Double,
    )

    /** The fake server's whole state: bearer key -> that account's progress rows. */
    private val serverProgress = ConcurrentHashMap<String, MutableList<StoredProgress>>()

    /** What the fake server saw and suffered, in order — printed into failure messages. */
    private val serverEvents = ConcurrentLinkedQueue<String>()

    private lateinit var server: FakeSyncServer
    private lateinit var settings: ServerSettingsRepository
    private lateinit var apiProvider: ApiProvider
    private val databases = mutableListOf<AppDatabase>()

    @Before
    fun setUp() = runBlocking {
        server = FakeSyncServer(::handleRequest, serverEvents::add).apply { start() }
        val context = ApplicationProvider.getApplicationContext<Context>()
        settings = ServerSettingsRepository(context)
        settings.saveServerUrl("http://127.0.0.1:${server.port}/")
        apiProvider = ApiProvider(settings)
    }

    @After
    fun tearDown() {
        databases.forEach { it.close() }
        if (::server.isInitialized) server.stop()
    }

    /** One device: its own Room mirror, sharing the account server with the other device. */
    private fun device(): Pair<SyncAccountRepository, AppDatabase> {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val db = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java).build()
        databases += db
        val repo = SyncAccountRepository(
            apiProvider = apiProvider,
            settingsRepository = settings,
            favoriteDao = db.favoriteDao(),
            unavailableDao = db.unavailableWorkDao(),
            syncedProgressDao = db.syncedProgressDao(),
            scope = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined),
        )
        return repo to db
    }

    @Test
    fun `a fresh device pulls progress on quick sign-in and resumes at the exact millisecond`() =
        runBlocking {
            val (deviceA, _) = device()
            val signedIn = deviceA.createAccount()
            assertTrue("device A must mint an account", signedIn is AccountMutation.SignedIn)
            val key = (signedIn as AccountMutation.SignedIn).revealedKey
            assertTrue("the minted key must be usable", SyncContract.isUsableSyncKey(key))

            deviceA.reportProgress(
                workRef = WORK_REF,
                season = SEASON,
                episode = EPISODE,
                positionMs = POSITION_MS,
                durationMs = DURATION_MS,
                forced = true,
            )
            assertEquals(
                "device A must resume where it stopped",
                POSITION_MS,
                deviceA.resumePositionMs(WORK_REF, SEASON, EPISODE),
            )

            // Device B: a fresh install — its own empty Room, no local history at all.
            val (deviceB, dbB) = device()
            assertNull(
                "a fresh device knows nothing before it signs in",
                deviceB.resumePositionMs(WORK_REF, SEASON, EPISODE),
            )
            val joined = deviceB.quickSignIn(key!!)
            assertTrue(
                "quickSignIn answered $joined; server saw: ${serverEvents.joinToString(" | ")}",
                joined is AccountMutation.SignedIn,
            )
            val report = deviceB.syncNow()
            assertTrue(
                "syncNow completed=${report.completed} pulled=${report.progressRowsPulled}; " +
                    "server saw: ${serverEvents.joinToString(" | ")}",
                report.completed,
            )
            assertEquals("one row must arrive", 1, report.progressRowsPulled)
            val mirrorRow = dbB.syncedProgressDao().find(WORK_REF, SEASON, EPISODE)
            val serverRow = serverProgress[key]!!.single()
            assertEquals(
                "device B must resume at device A's exact millisecond; " +
                    "mirror=$mirrorRow server=$serverRow",
                POSITION_MS,
                deviceB.resumePositionMs(WORK_REF, SEASON, EPISODE),
            )
        }

    @Test
    fun `a second sync pulls nothing twice`() = runBlocking {
        val (deviceA, _) = device()
        val key = (deviceA.createAccount() as AccountMutation.SignedIn).revealedKey!!
        deviceA.reportProgress(WORK_REF, SEASON, EPISODE, POSITION_MS, DURATION_MS, forced = true)

        val (deviceB, dbB) = device()
        deviceB.quickSignIn(key)
        val firstPull = deviceB.syncNow()
        assertEquals(
            "first pull pulled=${firstPull.progressRowsPulled} completed=${firstPull.completed}; " +
                "server saw: ${serverEvents.joinToString(" | ")}",
            1,
            firstPull.progressRowsPulled,
        )
        val second = deviceB.syncNow()
        assertTrue(second.completed)
        assertEquals("the same stamp must not count as a new pull", 0, second.progressRowsPulled)
        val mirrorRow = dbB.syncedProgressDao().find(WORK_REF, SEASON, EPISODE)
        assertEquals(
            "resume must read the pulled row; mirror=$mirrorRow",
            POSITION_MS,
            deviceB.resumePositionMs(WORK_REF, SEASON, EPISODE),
        )
    }

    @Test
    fun `a stale server row never overwrites a newer local row`() = runBlocking {
        val (deviceA, _) = device()
        val key = (deviceA.createAccount() as AccountMutation.SignedIn).revealedKey!!
        deviceA.reportProgress(WORK_REF, SEASON, EPISODE, POSITION_MS, DURATION_MS, forced = true)
        val serverStamp = serverProgress[key]!!.single().clientUpdatedAt

        // Device B watched further while offline: its mirror holds a newer stamp, seeded
        // directly because the server must never see it for this case to mean anything.
        val (deviceB, dbB) = device()
        val newerMs = 200_000L
        dbB.syncedProgressDao().put(
            SyncedProgressEntity(
                workRef = WORK_REF,
                seasonNumber = SEASON,
                episodeNumber = EPISODE,
                positionSeconds = newerMs / 1000.0,
                durationSeconds = DURATION_MS / 1000.0,
                clientUpdatedAt = serverStamp + 1000.0,
            ),
        )
        val seeded = dbB.syncedProgressDao().find(WORK_REF, SEASON, EPISODE)
        deviceB.quickSignIn(key)
        val report = deviceB.syncNow()
        assertTrue(
            "syncNow completed=${report.completed} pulled=${report.progressRowsPulled}; " +
                "server saw: ${serverEvents.joinToString(" | ")}",
            report.completed,
        )
        assertEquals(
            "the stale row must not count as pulled; seeded=$seeded " +
                "server=${serverProgress[key]!!.single()}",
            0,
            report.progressRowsPulled,
        )
        assertEquals(
            "the newer local position must survive the pull",
            newerMs,
            deviceB.resumePositionMs(WORK_REF, SEASON, EPISODE),
        )
    }

    // ── the fake server's routes ─────────────────────────────────────────────────

    /** Dispatch one parsed request. Returns the status and the JSON body to answer. */
    private fun handleRequest(
        method: String,
        path: String,
        headers: Map<String, String>,
        body: String,
    ): Pair<Int, String> = when {
        path == "/api/v2/account" -> handleAccount(method, body)
        path == "/api/v2/account/entitlement" ->
            200 to """{"entitlement":{"vip":false,"vip_until":0.0,"pending":false}}"""
        path == "/api/v2/account/favorites" -> 200 to """{"favorites":[],"count":0}"""
        path == "/api/v2/account/progress" -> handleProgress(method, headers, body)
        else -> 404 to """{"code":"not_found"}"""
    }

    private fun handleAccount(method: String, body: String): Pair<Int, String> {
        if (method == "POST") {
            val presented = Regex(""""sync_key"\s*:\s*"([^"]+)"""").find(body)?.groupValues?.get(1)
            if (presented.isNullOrBlank()) {
                // A fresh mint: the one moment the plaintext key exists.
                return 200 to """{"account":{"created":true,"sync_key":"$MINTED_KEY"}}"""
            }
            // An import: the server recognises the key and never repeats it.
            return 200 to """{"account":{"created":false}}"""
        }
        return 200 to """{"account":{"created_at":0.0,"last_seen_at":0.0}}"""
    }

    private fun handleProgress(
        method: String,
        headers: Map<String, String>,
        body: String,
    ): Pair<Int, String> {
        val key = headers["authorization"]?.removePrefix("Bearer ")?.trim().orEmpty()
        if (key.isEmpty()) return 401 to """{"code":"unauthorized"}"""
        if (method == "GET") {
            val rows = serverProgress[key].orEmpty().joinToString(",") { row ->
                """{"work_ref":"${row.workRef}","season_number":${row.season},""" +
                    """"episode_number":${row.episode},"position_seconds":${row.positionSeconds},""" +
                    """"duration_seconds":${row.durationSeconds},""" +
                    """"client_updated_at":${row.clientUpdatedAt}}"""
            }
            return 200 to """{"progress":[$rows],"count":${serverProgress[key].orEmpty().size}}"""
        }
        if (method == "POST") {
            val row = StoredProgress(
                workRef = stringField(body, "work_ref"),
                season = numberField(body, "season_number").toInt(),
                episode = numberField(body, "episode_number").toInt(),
                positionSeconds = numberField(body, "position_seconds"),
                durationSeconds = numberField(body, "duration_seconds"),
                clientUpdatedAt = numberField(body, "client_updated_at"),
            )
            // Newest-wins, like the real route: an older write is ignored, not rejected.
            val rows = serverProgress.getOrPut(key) { mutableListOf() }
            val existing = rows.indexOfFirst {
                it.workRef == row.workRef && it.season == row.season && it.episode == row.episode
            }
            if (existing < 0 || row.clientUpdatedAt > rows[existing].clientUpdatedAt) {
                if (existing >= 0) rows[existing] = row else rows += row
            }
            return 200 to
                """{"progress":{"work_ref":"${row.workRef}","season_number":${row.season},""" +
                """"episode_number":${row.episode},"position_seconds":${row.positionSeconds},""" +
                """"duration_seconds":${row.durationSeconds},""" +
                """"client_updated_at":${row.clientUpdatedAt}},"applied":true,"coins_earned":0}"""
        }
        return 404 to """{"code":"not_found"}"""
    }

    private fun stringField(body: String, name: String): String =
        Regex(""""$name"\s*:\s*"([^"]*)"""").find(body)?.groupValues?.get(1).orEmpty()

    private fun numberField(body: String, name: String): Double =
        // Gson writes large doubles in scientific notation (client_updated_at ~1.79E9),
        // so the exponent is part of the number, not the end of it.
        Regex(""""$name"\s*:\s*(-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)"""")
            .find(body)?.groupValues?.get(1)?.toDouble() ?: 0.0

    companion object {
        /** The key the fake server mints: 16 url-safe characters, like the real floor. */
        const val MINTED_KEY = "d2testkey1234567"
        const val WORK_REF = "d2-progress-pull-work"
        const val SEASON = 1
        const val EPISODE = 2
        const val POSITION_MS = 123_456L
        const val DURATION_MS = 600_000L
    }
}

/**
 * A minimal HTTP/1.1 server on a plain `ServerSocket`: one request per connection,
 * `Connection: close`, bodies read by `Content-Length`. Only what OkHttp needs here —
 * a request line, headers and a small JSON body — and nothing more. All threads are
 * daemon, so a test that forgets to stop it still ends.
 */
private class FakeSyncServer(
    private val handler: (method: String, path: String, headers: Map<String, String>, body: String) -> Pair<Int, String>,
    private val onEvent: (String) -> Unit,
) {
    private val socket = ServerSocket(0, 50, InetAddress.getByName("127.0.0.1"))

    val port: Int get() = socket.localPort

    fun start() {
        Thread({
            while (!socket.isClosed) {
                try {
                    val connection = socket.accept()
                    Thread({ handle(connection) }, "fake-sync-conn").apply {
                        isDaemon = true
                        start()
                    }
                } catch (error: SocketException) {
                    if (!socket.isClosed) onEvent("accept SocketException: $error")
                    break
                } catch (error: Exception) {
                    // A transient accept failure must not kill the server: log it and
                    // keep listening, so one bad handshake cannot fail every later test.
                    onEvent("accept ${error.javaClass.simpleName}: $error")
                }
            }
        }, "fake-sync-accept").apply {
            isDaemon = true
            start()
        }
    }

    fun stop() {
        socket.close()
    }

    private fun handle(connection: Socket) {
        try {
            serve(connection)
        } catch (error: Exception) {
            onEvent("handle ${error.javaClass.simpleName}: $error")
        }
    }

    private fun serve(connection: Socket) {
        connection.use { socket ->
            val input = socket.getInputStream()
            val head = ByteArrayOutputStream()
            // Read byte by byte until the blank line that ends the headers.
            var tail = 0
            while (true) {
                val byte = input.read()
                if (byte < 0) return
                head.write(byte)
                tail = (tail shl 8) or byte
                if (tail == 0x0D0A0D0A) break
            }
            val lines = head.toString(Charsets.UTF_8).split("\r\n")
            val requestLine = lines.firstOrNull()?.split(" ") ?: return
            if (requestLine.size < 2) return
            val headers = lines.drop(1)
                .mapNotNull { line ->
                    val colon = line.indexOf(':')
                    if (colon < 0) null else line.take(colon).trim().lowercase() to
                        line.drop(colon + 1).trim()
                }.toMap()
            val length = headers["content-length"]?.toIntOrNull() ?: 0
            val bodyBytes = ByteArray(length)
            var read = 0
            while (read < length) {
                val count = input.read(bodyBytes, read, length - read)
                if (count < 0) break
                read += count
            }
            val (status, json) = handler(
                requestLine[0],
                // Retrofit appends ?limit=1000 to the list routes; the query is not
                // part of the route, and matching on it 404s every list call.
                requestLine[1].substringBefore("?"),
                headers,
                bodyBytes.decodeToString(),
            )
            onEvent("${requestLine[0]} ${requestLine[1]} -> $status")
            val body = json.toByteArray(Charsets.UTF_8)
            val reason = when (status) {
                200 -> "OK"
                401 -> "Unauthorized"
                else -> "Not Found"
            }
            socket.getOutputStream().write(
                ("HTTP/1.1 $status $reason\r\nContent-Type: application/json\r\n" +
                    "Content-Length: ${body.size}\r\nConnection: close\r\n\r\n")
                    .toByteArray(Charsets.UTF_8),
            )
            socket.getOutputStream().write(body)
            socket.getOutputStream().flush()
        }
    }
}
