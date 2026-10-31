package com.raddstream.app.network.models

import com.google.gson.annotations.SerializedName

/*
 * ─────────────────────────────────────────────────────────────────────────────
 *  SYNC-ACCOUNT WIRE MODELS — the OPTIONAL cross-device surface.
 * ─────────────────────────────────────────────────────────────────────────────
 * Contract owner is `Fast_Fetch/accounts_api.py`; every shape below is a field-for-field
 * map of what that edge actually serialises, verified against it rather than against a
 * design note:
 *
 *   POST api/v2/account                     -> account{created, created_at, sync_key?}
 *   POST api/v2/account/anonymous           -> account{created, reissued, first_seen_at,
 *                                                      trial_expires_at,
 *                                                      trial_seconds_remaining, vip_until, sync_key?}
 *   POST api/v2/account/profile-link        -> profile{linked, name, phone, bonus_granted, vip_until}
 *   GET  api/v2/account                     -> account{created_at, last_seen_at}
 *   POST api/v2/account/revoke              -> {revoked}
 *   GET  api/v2/account/favorites?limit=n   -> {favorites[], count}
 *   POST api/v2/account/favorites           -> {favorite}
 *   POST api/v2/account/favorites/remove    -> {removed}
 *   GET  api/v2/account/progress?limit=n    -> {progress[], count}
 *   POST api/v2/account/progress            -> {progress}
 *   POST api/v2/account/progress/remove     -> {removed}
 *   POST api/v2/account/payment             -> payment{payment_id, status, plan, amount_pkr, method, submitted_at}
 *   GET  api/v2/account/entitlement         -> entitlement{vip, vip_until, pending}
 *
 * THREE THINGS THESE MODELS ENFORCE, because the server cannot enforce them for us:
 *
 *  1. A work is named by `work_ref` and by nothing else. That handle is minted by the
 *     server and reaches this app only inside a catalog payload; a raw title, a row id
 *     or a `work_key` sent here is refused with a 400 by `_target()`. So every request
 *     body below takes a ref, and nothing in this app can build a ref itself.
 *  2. `sync_key` exists on exactly two responses: the one that mints an account, and the trial
 *     route's reissue when the account a known device pointed at has been revoked or pruned. The
 *     server cannot hand it back a second time for the same account (it stores only a hash), so a
 *     model that looked like it could be refreshed would be a lie.
 *  3. Provenance (App/AGENTS.md, root AGENTS.md): no type here carries a site, hoster or
 *     upstream address, and `code`/`detail` from a refusal are never rendered. A refusal
 *     is answered to the viewer in our own words — the server's `detail` string is not a
 *     user-facing message and is not echoed into the UI or a log.
 *
 * Numbers: the ledger stores SQLite REAL columns, so every timestamp and second count is
 * a `Double` here (`added_at`, `client_updated_at`, `position_seconds`). Modelling them as
 * `Long` would truncate a resume point to a whole second for no reason.
 */

/** Body of POST api/v2/account. An empty object creates; a known key imports it. */
data class AccountCreateRequest(
    @SerializedName("sync_key") val syncKey: String? = null,
)

/** The creation answer. `sync_key` is non-null exactly once, when `created` is true. */
data class AccountCreated(
    val created: Boolean = false,
    @SerializedName("created_at") val createdAt: Double? = null,
    @SerializedName("last_seen_at") val lastSeenAt: Double? = null,
    @SerializedName("sync_key") val syncKey: String? = null,
)

data class AccountCreateResponse(
    val account: AccountCreated? = null,
)

/**
 * Body of POST api/v2/account/anonymous. `device_id` and nothing else, by the server's design:
 * `accounts_api.py:494` says a client that could set its own trial length would be a client that
 * sets its own price, and the same route ignores a body `account_id` rather than refusing it so as
 * not to advertise which field is interesting. There is therefore no field here to add later.
 */
data class DeviceTrialRequest(
    @SerializedName("device_id") val deviceId: String,
)

/**
 * The trial answer. `created` and `reissued` are the two bits that say whether this response is
 * the last moment the plaintext key exists, and `trial_seconds_remaining` is the server's own
 * countdown — the app displays that number and never computes one from a local clock.
 *
 * `trial_expires_at` is carried because the ledger publishes it, and is deliberately unread here:
 * turning it into "days left" would be a subtraction against a wall clock the viewer controls.
 */
data class DeviceTrialGrant(
    val created: Boolean = false,
    val reissued: Boolean = false,
    @SerializedName("first_seen_at") val firstSeenAt: Double = 0.0,
    @SerializedName("trial_expires_at") val trialExpiresAt: Double = 0.0,
    @SerializedName("trial_seconds_remaining") val trialSecondsRemaining: Double? = null,
    @SerializedName("vip_until") val vipUntil: Double = 0.0,
    @SerializedName("sync_key") val syncKey: String? = null,
)

data class DeviceTrialResponse(
    val account: DeviceTrialGrant? = null,
)

/**
 * Body of POST api/v2/account/profile-link — the three values the server stores, and the phone is
 * data, not a credential.
 *
 * There is no `account_id` field, and adding one would change nothing: the route takes the account
 * from the bearer sync key and ignores that field on purpose. There is no `sync_key` field either,
 * because this call is authenticated with it.
 */
data class ProfileLinkRequest(
    @SerializedName("name") val name: String,
    @SerializedName("phone") val phone: String,
    @SerializedName("pin") val pin: String,
)

/**
 * The linked profile, returned to the caller that already proved it holds the key. No hash, no
 * salt, no iteration count: `accounts_api.py:291` refuses to publish them because a wire-tap on
 * this plain-HTTP host could then try PINs offline. `bonus_granted` is the one-day extension, and
 * it is false on every call after the first — the ledger grants it once per account via
 * `linked_at`, which is also why replaying this request is safe.
 */
data class LinkedProfile(
    val linked: Boolean = false,
    @SerializedName("name") val name: String? = null,
    @SerializedName("phone") val phone: String? = null,
    @SerializedName("bonus_granted") val bonusGranted: Boolean = false,
    @SerializedName("vip_until") val vipUntil: Double = 0.0,
)

data class ProfileLinkResponse(
    val profile: LinkedProfile? = null,
)

/** GET api/v2/account — the read-back that proves a stored key still works. */
data class AccountInfo(
    @SerializedName("created_at") val createdAt: Double? = null,
    @SerializedName("last_seen_at") val lastSeenAt: Double? = null,
)

data class AccountInfoResponse(
    val account: AccountInfo? = null,
)

data class RevokedResponse(
    val revoked: Boolean = false,
)

data class RemovedResponse(
    val removed: Boolean = false,
)

/** One saved favorite. There is no title here — the server stores handles, not metadata. */
data class FavoriteEntry(
    @SerializedName("work_ref") val workRef: String? = null,
    @SerializedName("season_number") val seasonNumber: Int = 0,
    @SerializedName("episode_number") val episodeNumber: Int = 0,
    @SerializedName("added_at") val addedAt: Double = 0.0,
)

data class FavoritesResponse(
    val favorites: List<FavoriteEntry> = emptyList(),
    val count: Int = 0,
)

data class FavoriteWriteResponse(
    val favorite: FavoriteEntry? = null,
)

/** Body of both favorite writes. The whole-work scope is season 0, episode 0. */
data class FavoriteRequest(
    @SerializedName("work_ref") val workRef: String,
    @SerializedName("season_number") val seasonNumber: Int = 0,
    @SerializedName("episode_number") val episodeNumber: Int = 0,
)

/** One resume point. `clientUpdatedAt` is the clock this app chose, and the merge key. */
data class ProgressEntry(
    @SerializedName("work_ref") val workRef: String? = null,
    @SerializedName("season_number") val seasonNumber: Int = 0,
    @SerializedName("episode_number") val episodeNumber: Int = 0,
    @SerializedName("position_seconds") val positionSeconds: Double = 0.0,
    @SerializedName("duration_seconds") val durationSeconds: Double = 0.0,
    @SerializedName("client_updated_at") val clientUpdatedAt: Double = 0.0,
    @SerializedName("updated_at") val updatedAt: Double? = null,
)

data class ProgressResponse(
    val progress: List<ProgressEntry> = emptyList(),
    val count: Int = 0,
)

data class ProgressWriteResponse(
    val progress: ProgressEntry? = null,
    /** False when the server kept what it already had: our stamp was not newer. */
    val applied: Boolean? = null,
)

/** Body of both progress writes. Position and duration are seconds, not milliseconds. */
data class ProgressRequest(
    @SerializedName("work_ref") val workRef: String,
    @SerializedName("season_number") val seasonNumber: Int = 0,
    @SerializedName("episode_number") val episodeNumber: Int = 0,
    @SerializedName("position_seconds") val positionSeconds: Double = 0.0,
    @SerializedName("duration_seconds") val durationSeconds: Double = 0.0,
    @SerializedName("client_updated_at") val clientUpdatedAt: Double = 0.0,
)

/**
 * Body of POST api/v2/account/payment — the whole claim a viewer can make.
 *
 * There is no amount field and there must never be one: the server prices the plan
 * itself (`payments.submit_payment` looks the amount up and answers 400 to any body
 * that carries one), so a client cannot negotiate its own membership. `tid` is the
 * transaction reference from the confirmation SMS, sent as one alphanumeric token
 * because the server matches it against the method's shape with no whitespace.
 */
data class PaymentRequest(
    @SerializedName("plan") val plan: String,
    @SerializedName("method") val method: String,
    @SerializedName("tid") val tid: String,
)

/**
 * The receipt a filed claim comes back as. `status` is `pending` — the operator's
 * queue, not a verdict — and the TID is deliberately absent: the response carries
 * every other field of the request and not the one thing a shoulder-surfing screen
 * could read.
 */
data class PaymentReceipt(
    @SerializedName("payment_id") val paymentId: Int = 0,
    val status: String? = null,
    val plan: String? = null,
    @SerializedName("amount_pkr") val amountPkr: Int = 0,
    val method: String? = null,
    @SerializedName("submitted_at") val submittedAt: Double = 0.0,
)

data class PaymentSubmitResponse(
    val payment: PaymentReceipt? = null,
)

/**
 * GET api/v2/account/entitlement — "am I VIP yet?".
 *
 * `vip` is `vip_until > now` on the SERVER's clock, `vip_until` is its expiry in epoch
 * seconds, and `pending` means a claim exists that nobody has closed. Both can be true
 * at once after a late renewal, so a screen that shows one must not hide the other.
 * Nothing here is derived from a rewarded pass: a device-local pass is not a server
 * entitlement and cannot become one by being stored.
 *
 * Named apart from `CatalogV2`'s `Entitlement` on purpose: that one is a catalog row's licence
 * for one work (free or paid, ownership, price), this one is the account's membership over
 * every work. Two different questions under one name would be worse than two names.
 */
data class AccountEntitlement(
    val vip: Boolean = false,
    @SerializedName("vip_until") val vipUntil: Double = 0.0,
    val pending: Boolean = false,
)

data class EntitlementResponse(
    val entitlement: AccountEntitlement? = null,
)

/**
 * The RFC 9457 refusal body (API_V2.md §16.4). Read for `code`, `status` and
 * `retryAfter` only: `detail` is server prose about a handle, never a sentence a
 * viewer is shown, so it is deliberately not exposed past the classifier.
 */
data class AccountProblem(
    val status: Int = 0,
    val code: String? = null,
    val detail: String? = null,
    @SerializedName("retry_after") val retryAfter: Int = 0,
)
