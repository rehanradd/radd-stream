package com.raddstream.app.sync

import com.google.gson.Gson
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.data.local.FavoriteDao
import com.raddstream.app.data.local.SyncedProgressDao
import com.raddstream.app.data.local.SyncedProgressEntity
import com.raddstream.app.network.ApiProvider
import com.raddstream.app.network.RaddStreamApi
import com.raddstream.app.network.bearerHeader
import com.raddstream.app.network.buildRaddGson
import com.raddstream.app.network.models.AccountCreateRequest
import com.raddstream.app.network.models.AccountProblem
import com.raddstream.app.network.models.FavoriteEntry
import com.raddstream.app.network.models.FavoriteRequest
import com.raddstream.app.network.models.ProgressEntry
import com.raddstream.app.network.models.ProgressRequest
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import retrofit2.HttpException

/** The outcome of the two calls that mint or adopt a key, in the UI's vocabulary. */
sealed class AccountMutation {
    /** Signed in. [revealedKey] is non-null only when the server just minted this key. */
    data class SignedIn(val revealedKey: String? = null) : AccountMutation()

    /** Nothing changed. [reason] is our own sentence, never the server's. */
    data class Refused(val reason: Refusal) : AccountMutation()
}

/** Our fixed vocabulary for a refusal — the server's text is never a user-facing string. */
enum class Refusal { NO_SERVER, WEAK_KEY, REJECTED, THROTTLED, OFFLINE, SIGNED_OUT }

/**
 * The single owner of the optional sync account.
 *
 * WHAT THIS CLASS IS FOR: one place that knows the key, one place that decides what a
 * status code means, and one place that may touch the account routes. Everything else in
 * the app asks it for a best-effort write and gets a [SyncAck] back. That shape is the
 * point: a favorite tap must never fail because a network is down, so by the time this
 * class is called the local write has ALREADY happened, and it still stands when every
 * call in here returns [SyncAck.SKIPPED].
 *
 * WHAT IT NEVER DOES:
 *  - send anything but a minted `workRef`. A title, a row id or a work key cannot be built
 *    from these parameters, so a caller cannot leak one by accident;
 *  - retry. A 401 signs this device out and a 429 pauses the rest of the session — see
 *    [SyncContract], whose rules are the only decisions made in this file. Nothing here
 *    schedules a second attempt, because the server counts failures per key and a retrying
 *    client is how a viewer locks themselves out of the list they were trying to save;
 *  - log or display a key, a handle, or a server `detail`. The plaintext is handed back
 *    exactly once, in [AccountMutation.SignedIn], for the one screen that mints it.
 *
 * The key lives in the app's private DataStore beside the server URL
 * ([ServerSettingsRepository.syncKey]) — the same file as everything else the user typed
 * into this app, which is to say: as safe as the device, and sent over plain HTTP.
 */
@Singleton
class SyncAccountRepository @Inject constructor(
    private val apiProvider: ApiProvider,
    private val settingsRepository: ServerSettingsRepository,
    private val favoriteDao: FavoriteDao,
    private val syncedProgressDao: SyncedProgressDao,
) {

    /** The stored key. Null means signed out, and every caller below treats that as normal. */
    val syncKey: Flow<String?> = settingsRepository.syncKey

    val signedIn: Flow<Boolean> = settingsRepository.syncKey.map { !it.isNullOrBlank() }

    /** Rule 4's session flag: set by the first 429, cleared by a sign-out or a restart. */
    @Volatile
    private var pausedByThrottle: Boolean = false

    private val problemGson: Gson = buildRaddGson()

    /** One position report per [PROGRESS_REPORT_MIN_INTERVAL_MS], shared by all scopes. */
    private val progressThrottle = ProgressThrottle()

    val isPaused: Boolean get() = pausedByThrottle

    // ── account lifecycle ────────────────────────────────────────────────────────

    /** POST api/v2/account with an empty body — the one call that mints a key. */
    suspend fun createAccount(): AccountMutation = try {
        val answer = apiProvider.current().createAccount(AccountCreateRequest()).account
        val minted = answer?.syncKey?.trim()?.takeIf { it.isNotEmpty() }
        if (minted == null || !SyncContract.isUsableSyncKey(minted)) {
            // A 201 without a usable key is not a partial success, it is a broken answer.
            AccountMutation.Refused(Refusal.REJECTED)
        } else {
            settingsRepository.saveSyncKey(minted)
            AccountMutation.SignedIn(revealedKey = minted)
        }
    } catch (error: Exception) {
        refusalOf(error, hadWorkRef = false)
    }

    /**
     * One tap: sign in with a Pakistani mobile number or a key the viewer already holds.
     *
     * A mobile number is normalized and derived into a 16-character credential on this
     * device (see [SyncContract.quickLoginKey]); the number itself never leaves the phone.
     * A 16-character server-minted key, or an older longer key, is sent unchanged — that is
     * what makes the same key open the same library on a second device. The card's honest
     * warning about a number's small entropy lives in the screen, not in this call.
     *
     * POST api/v2/account with the key in the body answers `created: false` for a key this
     * server already knows, and opens a library around one it does not. A typo long enough
     * to pass the shape check therefore opens a NEW empty library rather than failing, so
     * the card says to check the number or key instead of promising a not-found answer.
     */
    suspend fun quickSignIn(input: String): AccountMutation {
        val key = SyncContract.quickLoginKey(input)
            ?: return AccountMutation.Refused(Refusal.WEAK_KEY)
        return try {
            val answer = apiProvider.current().createAccount(AccountCreateRequest(syncKey = key)).account
            val stored = answer?.syncKey?.trim()?.takeIf { it.isNotEmpty() } ?: key
            settingsRepository.saveSyncKey(stored)
            // Nothing to reveal: the viewer supplied the credential (or the number it is
            // derived from), and can do so again on any device. Minting a fresh random key
            // is the separate "Create account" door, and that is the only reveal path.
            AccountMutation.SignedIn(revealedKey = null)
        } catch (error: Exception) {
            refusalOf(error, hadWorkRef = false)
        }
    }

    /**
     * GET api/v2/account — the read-back that proves a stored key still names a live
     * account. A 404 here is [Refusal.SIGNED_OUT]: the key was revoked or the idle row was
     * pruned, and a card that kept saying "signed in" over a dead credential would be
     * lying, so the local key is dropped as part of answering.
     */
    suspend fun verify(): AccountMutation {
        val key = currentKey() ?: return AccountMutation.Refused(Refusal.SIGNED_OUT)
        return try {
            apiProvider.current().getAccount(bearerHeader(key))
            AccountMutation.SignedIn(revealedKey = null)
        } catch (error: Exception) {
            when (verdictOf(error, hadWorkRef = false)) {
                ServerVerdict.SIGN_OUT -> {
                    signOutLocally()
                    AccountMutation.Refused(Refusal.SIGNED_OUT)
                }
                ServerVerdict.PAUSE_SESSION -> {
                    pausedByThrottle = true
                    AccountMutation.Refused(Refusal.THROTTLED)
                }
                ServerVerdict.REJECT_ITEM -> AccountMutation.Refused(Refusal.REJECTED)
                ServerVerdict.TRANSIENT_FAILURE -> AccountMutation.Refused(Refusal.OFFLINE)
            }
        }
    }

    /**
     * "Sign out (revokes the key)". The remote revoke is best effort and its failure changes
     * nothing about the local half: the key is dropped, the pulled mirror is dropped, and the
     * app behaves exactly as it did before an account existed.
     */
    suspend fun signOut() {
        val key = currentKey()
        if (key != null) {
            try {
                apiProvider.current().revokeAccount(bearerHeader(key))
            } catch (_: Exception) {
                // A revoke that did not land leaves the key working elsewhere for now.
                // This device has forgotten it either way, which is what the button promised.
            }
        }
        signOutLocally()
    }

    /**
     * Forget the credential WITHOUT asking the server — the path a 401 or a dead-key 404
     * takes, because asking a server that just refused this key to please accept it again is
     * exactly the retry this class is not allowed to make.
     */
    private suspend fun signOutLocally() {
        pausedByThrottle = false
        progressThrottle.reset()
        syncedProgressDao.clear()
        settingsRepository.saveSyncKey(null)
    }

    // ── best-effort writes, each called AFTER the local write already happened ─────

    /** Add one favorite. The handle is the whole API surface for "which title". */
    suspend fun pushFavorite(workRef: String?): SyncAck {
        val ref = workRef?.takeIf { it.isNotBlank() } ?: return SyncAck.NOT_NAMABLE
        return attempt(hadWorkRef = true) { api, auth ->
            api.addFavorite(auth, FavoriteRequest(workRef = ref))
        }
    }

    /** Remove one favorite. A refusal cannot un-remove it locally, and does not try to. */
    suspend fun removeRemoteFavorite(workRef: String?): SyncAck {
        val ref = workRef?.takeIf { it.isNotBlank() } ?: return SyncAck.NOT_NAMABLE
        return attempt(hadWorkRef = true) { api, auth ->
            api.removeFavorite(auth, FavoriteRequest(workRef = ref))
        }
    }

    /**
     * The tick loop's cheap question: may a position report be attempted right now? It never
     * suspends, never takes the throttle slot and never builds a request, so a player that
     * asks twice a second costs nothing. [reportProgress] is the only consumer of the slot.
     */
    fun progressReportDue(): Boolean = !pausedByThrottle && progressThrottle.isDue()

    /**
     * Report where viewing stopped. Throttled to one call per
     * [PROGRESS_REPORT_MIN_INTERVAL_MS] unless [forced] — a pause or a teardown, where the
     * position is the one thing worth a request and the next tick may never come. The player
     * that owns the tick loop is the reason this throttle exists; nothing here is called per
     * frame.
     */
    suspend fun reportProgress(
        workRef: String?,
        season: Int,
        episode: Int,
        positionMs: Long,
        durationMs: Long,
        forced: Boolean = false,
    ): SyncAck {
        val ref = workRef?.takeIf { it.isNotBlank() } ?: return SyncAck.NOT_NAMABLE
        if (pausedByThrottle) return SyncAck.SKIPPED
        if (forced) progressThrottle.forceNow() else if (!progressThrottle.take()) return SyncAck.SKIPPED
        val positionSeconds = positionMs.coerceAtLeast(0L) / 1000.0
        val durationSeconds = durationMs.coerceAtLeast(0L) / 1000.0
        val stamp = System.currentTimeMillis() / 1000.0
        val ack = attempt(hadWorkRef = true) { api, auth ->
            api.putProgress(
                auth,
                ProgressRequest(
                    workRef = ref,
                    seasonNumber = season,
                    episodeNumber = episode,
                    positionSeconds = positionSeconds,
                    durationSeconds = durationSeconds,
                    clientUpdatedAt = stamp,
                ),
            )
        }
        // Fold our own report into the mirror at once, so this device resumes from where
        // this device stopped without waiting for a pull to agree with it.
        if (ack == SyncAck.WRITTEN && positionSeconds > 0.0) {
            syncedProgressDao.put(
                SyncedProgressEntity(
                    workRef = ref,
                    seasonNumber = season,
                    episodeNumber = episode,
                    positionSeconds = positionSeconds,
                    durationSeconds = durationSeconds,
                    clientUpdatedAt = stamp,
                ),
            )
        }
        return ack
    }

    /** "Sync now": read both lists, write what the library is missing, fold in what it has. */
    suspend fun syncNow(): SyncReport {
        if (currentKey() == null || pausedByThrottle) return SyncReport()
        return try {
            val api = apiProvider.current()
            val auth = bearerHeader(currentKey())
            val remoteFavorites = api.listFavorites(auth).favorites
            val remoteProgress = api.listProgress(auth).progress
            val local = favoriteDao.favoritesOnce().map { row ->
                LocalFavorite(postId = row.id, workRef = row.workRef, syncedAt = row.syncedAt)
            }
            val plan = SyncContract.favoritePlan(local = local, server = remoteFavorites.asServerList())

            var pushed = 0
            for (row in plan.needsWriting.take(MAX_WRITES_PER_PASS)) {
                val ref = row.workRef ?: continue
                val ack = attempt(hadWorkRef = true) { api2, auth2 ->
                    api2.addFavorite(auth2, FavoriteRequest(workRef = ref))
                }
                if (ack == SyncAck.WRITTEN) {
                    favoriteDao.markSynced(row.postId, System.currentTimeMillis())
                    pushed++
                } else {
                    // A pause or a sign-out mid-pass stops the rest of it.
                    break
                }
            }

            var pulled = 0
            for (entry in remoteProgress) {
                val ref = entry.workRef?.takeIf { it.isNotBlank() } ?: continue
                if (mergeProgress(ref, entry)) pulled++
            }

            SyncReport(
                favoritesPushed = pushed,
                progressRowsPulled = pulled,
                favoritesUnknownHere = plan.unknownHere,
                favoritesUnnamable = plan.unnammable,
                completed = true,
            )
        } catch (error: Exception) {
            when (verdictOf(error, hadWorkRef = false)) {
                ServerVerdict.SIGN_OUT -> {
                    signOutLocally()
                    SyncReport()
                }
                ServerVerdict.PAUSE_SESSION -> {
                    pausedByThrottle = true
                    SyncReport()
                }
                else -> SyncReport()
            }
        }
    }

    /** The pulled resume point for one scope, in milliseconds, or null = nothing known. */
    suspend fun resumePositionMs(workRef: String?, season: Int, episode: Int): Long? {
        val ref = workRef?.takeIf { it.isNotBlank() } ?: return null
        if (pausedByThrottle) return null
        val row = syncedProgressDao.find(ref, season, episode) ?: return null
        return SyncContract.resumablePositionMs(row.positionSeconds, row.durationSeconds)
    }

    /** Backfill a handle for a saved row, once the catalog finally names that work. */
    suspend fun adoptWorkRef(postId: Int, workRef: String?) {
        val ref = workRef?.takeIf { it.isNotBlank() } ?: return
        val row = favoriteDao.findById(postId) ?: return
        if (row.workRef == ref) return
        favoriteDao.updateWorkRef(postId, ref)
    }

    // ── the plumbing every call shares ───────────────────────────────────────────

    /** Signed-out and throttled calls never reach the network; every refusal is classified. */
    private suspend fun attempt(
        hadWorkRef: Boolean,
        call: suspend (RaddStreamApi, String?) -> Any?,
    ): SyncAck {
        val key = currentKey() ?: return SyncAck.SKIPPED
        if (pausedByThrottle) return SyncAck.SKIPPED
        return try {
            call(apiProvider.current(), bearerHeader(key))
            SyncAck.WRITTEN
        } catch (error: Exception) {
            when (verdictOf(error, hadWorkRef)) {
                ServerVerdict.SIGN_OUT -> {
                    signOutLocally()
                    SyncAck.SKIPPED
                }
                ServerVerdict.PAUSE_SESSION -> {
                    pausedByThrottle = true
                    SyncAck.SKIPPED
                }
                ServerVerdict.REJECT_ITEM, ServerVerdict.TRANSIENT_FAILURE -> SyncAck.SKIPPED
            }
        }
    }

    /** Newest-wins fold of one server row into the mirror. True when the mirror moved. */
    private suspend fun mergeProgress(workRef: String, entry: ProgressEntry): Boolean {
        val stored = syncedProgressDao.find(workRef, entry.seasonNumber, entry.episodeNumber)
        if (stored != null &&
            !SyncContract.serverProgressWins(entry.clientUpdatedAt, stored.clientUpdatedAt)
        ) {
            return false
        }
        syncedProgressDao.put(
            SyncedProgressEntity(
                workRef = workRef,
                seasonNumber = entry.seasonNumber,
                episodeNumber = entry.episodeNumber,
                positionSeconds = entry.positionSeconds,
                durationSeconds = entry.durationSeconds,
                clientUpdatedAt = entry.clientUpdatedAt,
            ),
        )
        return true
    }

    private fun refusalOf(error: Exception, hadWorkRef: Boolean): AccountMutation =
        when (verdictOf(error, hadWorkRef)) {
            ServerVerdict.PAUSE_SESSION -> AccountMutation.Refused(Refusal.THROTTLED)
            ServerVerdict.SIGN_OUT, ServerVerdict.REJECT_ITEM -> AccountMutation.Refused(Refusal.REJECTED)
            ServerVerdict.TRANSIENT_FAILURE -> AccountMutation.Refused(
                if (error is HttpException) Refusal.REJECTED else Refusal.OFFLINE,
            )
        }

    private fun verdictOf(error: Exception, hadWorkRef: Boolean): ServerVerdict {
        if (error is HttpException) {
            return SyncContract.verdictOf(error.code(), parseProblem(error)?.code, hadWorkRef)
        }
        return ServerVerdict.TRANSIENT_FAILURE
    }

    /** Read the RFC 9457 body for `code` and nothing else. `detail` is dropped, not stored. */
    private fun parseProblem(failure: HttpException): AccountProblem? = try {
        val body = failure.response()?.errorBody()?.string()
        if (body.isNullOrEmpty()) null else problemGson.fromJson(body, AccountProblem::class.java)
    } catch (_: Exception) {
        null
    }

    private suspend fun currentKey(): String? = syncKey.first()?.takeIf { it.isNotBlank() }

    companion object {
        /** One pass writes at most this many favorites: a first sync of a long list must not
         * turn into a burst that trips the server's own attempt window. */
        const val MAX_WRITES_PER_PASS = 50
    }
}

/** The server's favorite rows, filtered to the ones this app is allowed to talk about. */
private fun List<FavoriteEntry>.asServerList(): List<ServerFavorite> =
    mapNotNull { entry ->
        entry.workRef?.takeIf { it.isNotBlank() }?.let {
            ServerFavorite(
                workRef = it,
                season = entry.seasonNumber,
                episode = entry.episodeNumber,
                addedAt = entry.addedAt,
            )
        }
    }
