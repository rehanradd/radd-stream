package com.raddstream.app.repository

import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.network.ApiProvider
import com.raddstream.app.network.bearerHeader
import kotlinx.coroutines.flow.first
import com.raddstream.app.network.models.ContactRequest
import com.raddstream.app.network.models.FacetsResponse
import com.raddstream.app.network.models.LiveTvChannelsResponse
import com.raddstream.app.network.models.PlayBundle
import com.raddstream.app.network.models.Post
import com.raddstream.app.network.models.PostDetail
import com.raddstream.app.network.models.PostsResponse
import com.raddstream.app.network.models.SeasonArtwork
import com.raddstream.app.network.models.StatsResponse
import com.raddstream.app.network.models.StreamResponse
import com.raddstream.app.network.models.SuggestItem
import com.raddstream.app.network.models.VipRemoteConfig
import com.raddstream.app.network.models.EpisodeOffsetRequest
import com.raddstream.app.network.models.LinkReportRequest
import com.raddstream.app.network.models.WirePlayRequest
import com.raddstream.app.player.Coverage
import com.raddstream.app.player.toPlayerCoverage
import java.io.IOException
import java.util.concurrent.atomic.AtomicBoolean
import javax.inject.Inject
import javax.inject.Singleton
import retrofit2.HttpException

@Singleton
class CatalogRepository @Inject constructor(
    private val apiProvider: ApiProvider,
    private val settingsRepository: ServerSettingsRepository,
) {
    suspend fun testAndSaveServer(serverUrl: String): StatsResponse {
        val normalizedUrl = com.raddstream.app.network.normalizeServerUrl(serverUrl)
        val stats = apiProvider.forServer(normalizedUrl).getStats()
        settingsRepository.saveServerUrl(normalizedUrl)
        return stats
    }

    suspend fun getStats(): StatsResponse = apiProvider.current().getStats()

    private val connectionWarmed = AtomicBoolean(false)

    /**
     * Session 153 — warm the connection once per process before the first
     * detail load: one cheap stats call through the same provider, so DNS +
     * TCP + the OkHttp pool are warm when the big v2 detail call goes out.
     * A first tap that fails before any byte leaves the device is a cold
     * connection, not a slow server; warming it here costs one small call
     * and never holds the detail back (failures are swallowed, and the
     * caller bounds the wait). Only the first call pays it.
     */
    suspend fun warmConnectionIfNeeded() {
        if (!connectionWarmed.compareAndSet(false, true)) return
        runCatching { getStats() }
    }

    /** Live TV channels from the server-side registry (see `live_tv.py`). */
    suspend fun getLiveTvChannels(
        category: String? = null,
    ): LiveTvChannelsResponse = apiProvider.current().getLiveTvChannels(category)

    suspend fun getPosts(
        query: String? = null,
        type: String? = null,
        industry: String? = null,
        genre: String? = null,
        language: String? = null,
        quality: String? = null,
        sort: String? = null,
        freeOnly: Boolean? = null,
        workRef: String? = null,
        page: Int = 1,
        limit: Int = 20,
    ): PostsResponse = apiProvider.current().getPosts(
        query = query?.takeIf(String::isNotBlank),
        type = type,
        industry = industry,
        genre = genre,
        language = language,
        quality = quality,
        sort = sort,
        freeOnly = freeOnly,
        workRef = workRef,
        page = page,
        limit = limit,
    )

    /**
     * GET /api/v1/trending — the "Most versions" rail's own route. Throws
     * like [getPosts]; the caller ([HomeViewModel.loadSection]) falls back
     * to the `sort=trending` list when the route is unavailable, so an old
     * server never loses the rail.
     */
    suspend fun getTrending(
        type: String? = null,
        page: Int = 1,
        limit: Int = 20,
    ): PostsResponse = apiProvider.current().getTrending(
        type = type,
        page = page,
        limit = limit,
    )

    /**
     * GET /api/v1/related — "Because you watch" for one seed post id.
     * Throws like [getPosts]; an empty page is a rail with nothing to
     * show, not an error.
     */
    suspend fun getRelated(
        workId: Int,
        page: Int = 1,
        limit: Int = 20,
    ): PostsResponse = apiProvider.current().getRelated(
        workId = workId,
        page = page,
        limit = limit,
    )

    /**
     * GET /api/v1/facets — the browse jump-off chips. Null on any failure,
     * like [browseWorksV2]: a chips call that fails must never fail the
     * Home load it was helping, and the screen must not pretend the
     * silence means "no genres exist". An empty response is NOT null:
     * the server answered and has no facets.
     */
    suspend fun getFacets(): FacetsResponse? {
        return try {
            apiProvider.current().getFacets()
        } catch (_: HttpException) {
            null
        } catch (_: IOException) {
            null
        }
    }

    /**
     * GET /api/v2/suggest while typing. Never throws: a blocked route (the
     * live nginx allow-list covers it since the rev-7 deploy, so a 403 now
     * means something else), an old server or a dead socket all answer
     * the same way — null, which the caller
     * reads as "suggestions unavailable", distinct from an empty list (the
     * server answered and has no matches). A type-ahead that fails must
     * never fail the search it was helping, but the screen must not pretend
     * the silence means "no titles match".
     */
    suspend fun suggest(query: String): List<SuggestItem>? {
        if (query.trim().length < 2) return emptyList()
        return runCatching {
            apiProvider.current().suggest(query.trim(), limit = 5).items
        }.getOrNull()
    }

    /**
     * GET /api/v1/posts/{id} — one title's detail. Null on ANY failure.
     *
     * `warm` asks the server to pre-resolve the auto tier's link while the
     * viewer is still on the detail screen (audit #1: the Play press then
     * answers from the resolved cache instead of paying a 5–11 s live
     * resolve). `audio` names the preferred audio language; the server
     * orders preferred-audio tiers first. Both default off, so the
     * compliance probe and the player-side re-read send the old request.
     */
    suspend fun getPostDetail(postId: Int, warm: Boolean = false, audio: String? = null): PostDetail? {
        val response = try {
            apiProvider.current().getPostDetail(
                postId,
                warm = if (warm) "1" else null,
                audio = audio?.takeIf { it.isNotBlank() },
            )
        } catch (_: IllegalStateException) {
            // Session 155 (S2): the provider throwing "Connect to a catalog
            // server first" is a first-call readiness failure, not a server
            // refusal — the server IS configured (the brand default), and a
            // re-call succeeds. Null so the caller's retry re-asks instead
            // of hard-failing the first tap. Only the provider-not-ready
            // error is caught here: a dead socket still throws, so the
            // caller can tell a refusal from a failure to ask.
            return null
        }
        if (response.success && response.data != null) {
            return response.data
        }
        return null
    }

    /**
     * GET /api/v2/browse (Phase 7, M1): one page of works. Null on ANY failure —
     * a 403 until the gate adds the route to nginx (the location ships in
     * this branch's ORACLE_DEPLOYMENT.md addendum), a 404, a dead socket — because
     * the caller falls back to the v1 list it already has, and a list that used
     * to load must never turn into an error for a call that is only an upgrade.
     * An empty page is NOT null here: the caller decides whether empty means
     * "fall back" (a type the v2 side cannot serve) or "no titles".
     */
    suspend fun browseWorksV2(
        type: String? = null,
        sort: String? = null,
        limit: Int = 20,
        cursor: String? = null,
    ): V2BrowsePage? {
        val response = try {
            apiProvider.current().browseWorks(type = type, sort = sort, limit = limit, cursor = cursor)
        } catch (_: HttpException) {
            return null
        } catch (_: IOException) {
            return null
        }
        if (!response.ok) return null
        return V2BrowsePage(
            posts = response.items.map { it.toPost() },
            nextCursor = response.nextCursor,
            hasMore = response.hasMore,
            totalEstimate = response.totalEstimate,
        )
    }

    /**
     * GET /api/v2/search (Phase 7, M1): title search over the works ledger.
     * Null on any failure, like [browseWorksV2]. An empty page is NOT null:
     * the caller falls back to the v1 `q=` search when it is empty, because
     * only v1 matches cast — an actor query is the one query v2 cannot answer.
     */
    suspend fun searchWorksV2(
        query: String,
        sort: String? = null,
        limit: Int = 20,
        cursor: String? = null,
        type: String? = null,
        genres: List<String>? = null,
        industries: List<String>? = null,
        qualities: List<String>? = null,
    ): V2BrowsePage? {
        val response = try {
            apiProvider.current().searchWorks(
                query = query, sort = sort, limit = limit, cursor = cursor, type = type,
                genres = genres, industries = industries, qualities = qualities,
            )
        } catch (_: HttpException) {
            return null
        } catch (_: IOException) {
            return null
        }
        if (!response.ok) return null
        return V2BrowsePage(
            posts = response.items.map { it.toPost() },
            nextCursor = response.nextCursor,
            hasMore = response.hasMore,
            totalEstimate = response.totalEstimate,
        )
    }

    /**
     * GET /api/v2/works/{id} (Phase 7, M1): one work, whole, mapped to the
     * [PostDetail] the detail screen already reads. Null on any failure, so the
     * caller falls back to the v1 detail it already has.
     *
     * The v2 projection carries no cast and no season artwork, so those ride in
     * through the `work_ref` bridge: one `GET /api/v1/posts?work_ref=…` names
     * the work's v1 post, and one `GET /api/v1/posts/{id}` reads the cast off
     * it. The bridge also resolves the real v1 post id, which is what Room
     * favorites/history and the adult ledger key on — the mapped detail's `id`
     * is that post id, or 0 when the bridge did not resolve, never the work id.
     * A bridge failure never fails the detail: the cast section simply hides,
     * exactly as it does on a v1 row with no cast data.
     */
    suspend fun getWorkDetailV2(workId: Long, audio: String? = null): PostDetail? {
        val response = try {
            apiProvider.current().getWorkDetail(workId)
        } catch (_: HttpException) {
            return null
        } catch (_: IOException) {
            return null
        } catch (_: IllegalStateException) {
            // Session 155 (S2): the provider throwing "Connect to a catalog
            // server first" is a first-call readiness failure, not a server
            // refusal — the server IS configured (the brand default), and a
            // re-call succeeds. Null so the caller's null-retry re-asks
            // instead of hard-failing the first tap.
            return null
        }
        if (!response.ok) return null
        val baseUrl = try {
            apiProvider.currentBaseUrl()
        } catch (_: IllegalStateException) {
            return null
        }
        var v1PostId = 0
        var castNames: String? = null
        var seasonArtwork: List<SeasonArtwork> = emptyList()
        val workRef = response.work?.workRef
        if (!workRef.isNullOrBlank()) {
            runCatching {
                val post = apiProvider.current().getPosts(workRef = workRef, page = 1, limit = 1)
                    .results.firstOrNull()
                if (post != null && post.id > 0) {
                    v1PostId = post.id
                    // Warm the auto tier too: a v2 title's Play press pays
                    // the same live resolve, and this is the only v1 detail
                    // call on this path. Audio rides along now (Gap A2
                    // follow-up): without it the warmed auto tier could be a
                    // different audio than the ladder Play presses. The tiers
                    // from this call are never shown, only cast + season art.
                    val detail = apiProvider.current().getPostDetail(
                        post.id,
                        warm = "1",
                        audio = audio?.takeIf { it.isNotBlank() },
                    )
                    if (detail.success && detail.data != null) {
                        castNames = detail.data.castNames
                        seasonArtwork = detail.data.seasonArtwork
                    }
                }
            }
        }
        return response.toPostDetail(baseUrl, v1PostId, castNames, seasonArtwork)
    }

    /**
     * GET /api/v2/resolve/{handle} with `redirect=0` (Phase 7, M3): the
     * re-resolved link's measured facts. Null on any failure; the caller keeps
     * the v1 redirector metadata it already has. The echoed `stream_id` is the
     * v1-stream handle for the same link.
     */
    suspend fun resolveV2(handle: String): StreamResponse? {
        if (handle.isBlank()) return null
        val response = try {
            apiProvider.current().resolveV2(handle, redirect = "0")
        } catch (_: HttpException) {
            return null
        } catch (_: IOException) {
            return null
        }
        if (!response.ok) return null
        return StreamResponse(
            success = true,
            streamHandle = response.streamId,
            kind = response.kind,
            mimeType = response.mimeType,
            fileSizeBytes = response.fileSizeBytes,
            resumable = response.resumable,
            expiresIn = response.expiresIn,
            refreshed = response.refreshed,
        )
    }

    /**
     * Ask OUR OWN redirector about one opaque handle (`redirect=0`): metadata only, never a
     * location. Not needed to play — Media3 follows the 302 — only to learn resumability.
     *
     * Session 153: the call carries the viewer's sync key when signed in, so a
     * gated handle warms as the account that will press it instead of 402ing
     * anonymously and banking nothing. Same pattern as [playV2] below; the
     * key rides a metadata-only call, so no redirect ever carries it onward.
     */
    suspend fun resolveStream(streamId: String): StreamResponse {
        val authorization = runCatching {
            bearerHeader(settingsRepository.syncKey.first())
        }.getOrNull()
        return apiProvider.current().resolveStream(streamId, redirect = "0", authorization = authorization)
    }

    /**
     * POST /api/v2/play for one print (plan §5 step 13): the server's own ranked
     * bundle, with the coverage the v1 detail never serves. Returns null on ANY
     * failure — a 403, a 404 for a target the
     * server cannot see, a dead socket, a print with nothing playable — because the
     * caller falls back to the client-side ladder it already has, and a Play tap
     * that used to work must never turn into an error for a call that is only an
     * upgrade. A ceiling on the wait is the caller's job, not this one's.
     */
    suspend fun playV2(releaseId: Int, prefer: String? = null, legacyReleaseId: Boolean = true): V2PlayResult? {
        // Session 123: the call carries the viewer's sync key when signed in,
        // so the server's quality-gate mint refusal can exempt a VIP caller.
        // A guest sends no header at all. The key is read here, not passed
        // in, because every caller would otherwise have to thread it through.
        val authorization = runCatching {
            bearerHeader(settingsRepository.syncKey.first())
        }.getOrNull()
        val response = try {
            apiProvider.current().play(
                WirePlayRequest(
                    releaseId = releaseId,
                    prefer = prefer ?: "quality",
                    // Salaar (2026-11-12): a v2 detail's print id is a cat id,
                    // and the server must not translate it through the legacy
                    // map. The caller names the universe; the default stays
                    // legacy, for the v1 detail that hands those out.
                    legacyReleaseId = legacyReleaseId,
                ),
                authorization = authorization,
            )
        } catch (_: HttpException) {
            return null
        } catch (_: IOException) {
            return null
        }
        if (!response.playable || response.streamCandidates.isEmpty()) return null
        val baseUrl = try {
            apiProvider.currentBaseUrl()
        } catch (_: IllegalStateException) {
            return null
        }
        val coverage = response.coverage?.toPlayerCoverage() ?: Coverage()
        return V2PlayResult(bundle = response.toDomain(baseUrl), coverage = coverage)
    }

    /**
     * POST /api/v2/links/{handle}/report — one playback fact about one link
     * (Session 123). Best-effort by design: true only when the server recorded
     * it; ANY failure (a 403, a dead socket,
     * a 400 for a stale handle) answers false and is dropped silently, because
     * a report must never interrupt playback or show the viewer an error.
     * `handle` is our own opaque handle — never a raw row id.
     */
    suspend fun reportLink(handle: String, event: String, latencyMs: Int? = null, error: String? = null): Boolean {
        if (handle.isBlank()) return false
        return try {
            val response = apiProvider.current().reportLink(
                handle = handle,
                body = LinkReportRequest(event = event, latencyMs = latencyMs, error = error),
            )
            response.recorded
        } catch (_: HttpException) {
            false
        } catch (_: IOException) {
            false
        }
    }

    /**
     * POST /api/v2/episodes/{episodeId}/offset — a learned pack offset
     * (Session 123). Best-effort like [reportLink]: false on any failure, and
     * the local learned offset stays in place either way.
     */
    suspend fun reportEpisodeOffset(
        episodeId: Int,
        offsetSeconds: Int,
        chapterTitle: String? = null,
        releaseLabel: String? = null,
    ): Boolean {
        return try {
            val response = apiProvider.current().reportEpisodeOffset(
                episodeId = episodeId,
                body = EpisodeOffsetRequest(
                    offsetSeconds = offsetSeconds,
                    chapterTitle = chapterTitle,
                    releaseLabel = releaseLabel,
                ),
            )
            response.recorded
        } catch (_: HttpException) {
            false
        } catch (_: IOException) {
            false
        }
    }

    /**
     * POST /api/v1/contact: one message for the operator's inbox. True only
     * when the server stored it — a 400 (bad category, empty body), a 403,
     * a 503 when the inbox is not wired,
     * or a dead socket all answer false, because the form keeps the text and
     * says "try again" instead of pretending the message went through.
     */
    suspend fun submitContact(
        category: String,
        subject: String,
        body: String,
        accountHint: String?,
    ): Boolean {
        return try {
            apiProvider.current().submitContact(
                ContactRequest(category, subject, body, accountHint),
            ).success
        } catch (_: HttpException) {
            false
        } catch (_: IOException) {
            false
        }
    }

    /**
     * Ask the detail route about one id purely to learn whether it still answers, and report the
     * answer as PRIMITIVES rather than as a verdict. The verdict is `viewmodel/AdultPolicy`'s to
     * make, in one place, so a revalidation pass and a render filter can never disagree about what
     * a 404 meant; this method's job is only to not lose the distinction between "refused",
     * "served" and "I could not ask".
     *
     * That third case is the reason this exists as its own call instead of reusing
     * [getPostDetail]: that one collapses a 404 and a dead socket into the same `null`, which is
     * correct for a screen and fatal for a compliance ledger — an outage that wrote refusals would
     * empty My List on a plane flight.
     */
    suspend fun probePost(postId: Int): DetailProbe = try {
        val response = apiProvider.current().getPostDetail(postId)
        DetailProbe(httpStatus = HTTP_OK, bodyClaimsSuccess = response.success, noAnswer = false)
    } catch (e: HttpException) {
        // A refusal carries no parsed body here: `getPostDetail` is typed to the success shape, so
        // Retrofit throws before `{"success": false}` is ever read. The status is the fact.
        DetailProbe(httpStatus = e.code(), bodyClaimsSuccess = null, noAnswer = false)
    } catch (_: IOException) {
        DetailProbe(httpStatus = null, bodyClaimsSuccess = null, noAnswer = true)
    } catch (_: IllegalStateException) {
        // No server configured yet — ApiProvider refuses before it builds a request.
        DetailProbe(httpStatus = null, bodyClaimsSuccess = null, noAnswer = true)
    }

    /** Live VIP prices and payment handles; never cached here, the server sets its own max-age. */
    suspend fun getRemoteConfig(): VipRemoteConfig = apiProvider.current().getRemoteConfig()

    companion object {
        private const val HTTP_OK = 200
    }
}

/**
 * What one `GET /api/v1/posts/{id}` round-trip established, before anyone decided what to do
 * about it. `httpStatus` and `noAnswer` are mutually exclusive by construction: an answer always
 * has a status, and the absence of one is spelled [noAnswer] rather than a made-up code — a reader
 * that inferred "no status means gone" would hide a viewer's library on a timeout.
 */
data class DetailProbe(
    val httpStatus: Int?,
    val bodyClaimsSuccess: Boolean?,
    val noAnswer: Boolean,
)

/**
 * What POST /api/v2/play hands back, as the app uses it: the server-ranked bundle plus
 * the print's coverage (the chapter data). The two ride together because the coverage
 * belongs to the bundle's print, not to any one rung — the detail screen stages both
 * under the winner's handle, and the player reads both back from the same place.
 */
data class V2PlayResult(
    val bundle: PlayBundle,
    val coverage: Coverage,
)

/**
 * One page of a v2 list (Phase 7, M1): the mapped rows plus the keyset cursor
 * for the next page. `hasMore` is the server's own answer; a null cursor with
 * `hasMore` true means the server withheld the cursor and the caller must stop.
 */
data class V2BrowsePage(
    val posts: List<Post>,
    val nextCursor: String?,
    val hasMore: Boolean,
    /** The server's rough total for this query, or null when it did not say. */
    val totalEstimate: Int? = null,
)
