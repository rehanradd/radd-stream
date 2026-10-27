package com.raddstream.app.sync

import com.google.gson.Gson
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.data.local.FavoriteDao
import com.raddstream.app.data.local.SyncedProgressDao
import com.raddstream.app.data.local.SyncedProgressEntity
import com.raddstream.app.di.CacheScope
import com.raddstream.app.network.ApiProvider
import com.raddstream.app.network.RaddStreamApi
import com.raddstream.app.network.bearerHeader
import com.raddstream.app.network.buildRaddGson
import com.raddstream.app.network.models.AccountCreateRequest
import com.raddstream.app.network.models.AccountEntitlement
import com.raddstream.app.network.models.AccountProblem
import com.raddstream.app.network.models.FavoriteEntry
import com.raddstream.app.network.models.FavoriteRequest
import com.raddstream.app.network.models.PaymentReceipt
import com.raddstream.app.network.models.PaymentRequest
import com.raddstream.app.network.models.ProgressEntry
import com.raddstream.app.network.models.ProgressRequest
import java.util.concurrent.atomic.AtomicBoolean
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
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
    @CacheScope private val scope: CoroutineScope,
) {

    /** The stored key. Null means signed out, and every caller below treats that as normal. */
    val syncKey: Flow<String?> = settingsRepository.syncKey

    val signedIn: Flow<Boolean> = settingsRepository.syncKey.map { !it.isNullOrBlank() }

    private val _entitlement = MutableStateFlow<AccountEntitlement?>(null)

    /** Rule 4's session flag: set by the first 429, cleared by a sign-out or a restart. */
    @Volatile
    private var pausedByThrottle: Boolean = false

    private val problemGson: Gson = buildRaddGson()

    /** One position report per [PROGRESS_REPORT_MIN_INTERVAL_MS], shared by all scopes. */
    private val progressThrottle = ProgressThrottle()

    val isPaused: Boolean get() = pausedByThrottle

    init {
        // The last confirmed answer survives a restart. Loading it here means a screen that
        // opens before the launch poll lands already knows what this account may play, and a
        // device in flight mode does not lose a membership the ledger already granted.
        scope.launch {
            if (currentKey() == null || _entitlement.value != null) return@launch
            _entitlement.value = runCatching {
                settingsRepository.storedEntitlement.first()
            }.getOrNull()
        }
    }

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
        clearEntitlement()
        settingsRepository.clearStoredEntitlement()
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
        // Membership rides the same pass as the lists: signing in on a second device should
        // show a VIP the operator already approved, and the throttle below keeps a repeated
        // "Sync now" from asking the same question twice in a minute.
        refreshEntitlement()
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

    // ── paid VIP: the claim, and the answer to "did it land?" ────────────────────

    /**
     * The server's last word on this account's membership, or null when nothing has been
     * read yet. Null is a real state and not a failure: a signed-out device never asks, and
     * a screen that treated "never asked" as "not VIP" would hide a pending claim that the
     * viewer can still see the moment they sign in.
     */
    val entitlement: StateFlow<AccountEntitlement?> = _entitlement.asStateFlow()

    private val startedWatch = AtomicBoolean(false)
    private var lastEntitlementReadMs: Long = 0L

    /**
     * File one claimed payment. The reference never leaves this call as a stored value: the
     * server keeps it in its ledger and the receipt deliberately does not carry it back.
     *
     * A refusal is [Refusal] in our own vocabulary, and which one it is changes what the
     * screen says: `REJECTED` means the plan/method/reference shape the operator's server
     * accepts (a 400 — the viewer typed something that is not a TID), `THROTTLED` means this
     * account already filed inside the server's window (one claim per
     * [ENTITLEMENT_MIN_INTERVAL_MS] is generous next to it), and `SIGNED_OUT` means the key
     * died on the way. A 429 pauses the rest of this session's syncing like any other 429 —
     * that is [SyncContract]'s rule for every route, and a payment-specific exception to it
     * would be a second policy nobody audited.
     *
     * Nothing here retries, and nothing here pretends a filed claim is a purchase: it is
     * `pending` until a human approves it on the operator's own loopback panel.
     */
    suspend fun submitPayment(plan: String, method: String, tid: String): PaymentFiled {
        val key = currentKey() ?: return PaymentFiled.Refused(Refusal.SIGNED_OUT)
        return try {
            val answer = apiProvider.current()
                .submitVipTid(bearerHeader(key), PaymentRequest(plan, method, tid))
            val receipt = answer.payment
            if (receipt == null || receipt.paymentId <= 0) {
                // A 201 we cannot read is not a filing; the viewer must not be told to wait
                // for an approval that has no row behind it.
                return PaymentFiled.Refused(Refusal.REJECTED)
            }
            refreshEntitlement(force = true)
            PaymentFiled.Accepted(receipt)
        } catch (error: Exception) {
            when (verdictOf(error, hadWorkRef = false)) {
                ServerVerdict.SIGN_OUT -> {
                    signOutLocally()
                    PaymentFiled.Refused(Refusal.SIGNED_OUT)
                }
                ServerVerdict.PAUSE_SESSION -> {
                    pausedByThrottle = true
                    PaymentFiled.Refused(Refusal.THROTTLED)
                }
                ServerVerdict.REJECT_ITEM -> PaymentFiled.Refused(Refusal.REJECTED)
                ServerVerdict.TRANSIENT_FAILURE -> PaymentFiled.Refused(Refusal.OFFLINE)
            }
        }
    }

    /**
     * GET api/v2/account/entitlement — the only call that can turn "paid" into "VIP".
     *
     * A signed-out device never asks (that would be a 401 burst against a key that does not
     * exist), and a read younger than [ENTITLEMENT_MIN_INTERVAL_MS] is answered from the last
     * one unless [force]. Failure keeps the previous value rather than clearing it: a viewer
     * whose membership was confirmed does not lose VIP because a flight mode was on, and the
     * app never treats "could not ask" as "not entitled".
     */
    suspend fun refreshEntitlement(force: Boolean = false): AccountEntitlement? {
        val key = currentKey() ?: return null
        val now = System.currentTimeMillis()
        if (!force && now - lastEntitlementReadMs < ENTITLEMENT_MIN_INTERVAL_MS) return _entitlement.value
        return try {
            val read = apiProvider.current().getEntitlement(bearerHeader(key)).entitlement
            if (read != null) {
                lastEntitlementReadMs = now
                _entitlement.value = read
                // Mirror the server's answer so the next cold start has it before any network
                // call can fail. The ledger remains the only authority; this is its cache.
                settingsRepository.saveEntitlement(read)
            }
            read
        } catch (error: Exception) {
            when (verdictOf(error, hadWorkRef = false)) {
                ServerVerdict.SIGN_OUT -> {
                    signOutLocally()
                    _entitlement.value = null
                    null
                }
                ServerVerdict.PAUSE_SESSION -> {
                    pausedByThrottle = true
                    _entitlement.value
                }
                else -> _entitlement.value
            }
        }
    }

    /**
     * The 6-hour poll the monetization spec asks for. Started once by the Application on the
     * app-lifetime [CacheScope], like every other holder in this app: it asks once at launch
     * and then on the interval, and it stops when the process does — no worker, no alarm, no
     * background job. An app that was closed simply re-reads on the next launch, which is why
     * the deadline itself lives on the server and not in a counter here.
     */
    fun startEntitlementWatch() {
        if (!startedWatch.compareAndSet(false, true)) return
        scope.launch {
            while (isActive) {
                if (currentKey() != null) refreshEntitlement()
                delay(ENTITLEMENT_POLL_INTERVAL_MS)
            }
        }
    }

    /** Forget the membership the moment the credential that produced it is gone. */
    private fun clearEntitlement() {
        _entitlement.value = null
        lastEntitlementReadMs = 0L
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

        /** How often the app asks the server about membership while it is alive: 6 hours,
         * the cadence the monetization spec names. A launch always asks once, immediately. */
        const val ENTITLEMENT_POLL_INTERVAL_MS = 6L * 60L * 60L * 1000L

        /** Two reads closer than this are one read. Opening the VIP card repeatedly is not a
         * reason to send the same question to the server twice in a minute. */
        const val ENTITLEMENT_MIN_INTERVAL_MS = 60L * 1000L
    }
}

/** What a payment submission did, in the screen's own vocabulary. */
sealed class PaymentFiled {
    /** Filed. The receipt is the server's row: `status` is `pending` and the price is the
     * server's, not the one the device displayed. */
    data class Accepted(val receipt: PaymentReceipt) : PaymentFiled()

    /** Not filed, for a reason this app can say without quoting the server. */
    data class Refused(val reason: Refusal) : PaymentFiled()
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
