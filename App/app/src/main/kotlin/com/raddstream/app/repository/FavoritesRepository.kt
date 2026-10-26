package com.raddstream.app.repository

import com.raddstream.app.data.local.FavoriteDao
import com.raddstream.app.data.local.FavoritePost
import com.raddstream.app.network.models.Post
import com.raddstream.app.network.models.PostDetail
import com.raddstream.app.sync.SyncAccountRepository
import com.raddstream.app.sync.SyncAck
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/**
 * The saved list. Local Room is the source of truth — for what My List shows, for what the
 * detail heart reflects, and for what survives a flight mode — exactly as it was before an
 * account existed.
 *
 * The one thing the sync account adds: after a local write that already succeeded, this
 * class also *tries* to tell the server about it, on its own scope, and drops the attempt on
 * the floor if it fails. That ordering is the whole design:
 *
 *  - the local row is inserted or deleted BEFORE any network is touched, so a saved title
 *    cannot be lost to a dead server, and a slow one cannot hold the screen's state hostage;
 *  - the report runs in [scope] rather than in the caller's suspend chain, so a tap answers
 *    in the same number of frames whether or not an account is configured;
 *  - when no key is stored, [SyncAccountRepository] short-circuits every call before it
 *    builds a request, so a signed-out install does the same Room writes it always did and
 *    talks to nobody.
 *
 * Provenance: a report names a work with the server's own minted handle, or not at all
 * ([com.raddstream.app.sync.SyncContract.canNameOnServer]). A title or a row id is never a
 * legal way to point at a work on that surface, and a favorite saved from today's v1 catalog
 * has no handle, so it stays on this device — which is the honest outcome, not a bug to
 * paper over by inventing an identifier.
 */
@Singleton
class FavoritesRepository @Inject constructor(
    private val favoriteDao: FavoriteDao,
    private val syncAccountRepository: SyncAccountRepository,
) {

    /** App-lifetime by design: a favorite report outlives the screen that made the tap. */
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    fun getAllFavorites(): Flow<List<FavoritePost>> = favoriteDao.getAllFavorites()

    fun isFavorite(postId: Int): Flow<Boolean> = favoriteDao.isFavorite(postId)

    suspend fun addFavorite(post: Post) {
        favoriteDao.insert(FavoritePost.fromPost(post))
        report(post.id, post.workRef, removal = false)
    }

    suspend fun addFavorite(detail: PostDetail) {
        favoriteDao.insert(FavoritePost.fromPostDetail(detail))
        report(detail.id, detail.workRef, removal = false)
    }

    suspend fun removeFavorite(postId: Int) {
        val row = favoriteDao.findById(postId)
        favoriteDao.deleteById(postId)
        // The handle is read before the row goes away: afterwards there is nothing to name.
        report(postId, row?.workRef, removal = true)
    }

    suspend fun toggleFavorite(detail: PostDetail): Boolean {
        val currentlyFavorite = favoriteDao.isFavorite(detail.id).first()
        if (currentlyFavorite) {
            removeFavorite(detail.id)
            return false
        }
        addFavorite(detail)
        return true
    }

    /** Best effort, off the caller's thread, after the local write is already durable. */
    private fun report(postId: Int, workRef: String?, removal: Boolean) {
        val ref = workRef?.takeIf { it.isNotBlank() } ?: return
        scope.launch {
            val ack = if (removal) {
                syncAccountRepository.removeRemoteFavorite(ref)
            } else {
                syncAccountRepository.pushFavorite(ref)
            }
            if (ack == SyncAck.WRITTEN && !removal) {
                favoriteDao.markSynced(postId, System.currentTimeMillis())
            }
        }
    }
}
