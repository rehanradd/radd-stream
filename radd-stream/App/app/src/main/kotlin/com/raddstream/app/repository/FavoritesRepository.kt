package com.raddstream.app.repository

import com.raddstream.app.data.local.FavoriteDao
import com.raddstream.app.data.local.FavoritePost
import com.raddstream.app.network.models.Post
import com.raddstream.app.network.models.PostDetail
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first

@Singleton
class FavoritesRepository @Inject constructor(
    private val favoriteDao: FavoriteDao,
) {
    fun getAllFavorites(): Flow<List<FavoritePost>> = favoriteDao.getAllFavorites()

    fun isFavorite(postId: Int): Flow<Boolean> = favoriteDao.isFavorite(postId)

    suspend fun addFavorite(post: Post) {
        favoriteDao.insert(FavoritePost.fromPost(post))
    }

    suspend fun addFavorite(detail: PostDetail) {
        favoriteDao.insert(FavoritePost.fromPostDetail(detail))
    }

    suspend fun removeFavorite(postId: Int) {
        favoriteDao.deleteById(postId)
    }

    suspend fun toggleFavorite(detail: PostDetail): Boolean {
        val currentlyFavorite = favoriteDao.isFavorite(detail.id).first()
        if (currentlyFavorite) {
            favoriteDao.deleteById(detail.id)
            return false
        } else {
            favoriteDao.insert(FavoritePost.fromPostDetail(detail))
            return true
        }
    }
}
