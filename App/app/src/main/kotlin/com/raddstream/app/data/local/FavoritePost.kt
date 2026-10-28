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
    /**
     * `posts.is_animated`, kept from whatever payload saved this row. My List is the one place
     * a viewer's anime lives without a catalog row beside it, and `content_type` alone calls an
     * anime "Series" — this flag is the only word on the wire that says otherwise.
     *
     * Null means "a row this build never asked about", not "not animated": a favourite saved by
     * an older build must keep the label it had rather than be stamped with a fact nobody told
     * it. That is why the column is nullable and why nothing here may default it.
     */
    val isAnimated: Boolean? = null,
    /**
     * The server's per-work subtitles answer, carried for the same reason as [isAnimated]: a
     * tile on My List is rebuilt from this row alone, and dropping the key silently removes the
     * Subtitled chip the viewer saw when they saved it.
     */
    val subtitled: Boolean? = null,
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
        isAnimated = isAnimated,
        subtitled = subtitled,
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
            isAnimated = post.isAnimated,
            subtitled = post.subtitled,
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
            isAnimated = detail.isAnimated,
        )
    }
}
