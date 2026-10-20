package com.raddstream.app.network

import com.raddstream.app.network.models.PostDetailResponse
import com.raddstream.app.network.models.PostsResponse
import com.raddstream.app.network.models.StatsResponse
import com.raddstream.app.network.models.StreamResponse
import retrofit2.http.GET
import retrofit2.http.Path
import retrofit2.http.Query

/**
 * Retrofit interface mirroring the radd-stream REST API v1.
 * Base URL is configured at runtime from DataStore (user's server URL).
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

    /** GET /api/v1/stream — resolve live stream link for a given source ID. */
    @GET("api/v1/stream")
    suspend fun resolveStream(
        @Query("id") sourceId: Int,
        @Query("redirect") redirect: String = "0",
    ): StreamResponse

    /** GET /api/v1/stats — catalog and diagnostic counts. */
    @GET("api/v1/stats")
    suspend fun getStats(): StatsResponse
}
