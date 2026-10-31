package com.raddstream.app.repository

import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.network.ApiProvider
import com.raddstream.app.network.models.PostDetail
import com.raddstream.app.network.models.PostsResponse
import com.raddstream.app.network.models.StatsResponse
import com.raddstream.app.network.models.StreamResponse
import com.raddstream.app.network.models.VipRemoteConfig
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
    } catch (e: IOException) {
        DetailProbe(httpStatus = null, bodyClaimsSuccess = null, noAnswer = true)
    } catch (e: IllegalStateException) {
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
