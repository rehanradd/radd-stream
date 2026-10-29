package com.raddstream.app.sync

/**
 * SyncContract — the pure decisions behind the optional sync account.
 *
 * This file holds every rule that can be argued about, so that the class next to it
 * ([SyncAccountRepository]) holds nothing but sockets, DataStore and Room. Nothing here
 * imports Android, Retrofit, okhttp or Gson: each rule is a function of values, which is
 * what makes it testable on a JVM with no device (`SyncContractTest`), and what keeps a
 * merge decision from being buried in a `try` block that a network blip skips over.
 *
 * The rules, and why each one is the shape it is:
 *
 *  1. **A work is named by a minted handle or not at all.** [canNameOnServer] is the gate
 *     in front of every write. A raw title, a catalog row id or a work key sent to the
 *     account surface is refused by the server with a 400 — and it must be, because a work
 *     key can contain a source-site name, which is the one thing this project never lets
 *     cross the edge. So a favorite with no handle stays on the device, and no amount of
 *     guessing on this side makes it syncable.
 *  2. **A refusal says one of four things.** [verdictOf] maps an HTTP status plus the RFC
 *     9457 `code` onto sign-out, a session pause, a rejected item, or a plain failure. Two
 *     of those are load-bearing and are the reason this is a table rather than an `if`.
 *  3. **A 401 signs this device out and never retries.** The key is the whole credential;
 *     the server cannot be asked to accept it again by asking harder. Retrying a 401 is
 *     how a stale key turns one viewer's mistake into a brute-force lockout on the shared
 *     attempt tracker, which locks the account even though the key was never wrong.
 *  4. **A 429 stops this session.** `Locked` is raised by the failure-count window, so the
 *     only polite answer is to stop presenting the key until the app is restarted. The
 *     server sends `retry_after`, but a resume point is worth nothing for fifteen minutes
 *     and a scheduled retry needs a work manager, which is not worth one dependency.
 *  5. **A 404 means different things on the two kinds of call.** With a handle in the body
 *     it is `UnknownWork` — that one work is invisible or gone, and the account is fine.
 *     Without one it is `UnknownAccount` — the key itself is dead (revoked, or the row was
 *     pruned), and staying "signed in" against a dead key is a lie the UI would keep telling.
 *  6. **Newest wins, and the client's clock is the only honest clock.** For progress the
 *     comparison is `client_updated_at`, per the server's own staleness rule; a tie keeps
 *     the row already stored, because a tie is not newer than itself. For favorites the
 *     merge is additive: a pull never deletes a local row (see [favoritePlan] for why).
 *  7. **Nothing here may name a source.** No value this file returns is a display string,
 *     and the server's `detail` text never leaves [SyncFailure] — it is a sentence about a
 *     handle, not a message for a viewer.
 */

/** The four answers a refusal can force, named so a caller cannot mix them up. */
enum class ServerVerdict {
    /** The key is not usable any more: drop it locally and return to signed-out behaviour. */
    SIGN_OUT,

    /** The server is throttling this key: stop syncing until the app process restarts. */
    PAUSE_SESSION,

    /** One item was refused (unknown work, bad params, a full library). Keep it local. */
    REJECT_ITEM,

    /** Anything else — network, 5xx, a body we could not read. Keep it local, say nothing. */
    TRANSIENT_FAILURE,
}

/** What one best-effort write did, so the caller can log nothing and still decide. */
enum class SyncAck {
    /** The server accepted it. */
    WRITTEN,

    /** No handle for this work — the write was not even attempted (rule 1). */
    NOT_NAMABLE,

    /** Signed out, paused by a 429, or refused: the local write already happened anyway. */
    SKIPPED,
}

/** A favorite as the account surface describes it: a handle, a scope, a timestamp. */
data class ServerFavorite(
    val workRef: String,
    val season: Int,
    val episode: Int,
    val addedAt: Double,
)

/** A resume point as the account surface describes it. Seconds throughout, as stored. */
data class ServerProgress(
    val workRef: String,
    val season: Int,
    val episode: Int,
    val positionSeconds: Double,
    val durationSeconds: Double,
    val clientUpdatedAt: Double,
)

/** The local half of a favorite merge, projected so the rule needs no Room types. */
data class LocalFavorite(
    val postId: Int,
    val workRef: String?,
    val syncedAt: Long?,
)

/**
 * What one sync pass did, in the four numbers the account card may show. Every count is
 * of rows, never of titles: the app cannot name a server row, so it could not tell a
 * viewer which title a number refers to even if it wanted to.
 */
data class SyncReport(
    val favoritesPushed: Int = 0,
    val progressRowsPulled: Int = 0,
    /** Server favorites this device has no row for. Reported, not silently dropped. */
    val favoritesUnknownHere: Int = 0,
    /** Local favorites this app could not name to the server because no handle arrived. */
    val favoritesUnnamable: Int = 0,
    /** True when the pass completed both reads; false when it stopped at a refusal. */
    val completed: Boolean = false,
)

object SyncContract {

    /** Mirrors `accounts.MIN_SYNC_KEY_CHARS` / `MAX_SYNC_KEY_CHARS`. */
    const val MIN_SYNC_KEY_CHARS = 16
    const val MAX_SYNC_KEY_CHARS = 256

    /** The length the server mints and the card calls a "16-character Sync Key". */
    const val SHORT_SYNC_KEY_CHARS = 16

    /**
     * The length earlier server releases minted (`token_urlsafe(32)`). Accepted unchanged so
     * a viewer who wrote one down keeps their library; not advertised on the card.
     */
    const val LEGACY_SYNC_KEY_CHARS = 43

    /**
     * How much of a self-typed account label the card can paint. A label is display data, so the
     * cap is a layout limit and nothing else — it is not a credential band, and unlike the key
     * above it is not mirrored from the server, which never receives one.
     */
    const val MAX_LABEL_CHARS = 32

    /** Rule 1: only a non-blank minted handle may go on the wire. */
    fun canNameOnServer(workRef: String?): Boolean = !workRef.isNullOrBlank()

    /**
     * Shape a pasted key must satisfy before it is worth a request, mirroring
     * `accounts._check_sync_key_shape`: the same length band, the same ban on whitespace,
     * control characters and the two characters that would break a header value. Checking
     * it here costs nothing and turns an obvious typo into an instant message instead of a
     * 400 that also counts, on the server, as a failed attempt against that key.
     */
    fun isUsableSyncKey(text: String?): Boolean {
        val trimmed = text?.trim() ?: return false
        if (trimmed.length < MIN_SYNC_KEY_CHARS || trimmed.length > MAX_SYNC_KEY_CHARS) return false
        return trimmed.none { it.code < 33 || it.code == 127 || it == '"' || it == '\\' }
    }

    /** A key for the screen: never the whole thing, so a screenshot is not a credential. */
    fun keyPreview(syncKey: String?): String {
        val key = syncKey?.takeIf { it.isNotBlank() } ?: return ""
        return if (key.length <= 12) key else "${key.take(6)}…${key.takeLast(4)}"
    }

    /**
     * A Pakistani mobile number as the account card accepts it: `03XXXXXXXXX`,
     * `3XXXXXXXXX`, `+923XXXXXXXXX`, `923XXXXXXXXX` or `00923XXXXXXXXX`, with spaces,
     * dashes or brackets. Returns the canonical `03XXXXXXXXX` form, or null when the
     * input is not a complete Pakistani mobile number.
     *
     * This is a display rule and nothing else. It exists so a label a viewer typed once reads
     * the same on every row of the card; it is NOT a step on any path to a credential. See
     * [accountLabel] for what a number is allowed to become, and [quickLoginKey] for the only
     * thing this screen will send to the server.
     */
    fun normalizePakistaniMobile(raw: String?): String? {
        val compact = raw?.trim()?.replace(Regex("[\\s()\\-]"), "") ?: return null
        if (compact.isEmpty()) return null
        val digits = compact.removePrefix("+")
        if (digits.isEmpty() || digits.any { !it.isDigit() }) return null
        val national = when {
            digits.startsWith("0092") -> digits.substring(4)
            digits.startsWith("92") -> digits.substring(2)
            digits.startsWith("0") -> digits.substring(1)
            else -> digits
        }
        if (national.length != 10 || national[0] != '3') return null
        return "0$national"
    }

    /**
     * A key exactly as the server mints it: sixteen characters from the URL-safe alphabet.
     * Case is preserved. The key IS the credential, so folding case would silently change
     * which account it opens — and throw away entropy while doing it.
     */
    fun isShortSyncKey(raw: String?): Boolean {
        val text = raw?.trim() ?: return false
        if (text.length != SHORT_SYNC_KEY_CHARS) return false
        return text.all {
            it in 'A'..'Z' || it in 'a'..'z' || it in '0'..'9' || it == '-' || it == '_'
        }
    }

    /**
     * The credential to send for a sign-in the viewer typed themselves: a key this server (or
     * an older release of it) minted, presented unchanged.
     *
     *  - the server's 16 characters, or the 43-character key older releases minted → that key
     *    exactly. Re-deriving a credential the viewer already has would open a different, empty
     *    library, so a key is never normalized, re-hashed or case-folded on its way here.
     *  - anything else, including a mobile number → null. A number is not a credential and this
     *    build derives nothing from one. It used to: `base64url(SHA-256("phone-sync/v1|…"))[:16]`
     *    turned the whole Pakistani mobile space into a password that anyone could compute
     *    offline, and `POST /api/v2/account` would happily reopen the account a presented key
     *    names. That derivation is deleted, not disabled — see [accountLabel] for the one thing
     *    a number may now become, and `tooling/PhoneCredentialGuardTest` for the build-breaking
     *    refusal that keeps it from coming back.
     *
     * A near-miss key (a character dropped or added) is refused here rather than sent, because
     * the server creates a NEW empty library for any well-shaped key it has never seen; the
     * honest typo answer is a message, not a blank list.
     */
    fun quickLoginKey(raw: String?): String? {
        val text = raw?.trim() ?: return null
        if (isShortSyncKey(text)) return text
        if (text.length == LEGACY_SYNC_KEY_CHARS && isUsableSyncKey(text)) return text
        return null
    }

    fun isQuickLoginInput(raw: String?): Boolean = quickLoginKey(raw) != null

    /**
     * What the viewer typed about themselves, as display data: canonicalized when it is a
     * Pakistani mobile number, kept as written otherwise, trimmed, and capped at a length a
     * card row can actually paint. Null means "no label".
     *
     * The result is stored in this app's own preferences, painted on the account card, and sent
     * to no endpoint. It is deliberately NOT an input to [quickLoginKey] or to anything else
     * that decides whether a request is allowed: a number is public, guessable information about
     * a person, and the whole point of this function is that it is the only place one goes.
     */
    fun accountLabel(raw: String?): String? {
        val text = raw?.trim()?.takeIf { it.isNotEmpty() } ?: return null
        return (normalizePakistaniMobile(text) ?: text).take(MAX_LABEL_CHARS)
    }

    /**
     * Rule 2: the refusal table. [hadWorkRef] says whether the call named a work, which is
     * what tells a dead key (sign out) from an invisible title (keep it local) — both are
     * 404 with code `not_found`, and reading them as one would either wipe a viewer's
     * session over one dead row or keep a dead key forever.
     */
    fun verdictOf(status: Int, code: String?, hadWorkRef: Boolean): ServerVerdict = when {
        status == 401 || code == "unauthorised" -> ServerVerdict.SIGN_OUT
        status == 410 || code == "gone" -> ServerVerdict.SIGN_OUT
        status == 429 || code == "rate_limited" -> ServerVerdict.PAUSE_SESSION
        status == 404 && !hadWorkRef -> ServerVerdict.SIGN_OUT
        status == 404 || status == 400 || status == 403 || status == 409 -> ServerVerdict.REJECT_ITEM
        else -> ServerVerdict.TRANSIENT_FAILURE
    }

    /**
     * Rule 6 for progress: does the incoming server row beat the row on this device?
     *
     * Strictly newer wins. Equality keeps what is already stored, which is the server's own
     * tie rule restated on this side — and it matters here for a second reason: a pull that
     * rewrote an unchanged row on every sync would make the mirror look freshly written
     * forever and hide the fact that nothing actually moved.
     */
    fun serverProgressWins(incomingClientUpdatedAt: Double, storedClientUpdatedAt: Double): Boolean =
        incomingClientUpdatedAt > storedClientUpdatedAt

    /**
     * A resume position worth offering at all: positive, and not the whole file. A row at
     * or beyond the end means the viewer finished it, and resuming a finished file restarts
     * nothing — it just hides the play button behind a prompt to resume from the end.
     */
    fun resumablePositionMs(positionSeconds: Double, durationSeconds: Double): Long? {
        if (!positionSeconds.isFinite() || positionSeconds <= 0.0) return null
        if (durationSeconds.isFinite() && durationSeconds > 0.0 &&
            positionSeconds >= durationSeconds
        ) {
            return null
        }
        val ms = positionSeconds * 1000.0
        if (!ms.isFinite() || ms < 1_000.0) return null
        return ms.toLong()
    }

    /**
     * Rule 6 for favorites: which local rows still need writing.
     *
     * The merge is deliberately ONE-DIRECTIONAL on deletion. A server favorite absent here
     * is counted, a local favorite absent there is kept, and nothing in this pass deletes a
     * saved title for anybody. Two reasons, both real:
     *  - the list route is capped (1000 rows asked, `accounts.MAX_FAVORITES` is 5000), so a
     *    truncated read looks exactly like a library where those titles were un-saved; and
     *  - a title this app could not name (no handle) is invisible to the server by
     *    definition, so absence there is the expected state of the device, not an edit.
     * Removals do propagate — immediately, on the tap that made them.
     */
    fun favoritePlan(local: List<LocalFavorite>, server: List<ServerFavorite>): FavoritePlan {
        val serverRefs = server.map { it.workRef }.toSet()
        val localRefs = local.mapNotNull { it.workRef?.takeIf(String::isNotBlank) }.toSet()
        val needsWriting = local.filter { row ->
            val ref = row.workRef?.takeIf { it.isNotBlank() } ?: return@filter false
            // Un-stamped (never confirmed on a library) or absent from the list it should be in.
            row.syncedAt == null || ref !in serverRefs
        }
        return FavoritePlan(
            needsWriting = needsWriting,
            unknownHere = server.count { it.workRef !in localRefs },
            unnammable = local.count { !canNameOnServer(it.workRef) },
        )
    }
}

/** Output of [SyncContract.favoritePlan]. Counts and rows, no decisions left inside. */
data class FavoritePlan(
    val needsWriting: List<LocalFavorite>,
    val unknownHere: Int,
    val unnammable: Int,
)

/**
 * Rule 4's other half: how often a playing app may talk about its position.
 *
 * A resume point changes every frame, so an unthrottled reporter would turn one evening of
 * viewing into thousands of authenticated requests against a one-CPU box — and each failure
 * counts toward the server's brute-force window, so the spam would eventually lock the
 * viewer out of their own account. [take] therefore allows one report per [minIntervalMs] and
 * nothing else, [isDue] is the same question without the side effect (the tick loop asks it
 * twice a second), and [forceNow] is the separate door the player uses on pause and on
 * teardown, where the position genuinely matters and the next tick may never come.
 */
class ProgressThrottle(
    val minIntervalMs: Long = PROGRESS_REPORT_MIN_INTERVAL_MS,
    private val clockMs: () -> Long = { System.currentTimeMillis() },
) {
    private var lastFiredAt: Long? = null

    /**
     * The cheap, NON-mutating question, for a caller that asks twice a second: is the next
     * report allowed yet? Reading is free and changes nothing, so a tick that is not due
     * costs no coroutine and no request; only [take] moves the clock.
     */
    fun isDue(): Boolean {
        val last = lastFiredAt ?: return true
        return clockMs() - last >= minIntervalMs
    }

    /** True (and records the firing) when enough time has passed since the last report. */
    fun take(): Boolean {
        if (!isDue()) return false
        lastFiredAt = clockMs()
        return true
    }

    /**
     * Take a report the clock would not have allowed — a stop or a pause, where the position
     * matters and the next tick may never come — and start the wait again from now, so a
     * forced report is never followed by an instant second one.
     */
    fun forceNow() {
        lastFiredAt = clockMs()
    }

    fun reset() {
        lastFiredAt = null
    }
}

/**
 * The mandate's number: at most one position report per fifteen seconds. A resume point
 * changes every frame, so an unthrottled reporter would turn one evening of viewing into
 * thousands of authenticated requests against a one-CPU box — and every failure counts
 * toward the server's brute-force window, so the spam would eventually lock the viewer out
 * of the account they were trying to keep current.
 */
const val PROGRESS_REPORT_MIN_INTERVAL_MS = 15_000L
