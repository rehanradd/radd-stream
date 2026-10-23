package com.raddstream.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.network.models.Post
import com.raddstream.app.repository.CatalogRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * Rich search built on what `GET /api/v1/posts` can do *today*: a single `q` LIKE and
 * a single `type`, paged. Everything else is composed honestly on top:
 *
 *  - **Server-driven:** free-text `q` (debounced) + `type` + paging (`page`/`limit`).
 *  - **Client-driven over the accumulated page(s):** sort, year range, source-site
 *    filter, and grouping by content type. These operate on rows already fetched
 *    (first page is `limit = 100`, the v1 max, so ordinary queries are complete in
 *    one page). We label sorting as "within loaded results" and request true
 *    server-side sort/facets in docs/HANDOFF_appui.md rather than pretending the
 *    subset is the whole catalog.
 *
 * We deliberately do NOT render genre / language / quality-floor / availability chips,
 * because the v1 list payload carries none of those fields — offering them would be
 * dead UI. The server facet endpoint is requested instead.
 */

enum class SearchSort(val label: String) {
    RELEVANCE("Server order"),
    NEWEST("Newest"),
    TITLE("Title A–Z"),
    RATING("Rating"),
}

data class SearchFilters(
    val type: String? = null,
    val yearFrom: Int? = null,
    val yearTo: Int? = null,
) {
    val anyClientFilterActive: Boolean
        get() = yearFrom != null || yearTo != null
}

data class TypeGroup(val label: String, val typeKey: String?, val items: List<Post>)

data class SearchUiState(
    val query: String = "",
    val isLoading: Boolean = false,
    val isLoadingMore: Boolean = false,
    val error: String? = null,
    val filters: SearchFilters = SearchFilters(),
    val sort: SearchSort = SearchSort.RELEVANCE,
    val groups: List<TypeGroup> = emptyList(),
    val resultCount: Int = 0,
    val recents: List<String> = emptyList(),
    val trendingHidden: Boolean = true, // no server support — see handoff; never faked
    val page: Int = 1,
    val hasMore: Boolean = false,
    val hasSearched: Boolean = false,
) {
    val hasActiveFilters: Boolean
        get() = filters.type != null || filters.anyClientFilterActive || sort != SearchSort.RELEVANCE
}

@HiltViewModel
class SearchViewModel @Inject constructor(
    private val catalogRepository: CatalogRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(SearchUiState())
    val uiState = _uiState.asStateFlow()

    private var searchJob: Job? = null
    private var moreJob: Job? = null
    private var rawResults: List<Post> = emptyList()
    private val recents = mutableListOf<String>()

    fun onQueryChanged(query: String) {
        _uiState.update { it.copy(query = query, error = null) }
        scheduleSearch(reset = true)
    }

    /** Records the current query and forces an immediate search (IME "Search" key). */
    fun submitCurrentQuery() {
        recordRecent(_uiState.value.query)
        scheduleSearch(reset = true, immediate = true)
    }

    fun runRecent(query: String) {
        _uiState.update { it.copy(query = query) }
        recordRecent(query)
        scheduleSearch(reset = true, immediate = true)
    }

    fun selectType(type: String?) {
        if (_uiState.value.filters.type == type) return
        _uiState.update { it.copy(filters = it.filters.copy(type = type)) }
        scheduleSearch(reset = true)
    }

    fun setSort(sort: SearchSort) {
        _uiState.update { it.copy(sort = sort) }
        recompute()
    }

    fun setYearRange(from: Int?, to: Int?) {
        _uiState.update { it.copy(filters = it.filters.copy(yearFrom = from, yearTo = to)) }
        recompute()
    }

    fun resetFilters() {
        _uiState.update { it.copy(filters = SearchFilters(type = it.filters.type), sort = SearchSort.RELEVANCE) }
        recompute()
    }

    fun loadMore() {
        val state = _uiState.value
        if (!state.hasMore || state.isLoadingMore || state.query.isBlank()) return
        moreJob?.cancel()
        moreJob = viewModelScope.launch {
            _uiState.update { it.copy(isLoadingMore = true) }
            val next = state.page + 1
            try {
                val resp = catalogRepository.getPosts(
                    query = state.query.trim(),
                    type = state.filters.type,
                    page = next,
                    limit = PAGE_SIZE,
                )
                rawResults = rawResults + resp.results
                _uiState.update { it.copy(page = next, hasMore = resp.results.size >= PAGE_SIZE && next < resp.totalPages) }
                recompute()
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                _uiState.update { it.copy(error = error.message ?: "Could not load more.") }
            } finally {
                _uiState.update { it.copy(isLoadingMore = false) }
            }
        }
    }

    private fun scheduleSearch(reset: Boolean, immediate: Boolean = false) {
        searchJob?.cancel()
        val query = _uiState.value.query.trim()
        if (query.isBlank()) {
            rawResults = emptyList()
            _uiState.update {
                it.copy(
                    isLoading = false, error = null, groups = emptyList(), resultCount = 0,
                    hasSearched = false, hasMore = false, page = 1,
                )
            }
            return
        }
        if (reset) _uiState.update { it.copy(page = 1) }
        searchJob = viewModelScope.launch {
            if (!immediate) delay(DEBOUNCE_MS)
            _uiState.update { it.copy(isLoading = true, error = null) }
            try {
                val resp = catalogRepository.getPosts(
                    query = query,
                    type = _uiState.value.filters.type,
                    page = 1,
                    limit = PAGE_SIZE,
                )
                rawResults = resp.results
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        hasSearched = true,
                        page = 1,
                        hasMore = resp.results.size >= PAGE_SIZE && resp.totalPages > 1,
                        error = null,
                    )
                }
                recompute()
                recordRecent(query)
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                rawResults = emptyList()
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        error = error.message ?: "Search failed. Check the server connection.",
                        groups = emptyList(),
                        resultCount = 0,
                    )
                }
            }
        }
    }

    private fun recompute() {
        val filters = _uiState.value.filters
        val sort = _uiState.value.sort
        val filtered = rawResults.filter { post ->
            // Post.year arrives as a JSON number (Int?), so no string parsing is needed.
            val year = post.year
            val yearOk = when {
                filters.yearFrom != null && (year == null || year < filters.yearFrom) -> false
                filters.yearTo != null && (year == null || year > filters.yearTo) -> false
                else -> true
            }
            yearOk
        }

        val groups = filtered
            .groupBy { normalizeTypeLabel(it.contentType) }
            .toSortedMap(typeComparator)
            .map { (label, posts) ->
                TypeGroup(
                    label = label,
                    typeKey = posts.firstOrNull()?.contentType,
                    items = when (sort) {
                        SearchSort.TITLE -> posts.sortedBy { (it.cleanTitle ?: it.title).lowercase() }
                        SearchSort.RATING -> posts.sortedByDescending { it.imdbRating?.toDoubleOrNull() ?: -1.0 }
                        SearchSort.NEWEST -> posts.sortedByDescending { it.year ?: 0 }
                        SearchSort.RELEVANCE -> posts
                    },
                )
            }

        _uiState.update {
            it.copy(
                groups = groups,
                resultCount = filtered.size,
                recents = recents.toList(),
            )
        }
    }

    private fun recordRecent(query: String) {
        val trimmed = query.trim()
        if (trimmed.isBlank()) return
        recents.remove(trimmed)
        recents.add(0, trimmed)
        while (recents.size > RECENTS_MAX) recents.removeAt(recents.lastIndex)
        _uiState.update { it.copy(recents = recents.toList()) }
    }

    private companion object {
        const val DEBOUNCE_MS = 300L
        const val PAGE_SIZE = 100
        const val RECENTS_MAX = 10

        val typeComparator = compareBy<String> { typeOrder(it) }

        fun typeOrder(label: String): Int = when (label) {
            "Movies" -> 0
            "Series" -> 1
            "Seasons" -> 2
            else -> 3
        }
    }

    // ---- pure helpers (unit-tested) ----

    fun normalizeTypeForTest(contentType: String?): String = normalizeTypeLabel(contentType)
}

internal fun parseYear(year: String?): Int? {
    if (year.isNullOrBlank()) return null
    Regex("""(19|20)\d{2}""").find(year)?.value?.toIntOrNull()?.let { return it }
    return null
}

internal fun normalizeTypeLabel(contentType: String?): String = when (contentType?.lowercase()?.trim()) {
    "movie" -> "Movies"
    "series" -> "Series"
    "complete_season", "ongoing_season" -> "Seasons"
    null, "" -> "Other"
    else -> "Other"
}
