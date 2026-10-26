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
 *   GET  api/v2/account                     -> account{created_at, last_seen_at}
 *   POST api/v2/account/revoke              -> {revoked}
 *   GET  api/v2/account/favorites?limit=n   -> {favorites[], count}
 *   POST api/v2/account/favorites           -> {favorite}
 *   POST api/v2/account/favorites/remove    -> {removed}
 *   GET  api/v2/account/progress?limit=n    -> {progress[], count}
 *   POST api/v2/account/progress            -> {progress}
 *   POST api/v2/account/progress/remove     -> {removed}
 *
 * THREE THINGS THESE MODELS ENFORCE, because the server cannot enforce them for us:
 *
 *  1. A work is named by `work_ref` and by nothing else. That handle is minted by the
 *     server and reaches this app only inside a catalog payload; a raw title, a row id
 *     or a `work_key` sent here is refused with a 400 by `_target()`. So every request
 *     body below takes a ref, and nothing in this app can build a ref itself.
 *  2. `sync_key` exists on exactly one response: the creation answer. The server cannot
 *     hand it back a second time (it stores only a hash), so a model that looked like it
 *     could be refreshed would be a lie.
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
