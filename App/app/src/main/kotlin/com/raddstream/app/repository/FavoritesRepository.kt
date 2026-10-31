package com.raddstream.app.repository

import com.raddstream.app.data.local.FavoriteDao
import com.raddstream.app.data.local.FavoritePost
import com.raddstream.app.data.local.UnavailableWorkDao
import com.raddstream.app.data.local.UnavailableWorkEntity
import com.raddstream.app.network.models.Post
import com.raddstream.app.network.models.PostDetail
import com.raddstream.app.sync.SyncAccountRepository
import com.raddstream.app.sync.SyncAck
import com.raddstream.app.viewmodel.AdultPolicy
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
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
    private val unavailableDao: UnavailableWorkDao,
    private val catalogRepository: CatalogRepository,
    private val syncAccountRepository: SyncAccountRepository,
) {

    /** App-lifetime by design: a favorite report outlives the screen that made the tap. */
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    fun getAllFavorites(): Flow<List<FavoritePost>> = favoriteDao.getAllFavorites()

    fun isFavorite(postId: Int): Flow<Boolean> = favoriteDao.isFavorite(postId)

    /**
     * The ids this device has been refused, as a Flow so a cached surface re-filters itself the
     * moment an answer arrives rather than on the next navigation.
     */
    fun observeRefusedIds(): Flow<Set<Int>> =
        unavailableDao.observeRefusedIds().map { it.toSet() }

    suspend fun addFavorite(post: Post) {
        favoriteDao.insert(FavoritePost.fromPost(post))
        // The row arrived on a live catalog page, so the server listed it in this very response.
        // Recording that answer is what lets a previously-refused id come back on its own.
        recordAnswer(post.id, post.is18Plus, AdultPolicy.ServerAnswer.LISTED)
        report(post.id, post.workRef, removal = false)
    }

    suspend fun addFavorite(detail: PostDetail) {
        favoriteDao.insert(FavoritePost.fromPostDetail(detail))
        recordAnswer(detail.id, detail.is18Plus, AdultPolicy.ServerAnswer.LISTED)
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

    // ── The server's answer about a row this device kept ──────────────────────

    /**
     * Write down what one round-trip established. `LISTED` clears the refusal (a served id may not
     * stay hidden by an older answer), `GONE` records it, and `UNANSWERED` writes nothing at all —
     * not even the stamp, so a row probed during an outage stays due for the next pass instead of
     * going quiet for a TTL on the strength of a request that never reached anybody.
     */
    suspend fun recordAnswer(postId: Int, flag: Boolean?, answer: AdultPolicy.ServerAnswer) {
        when (answer) {
            AdultPolicy.ServerAnswer.LISTED -> {
                unavailableDao.clear(postId)
                favoriteDao.recordAnswer(postId, flag, System.currentTimeMillis())
            }

            AdultPolicy.ServerAnswer.GONE -> {
                favoriteDao.recordAnswer(postId, flag, System.currentTimeMillis())
                unavailableDao.record(
                    UnavailableWorkEntity(
                        postId = postId,
                        refusedAt = System.currentTimeMillis(),
                        reason = UnavailableWorkEntity.REASON_CATALOG,
                    ),
                )
            }

            AdultPolicy.ServerAnswer.UNANSWERED -> Unit
        }
    }

    /** A `/api/v1/stream` refusal about a handle a saved row points at. Same ledger, other door. */
    suspend fun recordStreamRefusal(postId: Int) {
        favoriteDao.findById(postId)?.let { row ->
            favoriteDao.recordAnswer(row.id, row.is18Plus, System.currentTimeMillis())
        }
        unavailableDao.record(
            UnavailableWorkEntity(
                postId = postId,
                refusedAt = System.currentTimeMillis(),
                reason = UnavailableWorkEntity.REASON_STREAM,
            ),
        )
    }

    /**
     * Re-ask the server about the saved rows whose last answer has aged out, and write down what it
     * says. Returns how many rows were actually asked, so a caller can tell a pass that did nothing
     * from one that hid something.
     *
     * The bound is the point: [AdultPolicy.MAX_REVALIDATION_CHECKS_PER_PASS] stalest rows per pass,
     * because this same server puts every request in a token bucket and a screen that walked a
     * hundred-row library on each visit would be throttled by its own compliance check. Rows with
     * no answer yet sort first, so an install upgrading into this build gets checked before one
     * that has been checked for weeks.
     */
    suspend fun revalidateSavedRows(): Int {
        val rows = favoriteDao.favoritesOnce()
        val due = AdultPolicy.selectForRevalidation(
            rows = rows,
            checkedAtOf = FavoritePost::checkedAt,
            nowMs = System.currentTimeMillis(),
        )
        for (row in due) {
            val probe = catalogRepository.probePost(row.id)
            recordAnswer(
                postId = row.id,
                flag = null,
                answer = AdultPolicy.serverAnswerFor(
                    httpStatus = probe.httpStatus,
                    bodyClaimsSuccess = probe.bodyClaimsSuccess,
                    noAnswer = probe.noAnswer,
                ),
            )
        }
        return due.size
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
