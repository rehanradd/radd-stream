package com.raddstream.app.repository

import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.network.ApiProvider
import com.raddstream.app.network.models.PostDetail
import com.raddstream.app.network.models.PostsResponse
import com.raddstream.app.network.models.StatsResponse
import com.raddstream.app.network.models.StreamResponse
import javax.inject.Inject
import javax.inject.Singleton

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
        page: Int = 1,
        limit: Int = 20,
    ): PostsResponse = apiProvider.current().getPosts(
        query = query?.takeIf(String::isNotBlank),
        type = type,
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

    suspend fun resolveStream(sourceId: Int): StreamResponse =
        apiProvider.current().resolveStream(sourceId, redirect = "0")
}
