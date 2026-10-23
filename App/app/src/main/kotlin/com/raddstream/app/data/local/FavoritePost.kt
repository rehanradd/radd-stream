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
) {
    fun toPost(): Post = Post(
        id = id,
        title = title,
        cleanTitle = cleanTitle,
        year = year?.toIntOrNull(),
        contentType = contentType,
        posterUrl = posterUrl,
        imdbRating = imdbRating,
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
        )

        fun fromPostDetail(detail: PostDetail): FavoritePost = FavoritePost(
            id = detail.id,
            title = detail.title,
            cleanTitle = detail.cleanTitle,
            year = detail.year?.toString(),
            contentType = detail.contentType,
            posterUrl = detail.posterUrl,
            imdbRating = detail.imdbRating,
        )
    }
}
