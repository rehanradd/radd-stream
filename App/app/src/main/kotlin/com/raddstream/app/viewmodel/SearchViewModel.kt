package com.raddstream.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.data.normalizeSearchRecents
import com.raddstream.app.network.friendlyNetworkError
import com.raddstream.app.network.models.Post
import com.raddstream.app.network.models.SuggestItem
import com.raddstream.app.network.models.WorkType
import com.raddstream.app.player.PastedText
import com.raddstream.app.player.classifyPastedText
import com.raddstream.app.repository.CatalogRepository
import com.raddstream.app.sync.SyncAccountRepository
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
 *    device has already loaded. The sort is sent with every page fetch — it
 *    orders the page the server returns.
 *  - **Client-driven over the accumulated page(s):** the year range and the
 *    final per-group ordering. Grouping by content type is presentation only,
 *    and the order you SEE inside each group is this file's re-sort, not the
 *    server's page order: the server sort decides which rows arrive, the
 *    client sort decides how they line up on screen.
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
    /**
     * "Included in my plan": only works with at least one free print. A
     * server filter, so it narrows the whole catalog — and a VIP viewer
     * never sees the chip at all, because for them everything is included.
     */
    val includedOnly: Boolean = false,
) {
    val anyServerFilterActive: Boolean
        get() = industry != IndustryFilter.ALL ||
            genre != GenreFilter.ALL ||
            quality != QualityFilter.ALL ||
            includedOnly

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
    /** A VIP viewer has everything included, so the chip never shows for them. */
    val isVip: Boolean = false,
    /** Type-ahead titles for the current query; empty when the route is blocked or the server is old. */
    val suggestions: List<SuggestItem> = emptyList(),
    /**
     * True when the suggest call itself failed (blocked route, old server,
     * dead socket) — distinct from "the server answered and has no matches".
     * The screen says so instead of silently showing no chips.
     */
    val suggestionsUnavailable: Boolean = false,
    /** True when this page is the server's one-edit-away fallback, not an exact match. */
    val isFuzzy: Boolean = false,
    /**
     * True when the viewer asked to see exact matches only on a fuzzy page.
     * Every row on a fuzzy page is one-edit-away, so exact-only is the empty
     * state — not a second server call.
     */
    val showExactOnly: Boolean = false,
) {
    /** A blank query is still a search when a server facet is selected. */
    val hasSearchIntent: Boolean
        get() = query.isNotBlank() || filters.anyServerFilterActive

    val hasActiveFilters: Boolean
        get() = filters.type != null || filters.anyServerFilterActive ||
            filters.anyClientFilterActive || sort != SearchSort.DEFAULT

    /**
     * The filters the "Filtered" pill names: facets and years, never the
     * sort — a different sort order is not a filter, and the pill must not
     * claim the catalog is narrowed when only the ordering changed.
     */
    val hasFacetFilters: Boolean
        get() = filters.type != null || filters.anyServerFilterActive ||
            filters.anyClientFilterActive
}

@HiltViewModel
class SearchViewModel @Inject constructor(
    private val catalogRepository: CatalogRepository,
    private val settingsRepository: ServerSettingsRepository,
    private val syncAccountRepository: SyncAccountRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(SearchUiState())
    val uiState = _uiState.asStateFlow()

    private var searchJob: Job? = null
    private var moreJob: Job? = null
    private var suggestJob: Job? = null
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
        viewModelScope.launch {
            // Null entitlement is "not loaded yet", not "free": the chip
            // shows until the account answers, because hiding it for a
            // free viewer would cost them the filter, while a VIP viewer
            // sees it vanish the moment their tier loads.
            syncAccountRepository.entitlement.collect { entitlement ->
                _uiState.update { it.copy(isVip = entitlement?.vip == true) }
            }
        }
    }

    fun onQueryChanged(query: String) {
        _uiState.update { it.copy(query = query, error = null) }
        scheduleSearch(reset = true)
        scheduleSuggest()
    }

    /** Records the current query and forces an immediate search (IME "Search" key). */
    fun submitCurrentQuery() {
        _uiState.update { it.copy(suggestions = emptyList(), suggestionsUnavailable = false) }
        // A pasted address is not a title: it never joins the recents rail.
        if (classifyPastedText(_uiState.value.query) == PastedText.NotAUrl) {
            recordRecent(_uiState.value.query)
        }
        scheduleSearch(reset = true, immediate = true)
    }

    fun runRecent(query: String) {
        _uiState.update { it.copy(query = query, suggestions = emptyList(), suggestionsUnavailable = false) }
        recordRecent(query)
        scheduleSearch(reset = true, immediate = true)
    }

    /** A suggestion is a title to search for, not a page to open: the id it carries is a work id. */
    fun runSuggestion(title: String) {
        _uiState.update { it.copy(query = title, suggestions = emptyList(), suggestionsUnavailable = false) }
        recordRecent(title)
        scheduleSearch(reset = true, immediate = true)
    }

    /** Show only exact matches on a fuzzy page (the empty state — every fuzzy row is one-edit-away). */
    fun showExactOnly() {
        _uiState.update { it.copy(showExactOnly = true) }
    }

    /** Back to the close matches on a fuzzy page. */
    fun showCloseMatches() {
        _uiState.update { it.copy(showExactOnly = false) }
    }

    /** The recents rail is a history: clear it from the store, and the flow echoes it back. */
    fun clearRecents() {
        _uiState.update { it.copy(recents = emptyList()) }
        viewModelScope.launch { settingsRepository.saveSearchRecents(emptyList()) }
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

    fun setIncludedOnly(includedOnly: Boolean) {
        if (_uiState.value.filters.includedOnly == includedOnly) return
        _uiState.update { it.copy(filters = it.filters.copy(includedOnly = includedOnly)) }
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

    /** The v2 keyset cursor for the next page, or null once the list is on v1 paging. */
    private var v2Cursor: String? = null
    /** True once a search has loaded from v2: the list must never mix sources. */
    private var onV2: Boolean = false

    fun loadMore() {
        val state = _uiState.value
        if (!state.hasMore || state.isLoadingMore || !state.hasSearchIntent) return
        moreJob?.cancel()
        moreJob = viewModelScope.launch {
            _uiState.update { it.copy(isLoadingMore = true, error = null) }
            val next = state.page + 1
            try {
                if (onV2) {
                    val page = catalogRepository.searchWorksV2(
                        query = state.query.trim(),
                        sort = state.sort.wireValue,
                        limit = PAGE_SIZE,
                        cursor = v2Cursor,
                        type = state.filters.type,
                        genres = state.filters.genre.wireValue?.let { listOf(it) },
                        industries = state.filters.industry.wireValue?.let { listOf(it) },
                        qualities = state.filters.quality.wireValue?.let { listOf(it) },
                    )
                    if (page != null) {
                        v2Cursor = page.nextCursor
                        rawResults = (rawResults + page.posts).distinctById()
                        _uiState.update {
                            it.copy(
                                page = next,
                                serverTotal = page.totalEstimate ?: rawResults.size,
                                hasMore = page.hasMore,
                                isFuzzy = false,
                            )
                        }
                        recompute()
                        return@launch
                    }
                    throw IllegalStateException("The catalog could not serve the next page.")
                }
                val resp = catalogRepository.getPosts(
                    query = state.query.trim(),
                    type = state.filters.type,
                    industry = state.filters.industry.wireValue,
                    genre = state.filters.genre.wireValue,
                    quality = state.filters.quality.wireValue,
                    sort = state.sort.wireValue,
                    freeOnly = state.filters.includedOnly.takeIf { it },
                    page = next,
                    limit = PAGE_SIZE,
                )
                rawResults = (rawResults + resp.results).distinctById()
                _uiState.update {
                    it.copy(
                        page = next,
                        serverTotal = resp.total,
                        hasMore = resp.results.size >= PAGE_SIZE && next < resp.totalPages,
                        isFuzzy = resp.fuzzy,
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
                    isFuzzy = false, showExactOnly = false,
                )
            }
            return
        }
        // A pasted address is not a title: the catalog has nothing to say
        // about it, and the screen already shows the play row (or the
        // YouTube note) for it — so no server call, no suggest, no recent.
        if (classifyPastedText(query) != PastedText.NotAUrl) {
            rawResults = emptyList()
            _uiState.update {
                it.copy(
                    isLoading = false, error = null, groups = emptyList(), resultCount = 0,
                    serverTotal = 0, hasSearched = false, hasMore = false, page = 1,
                    isFuzzy = false, showExactOnly = false, suggestions = emptyList(),
                    suggestionsUnavailable = false,
                )
            }
            return
        }
        if (reset) _uiState.update { it.copy(page = 1) }
        searchJob = viewModelScope.launch {
            if (!immediate) delay(DEBOUNCE_MS)
            _uiState.update { it.copy(isLoading = true, error = null) }
            v2Cursor = null
            onV2 = false
            try {
                // Phase 7 (M1): v2 search first — one row per work — with v1 as
                // the fallback. The v2 side has no free-only filter, so a
                // free-only search stays on v1; and v2 matches titles only, so
                // an EMPTY v2 page falls back to v1, which is the route that
                // matches cast names (actor search, per the cast directive).
                val freeOnly = filters.includedOnly
                if (!freeOnly) {
                    val page = catalogRepository.searchWorksV2(
                        query = query,
                        sort = state.sort.wireValue,
                        limit = PAGE_SIZE,
                        type = filters.type,
                        genres = filters.genre.wireValue?.let { listOf(it) },
                        industries = filters.industry.wireValue?.let { listOf(it) },
                        qualities = filters.quality.wireValue?.let { listOf(it) },
                    )
                    if (page != null && page.posts.isNotEmpty()) {
                        onV2 = true
                        v2Cursor = page.nextCursor
                        rawResults = page.posts.distinctById()
                        _uiState.update {
                            it.copy(
                                isLoading = false,
                                hasSearched = true,
                                page = 1,
                                serverTotal = page.totalEstimate ?: rawResults.size,
                                hasMore = page.hasMore,
                                error = null,
                                isFuzzy = false,
                                showExactOnly = false,
                            )
                        }
                        recompute()
                        recordRecent(query)
                        return@launch
                    }
                }
                val resp = catalogRepository.getPosts(
                    query = query,
                    type = filters.type,
                    industry = filters.industry.wireValue,
                    genre = filters.genre.wireValue,
                    quality = filters.quality.wireValue,
                    sort = state.sort.wireValue,
                    freeOnly = filters.includedOnly.takeIf { it },
                    page = 1,
                    limit = PAGE_SIZE,
                )
                rawResults = resp.results.distinctById()
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        hasSearched = true,
                        page = 1,
                        serverTotal = resp.total,
                        hasMore = resp.results.size >= PAGE_SIZE && resp.totalPages > 1,
                        error = null,
                        isFuzzy = resp.fuzzy,
                        showExactOnly = false,
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

    /**
     * Type-ahead on the same debounce as the search, on its own job so a
     * slow suggest never delays the results. Two characters minimum — the
     * server answers nothing shorter — and a blank query clears the chips.
     * A blocked route or an old server just leaves the list empty.
     */
    private fun scheduleSuggest() {
        suggestJob?.cancel()
        val query = _uiState.value.query.trim()
        if (query.length < 2) {
            _uiState.update { it.copy(suggestions = emptyList(), suggestionsUnavailable = false) }
            return
        }
        if (classifyPastedText(query) != PastedText.NotAUrl) {
            _uiState.update { it.copy(suggestions = emptyList(), suggestionsUnavailable = false) }
            return
        }
        suggestJob = viewModelScope.launch {
            delay(DEBOUNCE_MS)
            // Null is "the suggest call itself failed" (blocked route, old
            // server, dead socket) — the screen says so, instead of
            // silently showing no chips as if nothing matched.
            val items = catalogRepository.suggest(query)
            _uiState.update {
                it.copy(
                    suggestions = items ?: emptyList(),
                    suggestionsUnavailable = items == null,
                )
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

        val groups = groupSearchResults(filtered, sort)

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
    }
}

internal fun parseYear(year: String?): Int? {
    if (year.isNullOrBlank()) return null
    Regex("""(19|20)\d{2}""").find(year)?.value?.toIntOrNull()?.let { return it }
    return null
}

/**
 * Rail order, by the LABEL the rail is headed with — Movies, Series, Seasons,
 * Anime, then anything else. Session 120: this used to live behind a
 * `compareBy { typeOrder(it) }` fed the raw wire keys ("movie"), which it never
 * matched, so every key ordered equal (see [groupSearchResults]).
 */
internal fun typeOrder(label: String): Int = when (label) {
    "Movies" -> 0
    "Series" -> 1
    "Seasons" -> 2
    "Anime" -> 3
    else -> 4
}

/**
 * Group search rows into labelled rails, in rail order.
 *
 * Session 120: this used to be
 * `groupBy { typeGroupKey(it) }.toSortedMap(typeComparator)`, which collapsed
 * every group into ONE. `toSortedMap` is a TreeMap, and a TreeMap treats two keys
 * as the SAME key when the comparator returns 0 — and `typeOrder` only ever
 * matched the plural labels ("Movies"), never the raw wire keys it was actually
 * handed ("movie"), so every key compared equal. The map kept the FIRST key and
 * the LAST value: a "Series" header, the Movies count, and film cards
 * underneath — exactly what the TestingBot retest showed ("Series — 4" over
 * "2026 · Movie" cards). Sorting the built list instead keeps every group,
 * and the header is the label of the rows it actually heads.
 */
internal fun groupSearchResults(posts: List<Post>, sort: SearchSort): List<TypeGroup> =
    posts
        .groupBy { typeGroupKey(it) }
        .map { (key, grouped) ->
            TypeGroup(
                label = normalizeTypeLabel(key),
                typeKey = key,
                items = when (sort) {
                    SearchSort.TITLE -> grouped.sortedBy { (it.cleanTitle ?: it.title).lowercase() }
                    SearchSort.HIGHEST_IMDB -> grouped.sortedWith(
                        compareByDescending<Post> { it.imdbRating?.toDoubleOrNull() ?: -1.0 }
                            .thenByDescending { it.id },
                    )
                    SearchSort.NEWEST -> grouped.sortedWith(
                        compareByDescending<Post> { it.year ?: 0 }
                            .thenByDescending { it.id },
                    )
                    // Mirrors the server's coverage ranking: no play counts exist.
                    SearchSort.MOST_SOURCES -> grouped.sortedWith(
                        compareByDescending<Post> { (it.releaseCount ?: 0) + (it.sourceCount ?: 0) }
                            .thenByDescending { it.id },
                    )
                },
            )
        }
        .sortedBy { typeOrder(it.label) }

internal fun normalizeTypeLabel(contentType: String?): String = when (contentType?.lowercase()?.trim()) {
    "movie" -> "Movies"
    "series" -> "Series"
    "complete_season", "ongoing_season" -> "Seasons"
    "anime" -> "Anime"
    // Session 120: these used to fall into "Other" while the tile painted the
    // capitalised wire word ("Documentary", "Sport_event"), so the header
    // described no card under it. A rail is headed with the word its cards
    // paint — see WorkTypeLabel.of, which answers the same word per row.
    "documentary" -> "Documentary"
    "sport_event" -> "Sport event"
    "music_video" -> "Music video"
    "tv_special" -> "TV special"
    "miniseries" -> "Miniseries"
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
