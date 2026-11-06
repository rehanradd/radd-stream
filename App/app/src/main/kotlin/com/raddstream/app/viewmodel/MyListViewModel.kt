package com.raddstream.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.data.local.FavoritePost
import com.raddstream.app.data.local.WatchHistoryDao
import com.raddstream.app.network.models.Post
import com.raddstream.app.repository.CatalogRepository
import com.raddstream.app.repository.FavoritesRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

enum class ListSort(val label: String) {
    RECENT("Recently added"),
    TITLE("Title A–Z"),
    UNWATCHED("Unwatched first"),
}

data class MyListUiState(
    val favorites: List<Post> = emptyList(),
    val sort: ListSort = ListSort.RECENT,
    val isLoading: Boolean = false,
    /**
     * Rows this device still stores and this build may not draw. Counted, never listed: the
     * viewer's list did not shrink, the server's answer about it changed.
     */
    val hiddenCount: Int = 0,
    /** The three most-covered titles in the catalog, for the empty state. Empty when unloaded. */
    val popular: List<Post> = emptyList(),
    /** The title just removed, so the screen can offer Undo. Null when nothing is waiting. */
    val removedTitle: String? = null,
) {
    /** [AdultPolicy.hiddenNotice] — a number, because a notice naming a hidden title is a list of one. */
    val hiddenNotice: String? get() = AdultPolicy.hiddenNotice(hiddenCount)
}

/**
 * The My List order, as one pure function: recently-added and title are the
 * old orders; unwatched-first puts titles with no finished watch row ahead
 * of finished ones, then recently-added inside each half. "Finished" is the
 * rail's own end-guard, via [watchedTitles] — a half-watched title still
 * counts as unwatched, and a series counts as watched when any episode of
 * it is finished.
 */
fun sortMyList(
    posts: List<FavoritePost>,
    sort: ListSort,
    watchedTitles: Set<String>,
): List<FavoritePost> {
    fun isWatched(post: FavoritePost) = (post.cleanTitle ?: post.title) in watchedTitles
    return when (sort) {
        ListSort.RECENT -> posts.sortedByDescending { it.addedAt }
        ListSort.TITLE -> posts.sortedBy { (it.cleanTitle ?: it.title).lowercase() }
        ListSort.UNWATCHED -> posts.sortedWith(
            compareBy<FavoritePost> { isWatched(it) }.thenByDescending { it.addedAt },
        )
    }
}

@HiltViewModel
class MyListViewModel @Inject constructor(
    private val favoritesRepository: FavoritesRepository,
    private val watchHistoryDao: WatchHistoryDao,
    private val catalogRepository: CatalogRepository,
) : ViewModel() {

    private val sortFlow = MutableStateFlow(ListSort.RECENT)
    private val popularFlow = MutableStateFlow<List<Post>>(emptyList())
    private val removedTitleFlow = MutableStateFlow<String?>(null)
    private var lastRemoved: Post? = null
    private var popularLoaded = false

    val uiState: StateFlow<MyListUiState> = combine(
        favoritesRepository.getAllFavorites(),
        favoritesRepository.observeRefusedIds(),
        sortFlow,
        watchHistoryDao.observeDurations(),
        popularFlow,
        removedTitleFlow,
    ) { list, refused, sort, history, popular, removedTitle ->
        // The stored rows are filtered here, before anything sorts or maps them, so no later step
        // can be handed the unfiltered list by accident. `is18Plus` is the strict half and is null
        // for every row on today's wire; the refusal ledger is the half that fires against a public
        // route that 404s a flagged id exactly as it 404s an absent one.
        val visible = AdultPolicy.listableRows(
            rows = list,
            flagOf = FavoritePost::is18Plus,
            refusedOf = { it.id in refused },
        )
        val sorted = sortMyList(visible, sort, watchedTitles(history))
        MyListUiState(
            favorites = sorted.map(FavoritePost::toPost),
            sort = sort,
            isLoading = false,
            hiddenCount = list.size - visible.size,
            popular = popular,
            removedTitle = removedTitle,
        )
    }.stateIn(
        scope = viewModelScope,
        started = SharingStarted.WhileSubscribed(5_000),
        initialValue = MyListUiState(isLoading = true),
    )

    init {
        viewModelScope.launch {
            // One bounded pass per visit: at most
            // [AdultPolicy.MAX_REVALIDATION_CHECKS_PER_PASS] rows, and only rows whose last answer
            // has aged out, so opening My List a second time the same day asks nothing. What it
            // learns lands on the ledger, which re-emits [uiState] through the combine above — a
            // row the server has since refused leaves the grid while the viewer is looking at it.
            //
            // A pass that cannot finish may not cost the viewer the list they came for: the rows on
            // screen are already filtered by whatever the ledger holds, and the next visit tries
            // again. [com.raddstream.app.repository.CatalogRepository.probePost] reports a transport
            // failure as an absence of an answer rather than as a refusal, so the ordinary outage
            // never reaches this catch; the catch is for a database or wiring fault.
            try {
                favoritesRepository.revalidateSavedRows()
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                // The ledger keeps what it held. Nothing here may hide or un-hide a row.
            }
        }
        viewModelScope.launch {
            // The empty state needs something to point at, and the only honest
            // "popular" this app can name is the server's own trending order —
            // most prints and mirrors first. Loaded once, only when the visible
            // list is empty, and never allowed to fail the screen: no server,
            // no titles, the text-only empty state stands.
            uiState.collect { state ->
                if (!state.isLoading && state.favorites.isEmpty() && !popularLoaded) {
                    popularLoaded = true
                    popularFlow.value = runCatching {
                        catalogRepository.getPosts(sort = "trending", page = 1, limit = 3).results
                    }.getOrNull() ?: emptyList()
                }
            }
        }
    }

    fun setSort(sort: ListSort) {
        sortFlow.value = sort
    }

    /**
     * One tap removes the row at once — no held tile, no confirm dialog.
     * The row is only ever one Undo away: the removed post is kept in memory
     * and [undoRemoval] puts it back, and the snackbar is the way back.
     */
    fun remove(postId: Int) {
        val post = uiState.value.favorites.firstOrNull { it.id == postId } ?: return
        lastRemoved = post
        removedTitleFlow.value = post.displayTitle
        viewModelScope.launch { favoritesRepository.removeFavorite(postId) }
    }

    fun undoRemoval() {
        val post = lastRemoved ?: return
        lastRemoved = null
        removedTitleFlow.value = null
        viewModelScope.launch { favoritesRepository.addFavorite(post) }
    }

    fun clearRemovedNotice() {
        lastRemoved = null
        removedTitleFlow.value = null
    }
}
