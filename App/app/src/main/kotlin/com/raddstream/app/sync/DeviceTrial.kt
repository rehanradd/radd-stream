package com.raddstream.app.sync

import java.security.MessageDigest

/**
 * DeviceTrial — the pure decisions behind the silent 3-day trial and the phone+PIN link.
 *
 * Like [SyncContract], this file imports nothing from Android, Retrofit, okhttp or Gson. It is
 * the rule half; [SyncAccountRepository] keeps the sockets and DataStore. That split is what
 * lets every number below be tested on this repository's only JVM, and it matters here more
 * than usual because the two features are built on inputs a client makes up:
 *
 *  1. **A device id is a claim, not proof.** The server's own note on `TRIAL_DAYS`
 *     (`Fast_Fetch/accounts.py:236-242`) is that the `device_id` is a string the client reports, an
 *     emulator hands out fresh ones, and nothing in the design attests anything. What the ledger
 *     DOES stop is the ordinary case the owner named: uninstall, reinstall, get another free week.
 *     So a screen may say "this install gets three days once" and may never say "locked to your
 *     device", "verified", or "we know who you are".
 *  2. **The clock is the server's, never this phone's.** [trialAnswer] stores
 *     `trial_seconds_remaining` from the response together with the instant this device read it,
 *     and [secondsRemaining] counts down from that pair. Deriving the countdown from
 *     `trial_expires_at` and a wall clock would make a viewer whose phone runs a day fast see a
 *     day less, and a device with no time at all see nothing.
 *  3. **A minted key is shown or it is gone.** `grant_or_resume_device_trial` can hand back a
 *     plaintext key twice — on a first sight (`created`) and when the account a trial row pointed
 *     at was revoked or pruned (`reissued`) — and never a third time. A silent first-launch mint
 *     therefore has to promise a reveal, or the app has created an account whose only credential
 *     nobody can ever read again.
 *  4. **The server's bounds are the grammar.** Everything in [nameError], [phoneError] and
 *     [pinError] mirrors `accounts._check_profile_name` / `_normalize_phone` / `_check_pin`
 *     exactly. Checking a shape the server does not accept is a wrong refusal; accepting a shape
 *     it will reject is a round trip that, for a PIN, charges the viewer's own attempt bucket.
 *  5. **A wrong PIN is not a dead key.** `PINMismatch` is 401 with code `unauthorised`
 *     (`accounts.py:433-442`), which is byte-identical to the answer a bad bearer produces
 *     everywhere else in this API — but on `profile-link` a bad bearer answers **404**
 *     (`accounts.authenticate` raises `UnknownAccount`). [profileLinkVerdict] is the one place
 *     that distinction is written down, and it exists because applying [SyncContract.verdictOf]
 *     here would sign a viewer out of their account for typing four wrong digits.
 */

/** What `POST api/v2/account/anonymous` did, in the app's own vocabulary. */
sealed class DeviceTrialOutcome {
    /**
     * A trial is running or was resumed. [keyToReveal] is non-null only when this call is the
     * last moment the app will ever have the plaintext, and it is never read back out of storage.
     */
    data class Active(
        val secondsRemaining: Double,
        val newAccount: Boolean,
        val reissued: Boolean,
        val keyToReveal: String? = null,
    ) : DeviceTrialOutcome()

    /** Nothing was started. [reason] is our sentence, never the server's. */
    data class Refused(val reason: TrialRefusal) : DeviceTrialOutcome()
}

/** The three ways a trial does not start, none of which is the viewer's fault. */
enum class TrialRefusal {
    /** No server is connected, so there is nobody to ask. */
    NO_SERVER,

    /** This device could not name itself (no `ANDROID_ID`), so there is nothing to send. */
    NO_DEVICE_ID,

    /** Already signed in with a credential the viewer chose — a trial would not add one. */
    ALREADY_SIGNED_IN,

    /** The answer arrived but could not be read, or the network refused it. */
    UNAVAILABLE,
}

/** What `POST api/v2/account/profile-link` did. */
sealed class ProfileLinkFiled {
    /** Stored. [bonusDayGranted] is the server's `bonus_granted`, not this app's guess. */
    data class Linked(val bonusDayGranted: Boolean, val vipUntil: Double) : ProfileLinkFiled()

    /** Not stored, for a reason this app can say without quoting the server. */
    data class Refused(val reason: LinkRefusal) : ProfileLinkFiled()
}

/** The refusal vocabulary of the link call — see [DeviceTrial.profileLinkVerdict]. */
enum class LinkRefusal {
    /** This install holds no credential, so there is no account to write onto. */
    NOT_SIGNED_IN,

    /** The four digits do not match the ones on file. The key is still good; nothing signed out. */
    WRONG_PIN,

    /** This account's key is dead. The session ends, because it already ended server-side. */
    DEAD_KEY,

    /** The attempt limiter is on this account. Say nothing about which field was wrong. */
    THROTTLED,

    /** A name or phone this server will not store — the field is named, the value is not. */
    BAD_INPUT,

    /** Network, 5xx, an unreadable body. */
    OFFLINE,
}

object DeviceTrial {

    /**
     * Domain separation for the device id. Public by design — it ships in the APK and protects
     * nothing, exactly like [SyncContract.PHONE_KEY_NAMESPACE]. Its only job is to keep this
     * hash from colliding with some other hash of the same three strings.
     */
    const val DEVICE_ID_NAMESPACE = "device-trial/v1"

    /** `accounts.MIN_DEVICE_ID_CHARS` / `MAX_DEVICE_ID_CHARS`. */
    const val MIN_DEVICE_ID_CHARS = 8
    const val MAX_DEVICE_ID_CHARS = 128

    /** `accounts.MIN_PIN_DIGITS` / `MAX_PIN_DIGITS`. */
    const val MIN_PIN_DIGITS = 4
    const val MAX_PIN_DIGITS = 8

    /** `accounts.MIN_PHONE_DIGITS` / `MAX_PHONE_DIGITS`. */
    const val MIN_PHONE_DIGITS = 8
    const val MAX_PHONE_DIGITS = 16

    /** `accounts.MAX_PROFILE_NAME_CHARS`. */
    const val MAX_PROFILE_NAME_CHARS = 60

    /** `accounts.DAY_SECONDS` — only ever used to render days, never to grant one. */
    const val DAY_SECONDS = 86_400.0

    /**
     * The id this install sends to `POST api/v2/account/anonymous`:
     * `SHA-256("<namespace>|<ANDROID_ID>|<HARDWARE>|<FINGERPRINT>")` as 64 lowercase hex
     * characters.
     *
     * Hex, and not the base64url the sync key uses, because the server's device-id grammar is
     * `[A-Za-z0-9._:-]{8,128}` — it has no `~` slot, and a digest that happened to contain one
     * would be a `WeakDeviceId` 400 that this app could not explain. Length and character class
     * are then guaranteed, not hoped for.
     *
     * Null when [androidId] is blank. Two of the three inputs are the same string on every phone
     * of one model, so `ANDROID_ID` is the whole identifier; without it there is no honest id to
     * send and the app must send a blank one rather than a guess. Callers treat null as "do not
     * start a trial", never as an error to show the viewer.
     */
    fun deviceId(androidId: String?, hardware: String?, fingerprint: String?): String? {
        val id = androidId?.trim()?.takeIf { it.isNotEmpty() } ?: return null
        val joined = listOf(DEVICE_ID_NAMESPACE, id, hardware.orEmpty().trim(), fingerprint.orEmpty().trim())
            .joinToString(separator = "|")
        val digest = MessageDigest.getInstance("SHA-256").digest(joined.toByteArray(Charsets.UTF_8))
        return digest.joinToString("") { "%02x".format(it) }
    }

    /**
     * Would this string survive `accounts._check_device_id`? Bounded, no whitespace, and only the
     * characters an installation id actually contains. Checked before the request so a broken
     * build fails here instead of 400-ing on a viewer's phone.
     */
    fun isStorableDeviceId(text: String?): Boolean {
        val trimmed = text?.trim() ?: return false
        if (trimmed.length < MIN_DEVICE_ID_CHARS || trimmed.length > MAX_DEVICE_ID_CHARS) return false
        return trimmed.all {
            it in 'a'..'z' || it in 'A'..'Z' || it in '0'..'9' || it == '.' || it == '_' || it == ':' || it == '-'
        }
    }

    /**
     * The countdown this app shows: the seconds the server said were left, minus the time this
     * device has been running since it heard that answer. Negative elapsed (a clock jumped
     * backwards while the app was closed) counts as no elapsed time rather than as a bonus, and
     * the result never goes below zero — a lapsed trial is 0, not a debt.
     */
    fun secondsRemaining(storedSecondsRemaining: Double, storedAtMs: Long, nowMs: Long): Double {
        if (!storedSecondsRemaining.isFinite() || storedSecondsRemaining <= 0.0) return 0.0
        val elapsedSeconds = (nowMs - storedAtMs).coerceAtLeast(0L) / 1000.0
        return (storedSecondsRemaining - elapsedSeconds).coerceAtLeast(0.0)
    }

    /**
     * Whole days to display, rounding a partial day UP: a trial with 20 hours left is "1 day
     * remaining" to a person deciding whether to link a phone, and "0 days" would read as over.
     * [secondsRemaining] at or below zero is 0, which the UI renders as a finished trial.
     */
    fun daysRemaining(secondsRemaining: Double): Int {
        if (!secondsRemaining.isFinite() || secondsRemaining <= 0.0) return 0
        return ceilDiv(secondsRemaining, DAY_SECONDS)
    }

    /**
     * Read one trial answer into the two numbers this app keeps. Returns null when the body is
     * missing or unusable, which the repository treats as [TrialRefusal.UNAVAILABLE] rather than
     * as a zero-second trial — a 0 stored from a broken response would tell a viewer their free
     * days are gone when nothing was ever granted.
     *
     * A real 0 from the server IS stored, because it means the ledger has an expired trial for this
     * device and that is the whole answer: re-asking every launch would return the same number and
     * buy nothing.
     */
    fun trialAnswer(
        secondsRemaining: Double?,
        syncKey: String?,
        usableKey: (String?) -> Boolean,
    ): StoredTrial? {
        val seconds = secondsRemaining?.takeIf { it.isFinite() && it >= 0.0 } ?: return null
        val key = syncKey?.trim()?.takeIf { it.isNotEmpty() }
        return StoredTrial(
            secondsRemaining = seconds,
            keyToReveal = key?.takeIf { usableKey(it) },
        )
    }

    /** The display name, checked the way the server will check it. Null means "store it". */
    fun nameError(name: String?): String? {
        val text = name?.replace(CONTROL, " ")?.trim()?.replace(ANY_WHITESPACE, " ") ?: return BLANK_NAME
        if (text.isEmpty()) return BLANK_NAME
        if (text.length > MAX_PROFILE_NAME_CHARS) {
            return "That name is longer than the $MAX_PROFILE_NAME_CHARS characters this server stores."
        }
        return null
    }

    /**
     * The phone, checked the way the server checks it: ASCII digits only, counted after every
     * other character is dropped, so `+92 300-1234567` and `03001234567` are both accepted.
     * Deliberately NOT [SyncContract.normalizePakistaniMobile] — that is the login-key grammar,
     * and a viewer with any other number is still allowed to link a profile. Nothing here claims
     * the number is a credential; it is not, the sync key is.
     */
    fun phoneError(phone: String?): String? {
        val digits = phone?.filter { it in '0'..'9' } ?: return BLANK_PHONE
        if (digits.length < MIN_PHONE_DIGITS || digits.length > MAX_PHONE_DIGITS) {
            return "Enter a phone number with $MIN_PHONE_DIGITS to $MAX_PHONE_DIGITS digits."
        }
        return null
    }

    /**
     * The PIN, checked the way the server checks it: `MIN_PIN_DIGITS`..`MAX_PIN_DIGITS` ASCII
     * digits and nothing else. `Char.isDigit()` is not used because it also answers true for `²`
     * and Arabic-Indic `٣`, and the server's `_PIN_RE` is an explicit `[0-9]` class for the same
     * reason — two visually identical PINs must not be two different digests.
     */
    fun pinError(pin: String?): String? {
        val text = pin?.trim() ?: return BLANK_PIN
        if (text.any { it !in '0'..'9' }) {
            return "A PIN must be digits only."
        }
        if (text.length < MIN_PIN_DIGITS || text.length > MAX_PIN_DIGITS) {
            return "A PIN must be $MIN_PIN_DIGITS to $MAX_PIN_DIGITS digits."
        }
        return null
    }

    /**
     * The refusal table for `profile-link` ONLY. [SyncContract.verdictOf] is correct for every
     * other account route and wrong here, because this route has a second 401: a re-link with the
     * wrong four digits. Reading that as `SIGN_OUT` would drop a working key every time somebody
     * mistyped their PIN, and the card would say "signed out" about an account that is fine.
     *
     * So: 401 here means the PIN, 404 here means the key, and a dead key on this route really is a
     * 404 — `accounts.authenticate` raises `UnknownAccount` for a wrong, revoked or never-issued
     * key, and the route only reaches the PIN check after that call returned.
     *
     * The route has a third 401, measured at `accounts_api.py:505`: a request that arrived with no
     * bearer at all gets the same answer a wrong PIN gets. This client cannot produce it, because
     * [SyncAccountRepository.linkProfile] refuses with `NOT_SIGNED_IN` before it opens the socket,
     * and that refusal is why the table may read 401 as the PIN without lying.
     */
    fun profileLinkVerdict(status: Int, code: String?): LinkRefusal = when {
        status == 429 || code == "rate_limited" -> LinkRefusal.THROTTLED
        status == 401 || code == "unauthorised" -> LinkRefusal.WRONG_PIN
        status == 404 || code == "not_found" -> LinkRefusal.DEAD_KEY
        status == 400 || code == "invalid_request" || code == "weak_pin" -> LinkRefusal.BAD_INPUT
        else -> LinkRefusal.OFFLINE
    }

    /** The key-shaped part of a trial answer, before anybody decides where it goes. */
    data class StoredTrial(
        val secondsRemaining: Double,
        val keyToReveal: String?,
    )

    private const val BLANK_NAME = "Add a name to put on this account — it is what the operator's " +
        "queue shows a human, so it cannot be empty."
    private const val BLANK_PHONE = "Enter a phone number."
    private const val BLANK_PIN = "Choose a 4 to 8 digit PIN."

    private val CONTROL = Regex("[\\u0000-\\u001F\\u007F-\\u009F]")
    private val ANY_WHITESPACE = Regex("\\s+")

    /** Integer ceiling without pulling in `kotlin.math.ceil` and a Double→Int round trip. */
    private fun ceilDiv(seconds: Double, daySeconds: Double): Int {
        val whole = (seconds / daySeconds).toLong()
        return if (seconds - whole * daySeconds > 0.0) {
            (whole + 1L).coerceAtMost(Int.MAX_VALUE.toLong()).toInt()
        } else {
            whole.coerceAtMost(Int.MAX_VALUE.toLong()).toInt()
        }
    }
}
