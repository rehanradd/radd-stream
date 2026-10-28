package com.raddstream.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.data.normalizeSearchRecents
import com.raddstream.app.network.friendlyNetworkError
import com.raddstream.app.network.models.Post
import com.raddstream.app.network.models.WorkType
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
 * Rich search built on what `GET /api/v1/posts` can do today.
 *
 *  - **Server-driven:** free-text `q` (debounced), `type`, and the industry /
 *    genre / quality / sort facets. The backend composes them into SQL before
 *    paging, so a chip narrows the whole catalog rather than only the rows this
 *    device has already loaded.
 *  - **Client-driven over the accumulated page(s):** the year range and the
 *    final per-group ordering. Grouping by content type is presentation only.
 *
 * Quality facets are an existence test over `releases.quality` on the server
 * (`4K` also matches 2160p/UHD). That is why the chip works even though the v1
 * list row itself carries no quality column.
 *
 * The default sort is [SearchSort.NEWEST], which the server answers from its own
 * index (`p.id DESC`). The alternatives are all measured on the live catalog as
 * several seconds per page — `trending`/`rating`/`title` each force a scan over the
 * whole result set before paging — so they stay opt-in and the default never pays
 * for them.
 *
 * "Most Sources" is named for its actual input: the ledger has no play-count column,
 * so the server ranks by how many prints and mirrors the catalog holds for a work.
 * Calling it "Trending" would promise popularity data that does not exist.
 */
enum class SearchSort(val label: String, val wireValue: String) {
    NEWEST("Newest", "newest"),
    MOST_SOURCES("Most Sources", "trending"),
    HIGHEST_IMDB("Highest IMDb", "rating"),
    TITLE("Title A–Z", "title");

    companion object {
        val DEFAULT = NEWEST
    }
}

enum class IndustryFilter(val label: String, val wireValue: String?) {
    ALL("All", null),
    BOLLYWOOD("Bollywood", "bollywood"),
    HOLLYWOOD("Hollywood", "hollywood"),
    PAKISTANI("Pakistani", "pakistani"),
    SOUTH_INDIAN("South Indian", "south_indian"),
    ANIME("Anime", "anime"),
}

enum class GenreFilter(val label: String, val wireValue: String?) {
    ALL("All", null),
    ACTION("Action", "action"),
    COMEDY("Comedy", "comedy"),
    DRAMA("Drama", "drama"),
    SCI_FI("Sci-Fi", "sci-fi"),
    HORROR("Horror", "horror"),
}

enum class QualityFilter(val label: String, val wireValue: String?) {
    ALL("All", null),
    UHD_4K("4K", "4k"),
    FULL_HD("1080p", "1080p"),
    HD("720p", "720p"),
}

data class SearchFilters(
    val type: String? = null,
    val industry: IndustryFilter = IndustryFilter.ALL,
    val genre: GenreFilter = GenreFilter.ALL,
    val quality: QualityFilter = QualityFilter.ALL,
    val yearFrom: Int? = null,
    val yearTo: Int? = null,
) {
    val anyServerFilterActive: Boolean
        get() = industry != IndustryFilter.ALL ||
            genre != GenreFilter.ALL ||
            quality != QualityFilter.ALL

    val anyClientFilterActive: Boolean
        get() = yearFrom != null || yearTo != null
}

data class TypeGroup(val label: String, val typeKey: String?, val items: List<Post>)

/**
 * How many results to claim, in words the viewer can trust.
 *
 * [loaded] is what this device has paged in and passed the client-side filters;
 * [serverTotal] is what the server says the query matches. They differ whenever the
 * viewer has not scrolled to the end OR has set a year range, which the ledger has no
 * column for, so it is narrowed here. Saying "37 results" while the server holds 4,000
 * of them is the difference between a filtered catalog and a broken-looking one.
 */
internal fun resultsSummary(loaded: Int, serverTotal: Int, hasMore: Boolean): String = when {
    hasMore || loaded < serverTotal -> "Showing $loaded of $serverTotal"
    else -> "$loaded result" + if (loaded == 1) "" else "s"
}

data class SearchUiState(
    val query: String = "",
    val isLoading: Boolean = false,
    val isLoadingMore: Boolean = false,
    val error: String? = null,
    val filters: SearchFilters = SearchFilters(),
    val sort: SearchSort = SearchSort.DEFAULT,
    val groups: List<TypeGroup> = emptyList(),
    val resultCount: Int = 0,
    /** What the server says the query matches, not merely what this page holds. */
    val serverTotal: Int = 0,
    val recents: List<String> = emptyList(),
    val page: Int = 1,
    val hasMore: Boolean = false,
    val hasSearched: Boolean = false,
) {
    /** A blank query is still a search when a server facet is selected. */
    val hasSearchIntent: Boolean
        get() = query.isNotBlank() || filters.anyServerFilterActive

    val hasActiveFilters: Boolean
        get() = filters.type != null || filters.anyServerFilterActive ||
            filters.anyClientFilterActive || sort != SearchSort.DEFAULT
}

@HiltViewModel
class SearchViewModel @Inject constructor(
    private val catalogRepository: CatalogRepository,
    private val settingsRepository: ServerSettingsRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(SearchUiState())
    val uiState = _uiState.asStateFlow()

    private var searchJob: Job? = null
    private var moreJob: Job? = null
    private var rawResults: List<Post> = emptyList()

    init {
        // The rail is a history, not a session scratch pad: hydrate from the persisted list
        // and keep following it, so a second device state (e.g. a reset) cannot leave the
        // screen showing queries the store no longer holds.
        viewModelScope.launch {
            settingsRepository.searchRecents.collect { stored ->
                _uiState.update { it.copy(recents = stored) }
            }
        }
    }

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

    fun selectIndustry(industry: IndustryFilter) {
        if (_uiState.value.filters.industry == industry) return
        _uiState.update { it.copy(filters = it.filters.copy(industry = industry)) }
        scheduleSearch(reset = true)
    }

    fun selectGenre(genre: GenreFilter) {
        if (_uiState.value.filters.genre == genre) return
        _uiState.update { it.copy(filters = it.filters.copy(genre = genre)) }
        scheduleSearch(reset = true)
    }

    fun selectQuality(quality: QualityFilter) {
        if (_uiState.value.filters.quality == quality) return
        _uiState.update { it.copy(filters = it.filters.copy(quality = quality)) }
        scheduleSearch(reset = true)
    }

    fun setSort(sort: SearchSort) {
        if (_uiState.value.sort == sort) return
        _uiState.update { it.copy(sort = sort) }
        // Sort is a server ordering, so re-fetch instead of reordering only the
        // rows this device happens to hold.
        scheduleSearch(reset = true)
    }

    fun setYearRange(from: Int?, to: Int?) {
        _uiState.update { it.copy(filters = it.filters.copy(yearFrom = from, yearTo = to)) }
        recompute()
    }

    fun resetFilters() {
        _uiState.update {
            it.copy(
                filters = SearchFilters(type = it.filters.type),
                sort = SearchSort.DEFAULT,
            )
        }
        scheduleSearch(reset = true)
    }

    fun loadMore() {
        val state = _uiState.value
        if (!state.hasMore || state.isLoadingMore || !state.hasSearchIntent) return
        moreJob?.cancel()
        moreJob = viewModelScope.launch {
            _uiState.update { it.copy(isLoadingMore = true, error = null) }
            val next = state.page + 1
            try {
                val resp = catalogRepository.getPosts(
                    query = state.query.trim(),
                    type = state.filters.type,
                    industry = state.filters.industry.wireValue,
                    genre = state.filters.genre.wireValue,
                    quality = state.filters.quality.wireValue,
                    sort = state.sort.wireValue,
                    page = next,
                    limit = PAGE_SIZE,
                )
                rawResults = rawResults + resp.results
                _uiState.update {
                    it.copy(
                        page = next,
                        serverTotal = resp.total,
                        hasMore = resp.results.size >= PAGE_SIZE && next < resp.totalPages,
                    )
                }
                recompute()
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                _uiState.update { it.copy(error = friendlyNetworkError(error, "Could not load more.")) }
            } finally {
                _uiState.update { it.copy(isLoadingMore = false) }
            }
        }
    }

    private fun scheduleSearch(reset: Boolean, immediate: Boolean = false) {
        searchJob?.cancel()
        val state = _uiState.value
        val query = state.query.trim()
        val filters = state.filters
        if (query.isBlank() && !filters.anyServerFilterActive) {
            rawResults = emptyList()
            _uiState.update {
                it.copy(
                    isLoading = false, error = null, groups = emptyList(), resultCount = 0,
                    serverTotal = 0, hasSearched = false, hasMore = false, page = 1,
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
                    type = filters.type,
                    industry = filters.industry.wireValue,
                    genre = filters.genre.wireValue,
                    quality = filters.quality.wireValue,
                    sort = state.sort.wireValue,
                    page = 1,
                    limit = PAGE_SIZE,
                )
                rawResults = resp.results
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        hasSearched = true,
                        page = 1,
                        serverTotal = resp.total,
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
                        error = friendlyNetworkError(error, "Search failed. Check the server connection."),
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
            .groupBy { typeGroupKey(it) }
            .toSortedMap(typeComparator)
            .map { (key, posts) ->
                TypeGroup(
                    label = normalizeTypeLabel(key),
                    typeKey = key,
                    items = when (sort) {
                        SearchSort.TITLE -> posts.sortedBy { (it.cleanTitle ?: it.title).lowercase() }
                        SearchSort.HIGHEST_IMDB -> posts.sortedWith(
                            compareByDescending<Post> { it.imdbRating?.toDoubleOrNull() ?: -1.0 }
                                .thenByDescending { it.id },
                        )
                        SearchSort.NEWEST -> posts.sortedWith(
                            compareByDescending<Post> { it.year ?: 0 }
                                .thenByDescending { it.id },
                        )
                        // Mirrors the server's coverage ranking: no play counts exist.
                        SearchSort.MOST_SOURCES -> posts.sortedWith(
                            compareByDescending<Post> { (it.releaseCount ?: 0) + (it.sourceCount ?: 0) }
                                .thenByDescending { it.id },
                        )
                    },
                )
            }

        _uiState.update {
            it.copy(
                groups = groups,
                resultCount = filtered.size,
            )
        }
    }

    private fun recordRecent(query: String) {
        val trimmed = query.trim()
        if (trimmed.isBlank()) return
        val next = normalizeSearchRecents(listOf(trimmed) + _uiState.value.recents)
        if (next == _uiState.value.recents) return
        // Show the new rail immediately, then persist the same list; the store's flow will
        // echo it back and settle the state.
        _uiState.update { it.copy(recents = next) }
        viewModelScope.launch { settingsRepository.saveSearchRecents(next) }
    }

    private companion object {
        const val DEBOUNCE_MS = 300L
        const val PAGE_SIZE = 100

        val typeComparator = compareBy<String> { typeOrder(it) }

        fun typeOrder(label: String): Int = when (label) {
            "Movies" -> 0
            "Series" -> 1
            "Seasons" -> 2
            "Anime" -> 3
            else -> 4
        }
    }
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
    "anime" -> "Anime"
    null, "" -> "Other"
    else -> "Other"
}

/**
 * Which rail a row belongs to. Animation is a flag on the post, never a `content_type`, so a
 * row the ledger flags as animated keys as the server's own `anime` filter word instead of
 * sitting in the Series rail — the same [WorkType] answer the tile paints through
 * [com.raddstream.app.network.models.WorkTypeLabel]. A row from a server that sends no flag
 * keeps its plain `content_type`: unknown is never read as "not animated".
 */
internal fun typeGroupKey(post: Post): String =
    if (WorkType.fromContentType(post.contentType, post.isAnimated) == WorkType.ANIME) {
        WorkType.ANIME.wire
    } else {
        post.contentType.orEmpty()
    }
