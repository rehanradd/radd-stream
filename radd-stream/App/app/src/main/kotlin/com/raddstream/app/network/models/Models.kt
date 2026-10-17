package com.raddstream.app.network.models

import com.google.gson.annotations.SerializedName

/** Exact response shape returned by GET /api/v1/posts. */
data class PostsResponse(
    val page: Int = 1,
    val limit: Int = 20,
    val total: Int = 0,
    @SerializedName("total_pages")
    val totalPages: Int = 1,
    val results: List<Post> = emptyList(),
)

/** Metadata-only catalog row. The backend may return a number or a year range. */
data class Post(
    val id: Int,
    val title: String,
    @SerializedName("clean_title")
    val cleanTitle: String? = null,
    val year: String? = null,
    @SerializedName("content_type")
    val contentType: String? = null,
    @SerializedName("poster_url")
    val posterUrl: String? = null,
    @SerializedName("imdb_rating")
    val imdbRating: String? = null,
    @SerializedName("source_site")
    val sourceSite: String? = null,
)

/** Response returned by GET /api/v1/posts/{id} */
data class PostDetailResponse(
    val success: Boolean = false,
    val data: PostDetail? = null,
    val error: String? = null,
)

/** Full details of a post including its releases and stream sources. */
data class PostDetail(
    val id: Int,
    val title: String,
    @SerializedName("clean_title")
    val cleanTitle: String? = null,
    val year: String? = null,
    @SerializedName("content_type")
    val contentType: String? = null,
    val seasons: String? = null,
    @SerializedName("poster_url")
    val posterUrl: String? = null,
    @SerializedName("imdb_rating")
    val imdbRating: String? = null,
    @SerializedName("imdb_id")
    val imdbId: String? = null,
    @SerializedName("tmdb_id")
    val tmdbId: String? = null,
    val genres: String? = null,
    val synopsis: String? = null,
    @SerializedName("source_site")
    val sourceSite: String? = null,
    val industry: String? = null,
    val country: String? = null,
    val language: String? = null,
    val releases: List<ReleaseDetail> = emptyList(),
)

/** A release group/variant for a post. */
data class ReleaseDetail(
    val id: Int,
    @SerializedName("post_id")
    val postId: Int = 0,
    val quality: String? = null,
    val resolution: String? = null,
    val codec: String? = null,
    val audio: String? = null,
    val size: String? = null,
    @SerializedName("season_number")
    val seasonNumber: Int? = null,
    @SerializedName("episode_number")
    val episodeNumber: Int? = null,
    @SerializedName("episode_title")
    val episodeTitle: String? = null,
    val sources: List<SourceDetail> = emptyList(),
)

/** Direct or resolved stream source link. */
data class SourceDetail(
    val id: Int,
    @SerializedName("release_id")
    val releaseId: Int = 0,
    @SerializedName("source_name")
    val sourceName: String? = null,
    val service: String? = null,
    @SerializedName("source_url")
    val sourceUrl: String? = null,
    @SerializedName("final_url")
    val finalUrl: String? = null,
    val status: String? = null,
    @SerializedName("is_resumable")
    val isResumable: Int? = null,
    @SerializedName("is_temporary")
    val isTemporary: Int? = null,
)

/** Response from GET /api/v1/stream?id=...&redirect=0 */
data class StreamResponse(
    val success: Boolean = false,
    val url: String? = null,
    val service: String? = null,
    @SerializedName("is_temporary")
    val isTemporary: Int? = null,
    val error: String? = null,
)

/** Exact response shape returned by GET /api/v1/stats. */
data class StatsResponse(
    val posts: Int = 0,
    val releases: Int = 0,
    val sources: Int = 0,
    @SerializedName("active_sources")
    val activeSources: Int? = null,
    @SerializedName("resumable_sources")
    val resumableSources: Int? = null,
    @SerializedName("temporary_sources")
    val temporarySources: Int? = null,
)
