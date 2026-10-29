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

/** A paged, single-content-type grid — the destination behind Home's rails and
 *  type jump-off tiles. Uses only `GET /api/v1/posts` (`type` + `page` + `limit`). */
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
            try {
                val resp = catalogRepository.getPosts(type = type, page = 1, limit = PAGE)
                _uiState.update {
                    it.copy(
                        items = resp.results,
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
                val resp = catalogRepository.getPosts(type = type, page = next, limit = PAGE)
                _uiState.update {
                    it.copy(
                        items = it.items + resp.results,
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
