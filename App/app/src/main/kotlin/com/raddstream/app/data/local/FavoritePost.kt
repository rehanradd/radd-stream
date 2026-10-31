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
    /**
     * `posts.is_18_plus` — stored, because a saved row is the one place this app renders a catalog
     * row it cannot re-ask about in the same frame. Null means the server never told us, which on
     * today's public edge is *always*: the flag is not in `post_brief` or `post_detail`, and the
     * un-redacted `full` view is switched on per server instance, never per request
     * (`Fast_Fetch/viewer.py:3109`/`:3465`). So this column is the strict half of the rule and
     * [checkedAt] plus `unavailable_works` is the half that actually fires. Null is not false: an
     * older row must keep the listing it had rather than be stamped with a fact nobody sent.
     */
    val is18Plus: Boolean? = null,
    /**
     * Wall-clock millis of the last time the server answered about this id — served or refused,
     * either is an answer. Null means "never asked by this build", which makes the row the first
     * candidate for a revalidation pass rather than the last.
     */
    val checkedAt: Long? = null,
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
        is18Plus = is18Plus,
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
            is18Plus = post.is18Plus,
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
            is18Plus = detail.is18Plus,
        )
    }
}
