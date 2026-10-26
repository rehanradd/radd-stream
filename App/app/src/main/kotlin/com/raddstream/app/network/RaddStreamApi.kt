package com.raddstream.app.network

import com.raddstream.app.network.models.AccountCreateRequest
import com.raddstream.app.network.models.AccountCreateResponse
import com.raddstream.app.network.models.AccountInfoResponse
import com.raddstream.app.network.models.FavoriteRequest
import com.raddstream.app.network.models.FavoriteWriteResponse
import com.raddstream.app.network.models.FavoritesResponse
import com.raddstream.app.network.models.PostDetailResponse
import com.raddstream.app.network.models.PostsResponse
import com.raddstream.app.network.models.ProgressRequest
import com.raddstream.app.network.models.ProgressResponse
import com.raddstream.app.network.models.ProgressWriteResponse
import com.raddstream.app.network.models.RemovedResponse
import com.raddstream.app.network.models.RevokedResponse
import com.raddstream.app.network.models.StatsResponse
import com.raddstream.app.network.models.StreamResponse
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

/**
 * How many rows a list route is asked for. The server default is 200 and its ceiling is
 * 1000 (`accounts_api._limit`), and a sync that imported 200 of a 600-title library
 * would look like a success while quietly dropping four hundred — so ask for the ceiling.
 */
const val ACCOUNT_LIST_LIMIT = 1000

/** The only bearer form this edge reads: `Authorization: Bearer <sync key>`, null if empty. */
fun bearerHeader(syncKey: String?): String? =
    syncKey?.trim()?.takeIf { it.isNotEmpty() }?.let { "Bearer $it" }

/**
 * Retrofit interface mirroring the radd-stream REST API v1, plus the OPTIONAL v2
 * sync-account surface.
 * Base URL is configured at runtime from DataStore (user's server URL).
 *
 * HOW THE SYNC KEY TRAVELS: every account call takes it as an explicit
 * `@Header("Authorization")` argument instead of getting an authenticating interceptor,
 * precisely so [com.raddstream.app.network.ApiProvider] can keep installing nothing
 * (see its KDoc). Nothing is added to a request the caller did not ask for — and a
 * signed-out caller passes `null`, which Retrofit omits, so the four v1 routes and the
 * signed-out app are untouched by anything below this line.
 *
 * The key goes out as a header value on plain HTTP: the deployed server has no TLS, so
 * this is convenience over confidentiality, and the account screen says so out loud.
 */
interface RaddStreamApi {

    /** GET /api/v1/posts — paginated metadata catalog with optional search + type filter. */
    @GET("api/v1/posts")
    suspend fun getPosts(
        @Query("q") query: String? = null,
        @Query("type") type: String? = null,
        @Query("page") page: Int = 1,
        @Query("limit") limit: Int = 20,
    ): PostsResponse

    /** GET /api/v1/posts/{id} — post details with all releases and sources. */
    @GET("api/v1/posts/{id}")
    suspend fun getPostDetail(
        @Path("id") id: Int,
    ): PostDetailResponse

    /**
     * GET /api/v1/stream — our OWN redirector, asked about one opaque handle.
     *
     * `redirect=0` answers metadata only (`stream_id`, `kind`, `mime_type`, `file_size_bytes`,
     * `resumable`, `expires_in`) and never a location; playback does not need this call at all,
     * because Media3 follows the 302 of `redirect=1` itself. It exists to learn whether a handle
     * is resumable/ephemeral before offering it for keeping.
     */
    @GET("api/v1/stream")
    suspend fun resolveStream(
        @Query("id") streamId: String,
        @Query("redirect") redirect: String = "0",
    ): StreamResponse

    /** GET /api/v1/stats — catalog and diagnostic counts. */
    @GET("api/v1/stats")
    suspend fun getStats(): StatsResponse

    // ── OPTIONAL sync account (api/v2/account) ───────────────────────────────────
    //
    // Everything below is opt-in by construction: the app calls none of it unless a key
    // is already stored or the viewer pressed a button on the Account card. A wrong or
    // absent key answers a 401 with an RFC 9457 body (`unauthorised`), a revoked one
    // answers 404 on the GET routes, and a burst of failures answers 429 with
    // `retry_after` — see [com.raddstream.app.sync.SyncContract] for what this app does
    // with each, which is never "retry inside the same session".

    /**
     * POST /api/v2/account — the one call that needs no key.
     *
     * An empty body mints a fresh account and answers its key exactly once. Passing an
     * existing key in the body is how a returning viewer imports one they kept: the
     * server recognises it, answers `created: false` and never repeats the plaintext.
     */
    @POST("api/v2/account")
    suspend fun createAccount(
        @Body body: AccountCreateRequest,
    ): AccountCreateResponse

    /** GET /api/v2/account — proves the stored key still names a live account. */
    @GET("api/v2/account")
    suspend fun getAccount(
        @Header("Authorization") authorization: String?,
    ): AccountInfoResponse

    /** POST /api/v2/account/revoke — kills the key forever, on this device and all others. */
    @POST("api/v2/account/revoke")
    suspend fun revokeAccount(
        @Header("Authorization") authorization: String?,
    ): RevokedResponse

    /**
     * GET /api/v2/account/favorites — the saved list, newest first.
     *
     * The server's own reader is `accounts_api._limit(query, "limit")`, so the parameter
     * is `limit` (clamped to 1..1000, default 200) and not `n`. Rows carry a `work_ref`,
     * a scope and an `added_at` — no title, no poster, nothing to render.
     */
    @GET("api/v2/account/favorites")
    suspend fun listFavorites(
        @Header("Authorization") authorization: String?,
        @Query("limit") limit: Int = ACCOUNT_LIST_LIMIT,
    ): FavoritesResponse

    /** POST /api/v2/account/favorites — idempotent add of one minted handle. */
    @POST("api/v2/account/favorites")
    suspend fun addFavorite(
        @Header("Authorization") authorization: String?,
        @Body body: FavoriteRequest,
    ): FavoriteWriteResponse

    /** POST /api/v2/account/favorites/remove — `removed: false` just means it was not there. */
    @POST("api/v2/account/favorites/remove")
    suspend fun removeFavorite(
        @Header("Authorization") authorization: String?,
        @Body body: FavoriteRequest,
    ): RemovedResponse

    /** GET /api/v2/account/progress — continue-watching rows, most recently updated first. */
    @GET("api/v2/account/progress")
    suspend fun listProgress(
        @Header("Authorization") authorization: String?,
        @Query("limit") limit: Int = ACCOUNT_LIST_LIMIT,
    ): ProgressResponse

    /**
     * POST /api/v2/account/progress — record where viewing stopped.
     *
     * `client_updated_at` is this device's clock in epoch seconds and is the row's
     * comparison key: a write that is not newer than what the server holds is ignored,
     * not rejected, and comes back with `applied: false`.
     */
    @POST("api/v2/account/progress")
    suspend fun putProgress(
        @Header("Authorization") authorization: String?,
        @Body body: ProgressRequest,
    ): ProgressWriteResponse

    /** POST /api/v2/account/progress/remove — "watched" / "start over". */
    @POST("api/v2/account/progress/remove")
    suspend fun removeProgress(
        @Header("Authorization") authorization: String?,
        @Body body: ProgressRequest,
    ): RemovedResponse
}
