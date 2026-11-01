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
     * The adult flag, as the server ever stated it for this id — and on today's public edge it
     * never does. Measured 2026-11-01 against the live deployment: `post_brief` and `post_detail`
     * both send `is_animated` and neither sends `is_18_plus`, which is not an oversight but the
     * design — a flagged row is *invisible* on the public routes, not labelled on them, so a row
     * that arrives at all arrives unflagged. That is why this column exists without a wire field
     * beside it: modelling `is_18_plus` on [Post] would be a permanently-null phantom, and the
     * app's own history (§6 of `App/AGENTS.md`) says a field the API never returns is a field
     * somebody will one day render.
     *
     * So this is the strict half of the rule, written only by
     * [com.raddstream.app.data.local.FavoriteDao.recordAnswer] when a payload really does carry a
     * flag (an operator-port probe, or a future projection that publishes the key), and read by
     * [com.raddstream.app.viewmodel.AdultPolicy] wherever a cached row is drawn. The half that
     * fires against the server this app can reach is [checkedAt] plus `unavailable_works`: an id
     * the public route 404s is, by that route's own design, indistinguishable from a flagged one.
     *
     * Null is not false. An older row keeps the listing it had rather than be stamped with a fact
     * nobody sent — and nothing may give this a default.
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
