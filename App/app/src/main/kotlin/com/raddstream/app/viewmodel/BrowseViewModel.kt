package com.raddstream.app.viewmodel

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.network.friendlyNetworkError
import com.raddstream.app.network.models.Post
import com.raddstream.app.player.AdCadenceGovernor
import com.raddstream.app.player.AdSurface
import com.raddstream.app.repository.CatalogRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * Paging guard for every grid/rail keyed on `post.id`. The server orders `id DESC`, so a
 * scrape landing between page fetches shifts the window and hands the same row back twice;
 * a duplicate key in `LazyVerticalGrid` (or a keyed `MediaRail`) throws. De-duplicating at
 * the paging source keeps one id exactly once per list, first occurrence winning.
 */
internal fun List<Post>.distinctById(): List<Post> = distinctBy { post -> post.id }

/** A paged, single-content-type grid — the destination behind Home's rails and
 *  type jump-off tiles. Phase 7 (M1): the v2 list first, the v1 list as the
 *  fallback — but only on the FIRST page, so a v2 page and a v1 page can never
 *  mix in one list (one row per work vs one row per site-post would show the
 *  same title twice). A later v2 page that fails keeps the load-more error
 *  instead of silently switching sources mid-scroll. */
data class BrowseUiState(
    val items: List<Post> = emptyList(),
    val title: String = "Catalog",
    val loading: Boolean = true,
    val loadingMore: Boolean = false,
    val error: String? = null,
    val page: Int = 1,
    val hasMore: Boolean = false,
)

@HiltViewModel
class BrowseViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    private val catalogRepository: CatalogRepository,
    private val adCadence: AdCadenceGovernor,
    private val adFreeReader: AdFreeReader,
) : ViewModel() {

    private val type: String? = (savedStateHandle.get<String>(ARG_TYPE))?.takeIf { it.isNotBlank() && it != "all" }
    private val _uiState = MutableStateFlow(BrowseUiState(title = titleFor(type)))
    val uiState = _uiState.asStateFlow()
    private var loadJob: Job? = null
    /** The v2 keyset cursor for the next page, or null once the list is on v1 paging. */
    private var v2Cursor: String? = null
    /** True once a page has loaded from v2: the list must never mix sources. */
    private var onV2: Boolean = false

    init {
        load()
    }

    /**
     * How many posters the viewer has passed since last time. The grid's scroll index is the only
     * honest measure of that, and it is reported rather than sampled because the cap is one card
     * per twelve posters: the count has to survive the grid recomposing, paging, and the process
     * being killed with the viewer mid-scroll, so it lands in Room and not in a composable.
     *
     * Crossing the cap asks the governor for the card itself. There is no `loading` state and no
     * slot reserved for an answer: a surface nothing can fill shows nothing, and the viewer scrolls
     * through the space where a card would have been exactly as if there had never been one.
     */
    fun onPostersScrolled(count: Int) {
        if (count <= 0) return
        viewModelScope.launch {
            val adFree = adFreeReader.isAdFree()
            adCadence.onPostersScrolled(count, adFree = adFree)
            adCadence.offer(AdSurface.FEED_CARD, adFree = adFree)
        }
    }

    fun load() {
        loadJob?.cancel()
        loadJob = viewModelScope.launch {
            _uiState.update { it.copy(loading = true, error = null, page = 1) }
            v2Cursor = null
            onV2 = false
            try {
                // Phase 7 (M1): v2 first; an empty v2 page falls back to v1, so a
                // type the v2 side cannot serve reads as its v1 list, not as empty.
                val page = catalogRepository.browseWorksV2(type = type, sort = "trending", limit = PAGE)
                if (page != null && page.posts.isNotEmpty()) {
                    onV2 = true
                    v2Cursor = page.nextCursor
                    _uiState.update {
                        it.copy(
                            items = page.posts.distinctById(),
                            loading = false,
                            page = 1,
                            hasMore = page.hasMore,
                        )
                    }
                    return@launch
                }
                val resp = catalogRepository.getPosts(type = type, page = 1, limit = PAGE)
                _uiState.update {
                    it.copy(
                        items = resp.results.distinctById(),
                        loading = false,
                        page = 1,
                        hasMore = resp.results.size >= PAGE && 1 < resp.totalPages,
                    )
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                _uiState.update { it.copy(loading = false, error = friendlyNetworkError(error, "Could not load this category.")) }
            }
        }
    }

    fun loadMore() {
        val state = _uiState.value
        if (!state.hasMore || state.loading || state.loadingMore) return
        loadJob = viewModelScope.launch {
            _uiState.update { it.copy(loadingMore = true, error = null) }
            val next = state.page + 1
            try {
                if (onV2) {
                    val page = catalogRepository.browseWorksV2(
                        type = type, sort = "trending", limit = PAGE, cursor = v2Cursor,
                    )
                    if (page != null) {
                        v2Cursor = page.nextCursor
                        _uiState.update {
                            it.copy(
                                items = (it.items + page.posts).distinctById(),
                                page = next,
                                hasMore = page.hasMore,
                                loadingMore = false,
                            )
                        }
                        return@launch
                    }
                    throw IllegalStateException("The catalog could not serve the next page.")
                }
                val resp = catalogRepository.getPosts(type = type, page = next, limit = PAGE)
                _uiState.update {
                    it.copy(
                        items = (it.items + resp.results).distinctById(),
                        page = next,
                        hasMore = resp.results.size >= PAGE && next < resp.totalPages,
                        loadingMore = false,
                    )
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                _uiState.update { it.copy(loadingMore = false, error = friendlyNetworkError(error, "Could not load more.")) }
            }
        }
    }

    private companion object {
        const val PAGE = 30
        const val ARG_TYPE = "type"
        fun titleFor(type: String?): String = when (type) {
            null -> "Recently added"
            "movie" -> "Movies"
            "series" -> "Series"
            // `anime` is a filter, not a stored `content_type`: animation is a flag on
            // the post, and the server answers the chip from that flag.
            "anime" -> "Anime"
            "complete_season" -> "Complete seasons"
            "ongoing_season" -> "Ongoing seasons"
            else -> "Catalog"
        }
    }
}
