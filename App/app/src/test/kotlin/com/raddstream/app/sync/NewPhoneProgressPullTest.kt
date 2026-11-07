package com.raddstream.app.sync

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.data.local.AppDatabase
import com.raddstream.app.data.local.SyncedProgressEntity
import com.raddstream.app.network.ApiProvider
import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import java.util.concurrent.ConcurrentHashMap
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
 * The fake is a JDK `HttpServer`, not a mock: the real Retrofit client, the real Gson
 * wire models and the real Room DAOs all run, so a snake_case drift or a merge-rule
 * regression fails here instead of on a viewer's second phone. x86_64-only like every
 * Robolectric suite (see the arm64 exclusion in `app/build.gradle.kts`).
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

    private lateinit var server: HttpServer
    private lateinit var settings: ServerSettingsRepository
    private lateinit var apiProvider: ApiProvider
    private val databases = mutableListOf<AppDatabase>()

    @Before
    fun setUp() = runBlocking {
        server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/api/v2/account") { exchange -> handleAccount(exchange) }
        server.createContext("/api/v2/account/entitlement") { exchange ->
            respond(exchange, 200, """{"entitlement":{"vip":false,"vip_until":0.0,"pending":false}}""")
        }
        server.createContext("/api/v2/account/favorites") { exchange ->
            respond(exchange, 200, """{"favorites":[],"count":0}""")
        }
        server.createContext("/api/v2/account/progress") { exchange -> handleProgress(exchange) }
        server.start()
        val context = ApplicationProvider.getApplicationContext<Context>()
        settings = ServerSettingsRepository(context)
        settings.saveServerUrl("http://127.0.0.1:${server.address.port}/")
        apiProvider = ApiProvider(settings)
    }

    @After
    fun tearDown() {
        databases.forEach { it.close() }
        if (::server.isInitialized) server.stop(0)
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
            val (deviceB, _) = device()
            assertNull(
                "a fresh device knows nothing before it signs in",
                deviceB.resumePositionMs(WORK_REF, SEASON, EPISODE),
            )
            val joined = deviceB.quickSignIn(key!!)
            assertTrue("the same key must open the same library", joined is AccountMutation.SignedIn)
            val report = deviceB.syncNow()
            assertTrue("the pull must complete", report.completed)
            assertEquals("one row must arrive", 1, report.progressRowsPulled)
            assertEquals(
                "device B must resume at device A's exact millisecond",
                POSITION_MS,
                deviceB.resumePositionMs(WORK_REF, SEASON, EPISODE),
            )
        }

    @Test
    fun `a second sync pulls nothing twice`() = runBlocking {
        val (deviceA, _) = device()
        val key = (deviceA.createAccount() as AccountMutation.SignedIn).revealedKey!!
        deviceA.reportProgress(WORK_REF, SEASON, EPISODE, POSITION_MS, DURATION_MS, forced = true)

        val (deviceB, _) = device()
        deviceB.quickSignIn(key)
        assertEquals(1, deviceB.syncNow().progressRowsPulled)
        val second = deviceB.syncNow()
        assertTrue(second.completed)
        assertEquals("the same stamp must not count as a new pull", 0, second.progressRowsPulled)
        assertEquals(POSITION_MS, deviceB.resumePositionMs(WORK_REF, SEASON, EPISODE))
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
        deviceB.quickSignIn(key)
        val report = deviceB.syncNow()
        assertTrue(report.completed)
        assertEquals("the stale row must not count as pulled", 0, report.progressRowsPulled)
        assertEquals(
            "the newer local position must survive the pull",
            newerMs,
            deviceB.resumePositionMs(WORK_REF, SEASON, EPISODE),
        )
    }

    // ── the fake server ──────────────────────────────────────────────────────────

    private fun handleAccount(exchange: HttpExchange) {
        if (exchange.requestMethod == "POST") {
            val body = exchange.requestBody.readAllBytes().decodeToString()
            val presented = Regex(""""sync_key"\s*:\s*"([^"]+)"""").find(body)?.groupValues?.get(1)
            if (presented.isNullOrBlank()) {
                // A fresh mint: the one moment the plaintext key exists.
                respond(
                    exchange,
                    200,
                    """{"account":{"created":true,"sync_key":"$MINTED_KEY"}}""",
                )
            } else {
                // An import: the server recognises the key and never repeats it.
                respond(exchange, 200, """{"account":{"created":false}}""")
            }
        } else {
            respond(exchange, 200, """{"account":{"created_at":0.0,"last_seen_at":0.0}}""")
        }
    }

    private fun handleProgress(exchange: HttpExchange) {
        val key = exchange.requestHeaders.getFirst("Authorization")
            ?.removePrefix("Bearer ")?.trim().orEmpty()
        if (key.isEmpty()) {
            respond(exchange, 401, """{"code":"unauthorized"}""")
            return
        }
        if (exchange.requestMethod == "GET") {
            val rows = serverProgress[key].orEmpty().joinToString(",") { row ->
                """{"work_ref":"${row.workRef}","season_number":${row.season},""" +
                    """"episode_number":${row.episode},"position_seconds":${row.positionSeconds},""" +
                    """"duration_seconds":${row.durationSeconds},""" +
                    """"client_updated_at":${row.clientUpdatedAt}}"""
            }
            respond(exchange, 200, """{"progress":[$rows],"count":${serverProgress[key].orEmpty().size}}""")
            return
        }
        if (exchange.requestMethod == "POST") {
            val body = exchange.requestBody.readAllBytes().decodeToString()
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
            respond(
                exchange,
                200,
                """{"progress":{"work_ref":"${row.workRef}","season_number":${row.season},""" +
                    """"episode_number":${row.episode},"position_seconds":${row.positionSeconds},""" +
                    """"duration_seconds":${row.durationSeconds},""" +
                    """"client_updated_at":${row.clientUpdatedAt}},"applied":true,"coins_earned":0}""",
            )
            return
        }
        respond(exchange, 404, """{"code":"not_found"}""")
    }

    private fun stringField(body: String, name: String): String =
        Regex(""""$name"\s*:\s*"([^"]*)"""").find(body)?.groupValues?.get(1).orEmpty()

    private fun numberField(body: String, name: String): Double =
        // Gson writes large doubles in scientific notation (client_updated_at ~1.79E9),
        // so the exponent is part of the number, not the end of it.
        Regex(""""$name"\s*:\s*(-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)"""")
            .find(body)?.groupValues?.get(1)?.toDouble() ?: 0.0

    private fun respond(exchange: HttpExchange, status: Int, json: String) {
        val bytes = json.toByteArray(Charsets.UTF_8)
        exchange.responseHeaders.set("Content-Type", "application/json")
        exchange.sendResponseHeaders(status, bytes.size.toLong())
        exchange.responseBody.use { it.write(bytes) }
    }

    companion object {
        /** The key the fake server mints: 16 url-safe characters, like the real floor. */
        const val MINTED_KEY = "d2testkey12345678"
        const val WORK_REF = "d2-progress-pull-work"
        const val SEASON = 1
        const val EPISODE = 2
        const val POSITION_MS = 123_456L
        const val DURATION_MS = 600_000L
    }
}
