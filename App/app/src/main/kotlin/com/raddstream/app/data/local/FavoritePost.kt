package com.raddstream.app.data.local

import androidx.room.Entity
import androidx.room.PrimaryKey
import com.raddstream.app.network.models.Post
import com.raddstream.app.network.models.PostDetail

@Entity(tableName = "favorite_posts")
data class FavoritePost(
    @PrimaryKey
    val id: Int,
    val title: String,
    val cleanTitle: String? = null,
    val year: String? = null,
    val contentType: String? = null,
    val posterUrl: String? = null,
    val imdbRating: String? = null,
    val addedAt: Long = System.currentTimeMillis(),
    /**
     * The server-minted handle for this work, exactly as the catalog payload delivered it.
     * It is the ONLY thing this app may name a work with on the sync surface, and it is
     * null for every row saved by a build that never had one, and for a row saved from a
     * server that sent none — the live v1 catalog does send it (measured 2026-10-28), but a
     * favourite kept before that, or from an older deployment, has nothing to send. A null
     * here means "this favorite stays on the device", and no code below may guess a value
     * for it.
     */
    val workRef: String? = null,
    /**
     * Wall-clock millis of the last write the server accepted for this row, or null while
     * it is local-only. A sync push retries rows whose stamp is missing without touching
     * ones already on the library, so a flaky evening costs a retry, not a duplicate.
     */
    val syncedAt: Long? = null,
) {
    /** True when this row CAN be named on the sync surface — not "true when it should be". */
    val syncable: Boolean get() = !workRef.isNullOrBlank()

    fun toPost(): Post = Post(
        id = id,
        title = title,
        cleanTitle = cleanTitle,
        year = year?.toIntOrNull(),
        contentType = contentType,
        posterUrl = posterUrl,
        imdbRating = imdbRating,
        workRef = workRef,
    )

    companion object {
        fun fromPost(post: Post): FavoritePost = FavoritePost(
            id = post.id,
            title = post.title,
            cleanTitle = post.cleanTitle,
            year = post.year?.toString(),
            contentType = post.contentType,
            posterUrl = post.posterUrl,
            imdbRating = post.imdbRating,
            workRef = post.workRef,
        )

        fun fromPostDetail(detail: PostDetail): FavoritePost = FavoritePost(
            id = detail.id,
            title = detail.title,
            cleanTitle = detail.cleanTitle,
            year = detail.year?.toString(),
            contentType = detail.contentType,
            posterUrl = detail.posterUrl,
            imdbRating = detail.imdbRating,
            workRef = detail.workRef,
        )
    }
}
