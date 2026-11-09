package com.raddstream.app.network

import com.raddstream.app.network.models.AccountCreateRequest
import com.raddstream.app.network.models.AccountCreateResponse
import com.raddstream.app.network.models.AccountInfoResponse
import com.raddstream.app.network.models.AccountOverviewResponse
import com.raddstream.app.network.models.CoinBalanceResponse
import com.raddstream.app.network.models.CoinCapsResponse
import com.raddstream.app.network.models.CoinHistoryResponse
import com.raddstream.app.network.models.CoinDownloadCreditRequest
import com.raddstream.app.network.models.CoinDownloadCreditResponse
import com.raddstream.app.network.models.CoinEarnRequest
import com.raddstream.app.network.models.CoinEarnResponse
import com.raddstream.app.network.models.CoinRedeemRequest
import com.raddstream.app.network.models.CoinRedeemResponse
import com.raddstream.app.network.models.CoinRedeemThemeRequest
import com.raddstream.app.network.models.CoinRedeemThemeResponse
import com.raddstream.app.network.models.CoinRequestMovieRequest
import com.raddstream.app.network.models.CoinRequestMovieResponse
import com.raddstream.app.network.models.CoinShareRequest
import com.raddstream.app.network.models.CoinShareResponse
import com.raddstream.app.network.models.CoinThemesResponse
import com.raddstream.app.network.models.ContactRequest
import com.raddstream.app.network.models.ContactResponse
import com.raddstream.app.network.models.DeviceTrialRequest
import com.raddstream.app.network.models.DeviceTrialResponse
import com.raddstream.app.network.models.EntitlementResponse
import com.raddstream.app.network.models.VipPassResponse
import com.raddstream.app.network.models.FavoriteRequest
import com.raddstream.app.network.models.FavoriteWriteResponse
import com.raddstream.app.network.models.FavoritesResponse
import com.raddstream.app.network.models.PaymentRequest
import com.raddstream.app.network.models.PaymentSubmitResponse
import com.raddstream.app.network.models.LiveTvChannelsResponse
import com.raddstream.app.network.models.PostDetailResponse
import com.raddstream.app.network.models.PostsResponse
import com.raddstream.app.network.models.ProfileLinkRequest
import com.raddstream.app.network.models.ProfileLinkResponse
import com.raddstream.app.network.models.ProgressRequest
import com.raddstream.app.network.models.ProgressResponse
import com.raddstream.app.network.models.ProgressWriteResponse
import com.raddstream.app.network.models.RemovedResponse
import com.raddstream.app.network.models.RevokedResponse
import com.raddstream.app.network.models.StatsResponse
import com.raddstream.app.network.models.StreamResponse
import com.raddstream.app.network.models.SuggestResponse
import com.raddstream.app.network.models.VipRemoteConfig
import com.raddstream.app.network.models.EpisodeOffsetRequest
import com.raddstream.app.network.models.EpisodeOffsetResponse
import com.raddstream.app.network.models.LinkReportRequest
import com.raddstream.app.network.models.LinkReportResponse
import com.raddstream.app.network.models.WireBrowseResponse
import com.raddstream.app.network.models.WirePlayRequest
import com.raddstream.app.network.models.WirePlayResponse
import com.raddstream.app.network.models.WireResolveResponse
import com.raddstream.app.network.models.WireWorkDetailResponse
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
 * The key goes out as a header value: over HTTPS to the shipped default, in the clear to a
 * server the viewer points at over plain HTTP. The account screen says which one is in use
 * out loud, and never claims a protection the transport does not provide.
 */
interface RaddStreamApi {

    /**
     * GET /api/v1/posts — paginated metadata catalog.
     *
     * `industry`, `genre`, `quality` and `sort` narrow/reorder the whole catalog on
     * the server before paging (see `Fast_Fetch/viewer.py:api_v1_get_posts`), so a
     * chip stays correct across pages instead of filtering only the rows already
     * loaded. Each value is one of the small fixed vocabularies in
     * `SearchViewModel`; null simply omits the query parameter.
     */
    @GET("api/v1/posts")
    suspend fun getPosts(
        @Query("q") query: String? = null,
        @Query("type") type: String? = null,
        @Query("industry") industry: String? = null,
        @Query("genre") genre: String? = null,
        @Query("quality") quality: String? = null,
        @Query("sort") sort: String? = null,
        @Query("free_only") freeOnly: Boolean? = null,
        @Query("work_ref") workRef: String? = null,
        @Query("page") page: Int = 1,
        @Query("limit") limit: Int = 20,
    ): PostsResponse

    /**
     * GET /api/v2/suggest — cheap type-ahead over the works ledger (title
     * prefixes only). An enhancement, never a gate: the route needs the
     * nginx allow-list (a gate item, like /api/v2/play), so a 403 here
     * means no chips, never a failed search.
     */
    @GET("api/v2/suggest")
    suspend fun suggest(
        @Query("q") query: String,
        @Query("limit") limit: Int = 5,
    ): SuggestResponse

    /**
     * GET /api/v2/browse — the v2 catalog list (Phase 7, M1). One row per WORK,
     * not one per site-post, keyed by `cat_works.id` with keyset pagination
     * (`next_cursor`), so a scrape landing mid-walk cannot repeat or skip a
     * title the way the v1 `page` window could. `type` takes the v2 `work_type`
     * values AND the four legacy v1 `content_type` strings (`movie`, `series`,
     * `anime`, `complete_season`, `ongoing_season`); `sort` is one of
     * `trending | newest | quality | rating | title | updated`.
     *
     * The route needs the nginx allow-list (a gate item, like /api/v2/play was):
     * until the gate adds the `works`/`browse`/`search` locations a 403 here
     * means "stay on v1", never a failed list — every caller falls back.
     */
    @GET("api/v2/browse")
    suspend fun browseWorks(
        @Query("type") type: String? = null,
        @Query("sort") sort: String? = null,
        @Query("order") order: String? = null,
        @Query("limit") limit: Int = 20,
        @Query("cursor") cursor: String? = null,
        @Query("genre") genres: List<String>? = null,
        @Query("industry") industries: List<String>? = null,
    ): WireBrowseResponse

    /**
     * GET /api/v2/search — title search over the works ledger (Phase 7, M1).
     * Matches title, original title and aliases — NOT cast: an actor query that
     * finds nothing here must fall back to the v1 `q=` search, which matches
     * `cast_names` too. `sort` defaults to `relevance` server-side.
     */
    @GET("api/v2/search")
    suspend fun searchWorks(
        @Query("q") query: String,
        @Query("sort") sort: String? = null,
        @Query("limit") limit: Int = 20,
        @Query("cursor") cursor: String? = null,
        @Query("type") type: String? = null,
        @Query("genre") genres: List<String>? = null,
        @Query("industry") industries: List<String>? = null,
        @Query("quality") qualities: List<String>? = null,
    ): WireBrowseResponse

    /**
     * GET /api/v2/works/{id} — one work, whole (Phase 7, M1): identity,
     * seasons with enumerated episodes, every print with its links, and the
     * availability block. `id` is the `cat_works` id (or a work key). The
     * projection carries no cast and no season artwork — the caller merges
     * those from the v1 detail through the `work_ref` bridge, or the detail
     * screen loses its cast section to the migration.
     */
    @GET("api/v2/works/{id}")
    suspend fun getWorkDetail(
        @Path("id") workId: Long,
    ): WireWorkDetailResponse

    /**
     * GET /api/v2/resolve/{handle} — re-resolve one cat link (Phase 7, M3).
     * `redirect=0` answers metadata only (`stream_id`, `kind`, `mime_type`,
     * `file_size_bytes`, `resumable`, `expires_in`) and never a location; the
     * echoed `stream_id` is the v1-stream handle for the same link, so a
     * caller that learns the size here can still press the v1 redirector.
     * The route is the one `EndpointGaps.RESOLVE` used to misname as
     * `/api/v2/links/{link_id}/resolve`, which never existed.
     */
    @GET("api/v2/resolve/{handle}")
    suspend fun resolveV2(
        @Path("handle") handle: String,
        @Query("redirect") redirect: String = "0",
    ): WireResolveResponse

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

    /**
     * GET /api/v1/live-tv/channels — the Live TV tab's channel list, served
     * from the server-side registry. Each channel carries a signed `stream_id`
     * handle; the app never sees the upstream HLS URL, and playback goes
     * through the existing player on `/api/v1/stream?id=…` exactly like a
     * movie. `category` narrows server-side; null lists everything the
     * operator enabled.
     *
     * NOTE (deploy): the nginx public allow-list does not yet include
     * the `/api/v1/live-tv/` prefix — until the gate adds it this answers 403 and the
     * tab shows its honest unavailable state, never a fake list.
     */
    @GET("api/v1/live-tv/channels")
    suspend fun getLiveTvChannels(
        @Query("category") category: String? = null,
    ): LiveTvChannelsResponse

    /**
     * GET /api/v1/app/remote-config — VIP pricing and the operator's payment handles.
     *
     * Public and unauthenticated by design: it is the same body a web client reads, and the
     * admin panel masks the secrets in its row before publishing. A handle may legitimately be
     * empty on a server that has not configured payments yet — an empty value is the honest
     * answer, not an error.
     */
    @GET("api/v1/app/remote-config")
    suspend fun getRemoteConfig(): VipRemoteConfig

    /**
     * POST /api/v1/contact — the public contact form, no login, no sync key.
     *
     * The message lands in the panel's inbox under the panel's own rules
     * (category, subject and body limits, the contact hint stored masked).
     * The server answers `{"success": true}` on store, 400 for a bad
     * category or an empty body, 503 when the inbox is not wired.
     */
    @POST("api/v1/contact")
    suspend fun submitContact(
        @Body request: ContactRequest,
    ): ContactResponse

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

    /**
     * POST /api/v2/account/anonymous — start or resume this install's three-day trial.
     *
     * Unauthenticated by construction, like [createAccount]: the body is `device_id` and nothing
     * else, and no body field can set `trial_days` (`accounts_api.py:494` — a client that picks
     * its own trial length is a client that picks its own price). A device the server has never
     * seen gets a new account and answers **201 with `sync_key`**; a device it knows gets its own
     * stored expiry back as **200 with no key**, because the key is stored one-way and handing it
     * back on a caller-chosen id would be a takeover for anyone who guessed one. The one
     * exception is `reissued`: a known device whose account was revoked or pruned gets a freshly
     * minted key for the SAME expired clock — so the app must read the key out of the answer
     * rather than assume 200 means no key.
     *
     * What this is not: an attestation. `device_id` is client-reported and spoofable, so the copy
     * that shows this answer says "three days on this install" and never "locked to your device".
     */
    @POST("api/v2/account/anonymous")
    suspend fun startDeviceTrial(
        @Body body: DeviceTrialRequest,
    ): DeviceTrialResponse

    /**
     * POST /api/v2/account/profile-link — put a name, a phone and a 4-8 digit PIN on this account.
     *
     * The bearer key is mandatory and is the only thing that decides which account is written:
     * a body `account_id` is ignored on purpose, not refused. The server stores the PIN as
     * PBKDF2-HMAC-SHA256 with a per-row salt and 120k iterations, which slows a stolen database
     * file and does nothing for the wire — to a server the viewer points at over plain HTTP the
     * digits cross it in the clear and the attempt limiter is the only thing between a 4-digit
     * PIN and a guesser; the shipped default speaks HTTPS. No copy about this call may say
     * secure, encrypted, private, or "only you can access this" about a plain-HTTP server.
     *
     * **201 means the +1 day bonus was granted; 200 means it already was** (`linked_at` makes it
     * once per account), so the entitlement is unchanged by a replay and a retry after a network
     * error is safe here in a way it is not for a payment. A second call must present the PIN
     * already on file, and a wrong one answers 401 — which on this route means the PIN and not the
     * key; see [com.raddstream.app.sync.DeviceTrial.profileLinkVerdict].
     */
    @POST("api/v2/account/profile-link")
    suspend fun linkProfile(
        @Header("Authorization") authorization: String?,
        @Body body: ProfileLinkRequest,
    ): ProfileLinkResponse

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

    /**
     * File a claimed transaction reference — the TID form's one write.
     *
     * The screen action is "submit the transaction id", so this is named for it. The route
     * is the one this deployment actually serves: `POST /api/v2/account/payment`. There is
     * no `/api/v1/vip/submit-tid` on this server, and a client that called one would turn a
     * real payment into a 404, so the method points at the ledger instead of at a note.
     *
     * `phone` is deliberately absent from the body: the ledger keys a claim to the sync
     * account and matches the reference against the payment channel, so the payer's own
     * mobile number is neither needed nor collected. Sending PII the server never reads
     * would be worse than useless.
     *
     * A claim, not a purchase: the server stores it as `pending`, prices the plan from
     * its own table and only a human on the loopback panel turns it into VIP. One
     * submission per account per window, so a second tap inside five minutes is a 429
     * with `retry_after` rather than a duplicate row. The answer is a receipt without
     * the reference in it.
     */
    @POST("api/v2/account/payment")
    suspend fun submitVipTid(
        @Header("Authorization") authorization: String?,
        @Body body: PaymentRequest,
    ): PaymentSubmitResponse

    /**
     * GET /api/v2/account/entitlement — the only question that answers "am I VIP?".
     *
     * Auth behaves exactly like every other account route, because `viewer.py` reads the
     * body before dispatch: no key is a 401 and a key the server does not know is a 404,
     * on this route and on the list routes alike. So nothing here has to special-case a
     * missing key.
     */
    @GET("api/v2/account/entitlement")
    suspend fun getEntitlement(
        @Header("Authorization") authorization: String?,
    ): EntitlementResponse

    /**
     * GET /api/v2/account/vip-pass — a signed pass the stream/download URLs
     * can carry (Session 123). 401 with no key, 402 with no live membership,
     * 410 when the membership lapsed between the check and the mint. The app
     * re-asks when it refreshes its entitlement; the pass itself is good for
     * six hours at most, capped at the membership end.
     */
    @GET("api/v2/account/vip-pass")
    suspend fun getVipPass(
        @Header("Authorization") authorization: String?,
    ): VipPassResponse

    /**
     * GET /api/v2/account/coins — this account's own coin balance. The number is the
     * same `SUM(delta)` the spender checks before it debits, so a reply and a refusal
     * cannot disagree about what this account holds.
     */
    @GET("api/v2/account/coins")
    suspend fun getCoinBalance(
        @Header("Authorization") authorization: String?,
    ): CoinBalanceResponse

    /**
     * GET /api/v2/account/coins/caps — the ceilings the ledger holds, the pass prices
     * and the streak ladder this server will actually pay. The ladder here is the one
     * the earn route enforces, so the phone cannot show a prize the ledger will not pay.
     */
    @GET("api/v2/account/coins/caps")
    suspend fun getCoinCaps(
        @Header("Authorization") authorization: String?,
    ): CoinCapsResponse

    /**
     * GET /api/v2/account/overview — the account's own wallet in one read:
     * the derived balance, the streak state and the ad cadence. Reading it
     * costs nothing and mints nothing.
     */
    @GET("api/v2/account/overview")
    suspend fun getAccountOverview(
        @Header("Authorization") authorization: String?,
    ): AccountOverviewResponse

    /**
     * GET /api/v2/account/coins/history — the account's own ledger rows,
     * newest first, on the server's bounded page. The limit is the page size
     * the caller asks for; the server clamps anything unreasonable.
     */
    @GET("api/v2/account/coins/history")
    suspend fun getCoinHistory(
        @Header("Authorization") authorization: String?,
        @Query("limit") limit: Int = 20,
    ): CoinHistoryResponse

    /**
     * POST /api/v2/account/coins/earn — claim today's check-in. The body carries
     * `reason` and nothing else: the grant size is the ladder's own and the day is
     * claimed by one guarded server UPDATE, so a second claim the same day answers
     * `same_day_noop` and pays nothing twice.
     */
    @POST("api/v2/account/coins/earn")
    suspend fun earnDailyLogin(
        @Header("Authorization") authorization: String?,
        @Body body: CoinEarnRequest,
    ): CoinEarnResponse

    /**
     * POST /api/v2/account/coins/redeem — spend coins on a VIP pass. The body carries
     * the plan name and nothing else: the price is the ladder's own, the debit is one
     * guarded server UPDATE, and the pass is recorded against the account, so the
     * entitlement it buys is visible the next time the app reads it.
     */
    @POST("api/v2/account/coins/redeem")
    suspend fun redeemPass(
        @Header("Authorization") authorization: String?,
        @Body body: CoinRedeemRequest,
    ): CoinRedeemResponse

    /**
     * POST /api/v2/account/coins/redeem-download — spend coins on one direct
     * download of one movie. The body carries the download handle and nothing
     * else: the price is the server's own knob, the debit is one guarded
     * server UPDATE, and the answer's token is the credit the browser spends
     * on `GET /api/v1/download?credit=…`.
     */
    @POST("api/v2/account/coins/redeem-download")
    suspend fun redeemDownloadCredit(
        @Header("Authorization") authorization: String?,
        @Body body: CoinDownloadCreditRequest,
    ): CoinDownloadCreditResponse

    /**
     * POST /api/v2/account/coins/share — report one share of a movie. The body
     * carries the work handle and nothing else: the server pays once a day, so
     * a second share the same day answers `granted: false` and pays nothing.
     */
    @POST("api/v2/account/coins/share")
    suspend fun reportShare(
        @Header("Authorization") authorization: String?,
        @Body body: CoinShareRequest,
    ): CoinShareResponse

    /**
     * POST /api/v2/account/coins/request-movie — spend coins on one requested
     * movie. The body carries the title and an optional note: the price is the
     * server's own knob, and a replay answers `already_applied` with the
     * request it already filed.
     */
    @POST("api/v2/account/coins/request-movie")
    suspend fun requestMovie(
        @Header("Authorization") authorization: String?,
        @Body body: CoinRequestMovieRequest,
    ): CoinRequestMovieResponse

    /** GET /api/v2/account/coins/themes — what this account owns, and what a theme costs. */
    @GET("api/v2/account/coins/themes")
    suspend fun getCoinThemes(
        @Header("Authorization") authorization: String?,
    ): CoinThemesResponse

    /**
     * POST /api/v2/account/coins/redeem-theme — spend coins on one player
     * theme. The body carries the theme id and nothing else: the price is one
     * price for every theme, and a theme already owned answers
     * `already_applied` with the ownership it already holds.
     */
    @POST("api/v2/account/coins/redeem-theme")
    suspend fun redeemTheme(
        @Header("Authorization") authorization: String?,
        @Body body: CoinRedeemThemeRequest,
    ): CoinRedeemThemeResponse

    /**
     * POST /api/v2/play — one PlayBundle for a print, ranked by the server (plan §5 step 13).
     *
     * This is the call the client-side bundle builder was waiting for: the server orders
     * the candidates from its own probes, hands back one tier per print plus the ranked
     * lists, and — the part no v1 route serves — the print's coverage with the episode
     * offsets and chapter titles. The response shape is the server's actual one
     * (`catalog_api.play_bundle`): tiers/candidates/coverage, no `renditions`.
     *
     * Unauthenticated like the v1 detail: the public answer is the same for every viewer.
     * A 403 here means nginx has not allowed the route yet (the gate owns that); a
     * non-playable print answers 200 with an empty ladder and `download_options` instead
     * of an error, and a target the server cannot see answers 404. The caller treats
     * ANY failure as "fall back to the client-side ladder" — never as a reason to show
     * the viewer an error for a Play tap that used to work.
     *
     * `authorization` is `Bearer <sync key>` when the viewer is signed in (Session
     * 123): the server's quality-gate mint refusal exempts a VIP caller, and it can
     * only see the capability when the call carries it. Null for a guest — the
     * header is omitted, never sent empty.
     */
    @POST("api/v2/play")
    suspend fun play(
        @Body body: WirePlayRequest,
        @Header("Authorization") authorization: String? = null,
    ): WirePlayResponse

    /**
     * POST /api/v2/links/{handle}/report — one playback fact about one link
     * (Session 123). Best-effort: the caller treats ANY failure as "dropped",
     * never as a reason to show the viewer an error.
     */
    @POST("api/v2/links/{handle}/report")
    suspend fun reportLink(
        @Path("handle") handle: String,
        @Body body: LinkReportRequest,
    ): LinkReportResponse

    /**
     * POST /api/v2/episodes/{episodeId}/offset — a learned pack offset
     * (Session 123). Best-effort like the link report.
     */
    @POST("api/v2/episodes/{episodeId}/offset")
    suspend fun reportEpisodeOffset(
        @Path("episodeId") episodeId: Int,
        @Body body: EpisodeOffsetRequest,
    ): EpisodeOffsetResponse
}
