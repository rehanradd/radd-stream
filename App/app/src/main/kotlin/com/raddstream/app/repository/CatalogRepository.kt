package com.raddstream.app.repository

import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.network.ApiProvider
import com.raddstream.app.network.models.ContactRequest
import com.raddstream.app.network.models.PlayBundle
import com.raddstream.app.network.models.PostDetail
import com.raddstream.app.network.models.PostsResponse
import com.raddstream.app.network.models.StatsResponse
import com.raddstream.app.network.models.StreamResponse
import com.raddstream.app.network.models.VipRemoteConfig
import com.raddstream.app.network.models.WirePlayRequest
import com.raddstream.app.player.Coverage
import com.raddstream.app.player.toPlayerCoverage
import java.io.IOException
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

    suspend fun getPosts(
        query: String? = null,
        type: String? = null,
        industry: String? = null,
        genre: String? = null,
        quality: String? = null,
        sort: String? = null,
        page: Int = 1,
        limit: Int = 20,
    ): PostsResponse = apiProvider.current().getPosts(
        query = query?.takeIf(String::isNotBlank),
        type = type,
        industry = industry,
        genre = genre,
        quality = quality,
        sort = sort,
        page = page,
        limit = limit,
    )

    suspend fun getPostDetail(postId: Int): PostDetail? {
        val response = apiProvider.current().getPostDetail(postId)
        if (response.success && response.data != null) {
            return response.data
        }
        return null
    }

    /**
     * Ask OUR OWN redirector about one opaque handle (`redirect=0`): metadata only, never a
     * location. Not needed to play — Media3 follows the 302 — only to learn resumability.
     */
    suspend fun resolveStream(streamId: String): StreamResponse =
        apiProvider.current().resolveStream(streamId, redirect = "0")

    /**
     * POST /api/v2/play for one print (plan §5 step 13): the server's own ranked
     * bundle, with the coverage the v1 detail never serves. Returns null on ANY
     * failure — a 403 while nginx still blocks the route, a 404 for a target the
     * server cannot see, a dead socket, a print with nothing playable — because the
     * caller falls back to the client-side ladder it already has, and a Play tap
     * that used to work must never turn into an error for a call that is only an
     * upgrade. A ceiling on the wait is the caller's job, not this one's.
     */
    suspend fun playV2(releaseId: Int, prefer: String? = null): V2PlayResult? {
        val response = try {
            apiProvider.current().play(WirePlayRequest(releaseId = releaseId, prefer = prefer ?: "quality"))
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
     * POST /api/v1/contact: one message for the operator's inbox. True only
     * when the server stored it — a 400 (bad category, empty body), a 403
     * while nginx still blocks the route, a 503 when the inbox is not wired,
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
