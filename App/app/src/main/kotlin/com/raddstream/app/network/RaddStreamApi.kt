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
}
