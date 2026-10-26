package com.raddstream.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.network.friendlyNetworkError
import com.raddstream.app.network.models.Post
import com.raddstream.app.repository.CatalogRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * One horizontal rail on Home. Every rail is loaded independently and reports its
 * own loading/error so one slow facet cannot blank the whole page.
 *
 * HONESTY RULE (owner brief + AGENTS.md policy): a rail is only *rendered* when it
 * has a real backing source. `HomeViewModel` therefore only builds rails the v1 API
 * can actually serve. Rails the brief asks for but that have **no server support yet**
 * (continue-watching, trending, "because you watched", genre/language jump-off) are
 * declared in [RESERVE_NOTE] and intentionally omitted — the endpoint is requested in
 * docs/HANDOFF_appui.md rather than filled with fabricated or client-invented data.
 */
data class HomeSection(
    val key: String,
    val title: String,
    val type: String?,
    val items: List<Post> = emptyList(),
    val loading: Boolean = false,
    val error: String? = null,
) {
    val visible: Boolean get() = items.isNotEmpty() && error == null
}

data class HomeUiState(
    val sections: List<HomeSection> = emptyList(),
    val isRefreshing: Boolean = false,
    val fatal: String? = null,
)

private const val RESERVE_NOTE = """
    Reserved rails awaiting server support (see docs/HANDOFF_appui.md):
      - continue_watching : needs a per-post resume-state source (Room DAO) — requested.
      - trending          : needs GET /api/v1/trending or a play-count field — requested.
      - because_you_watch : needs GET /api/v1/related?work_id= (API_V2.md collections) — requested.
      - genre / language jump-off : needs GET /api/v1/facets (browse facets) — requested.
    None of these render until the backend returns real rows; they are NOT faked.
"""

@HiltViewModel
class HomeViewModel @Inject constructor(
    private val catalogRepository: CatalogRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(HomeUiState())
    val uiState = _uiState.asStateFlow()

    init {
        // Only rails v1 can honestly serve today. `type = null` == recently added
        // (the API default order is `p.id DESC` per viewer.py:1905, i.e. freshest scrape).
        val initial = listOf(
            HomeSection(key = "recent", title = "Recently added", type = null, loading = true),
            HomeSection(key = "movie", title = "Movies", type = "movie", loading = true),
            HomeSection(key = "series", title = "Series", type = "series", loading = true),
            HomeSection(key = "season", title = "Seasons", type = "complete_season", loading = true),
        )
        _uiState.update { it.copy(sections = initial) }
        loadAll(force = true)
    }

    fun refresh() = loadAll(force = true)

    fun retrySection(key: String) {
        val section = _uiState.value.sections.firstOrNull { it.key == key } ?: return
        // loadSection is suspend (it hits the repository); run it on the ViewModel's scope.
        viewModelScope.launch { loadSection(section) }
    }

    private fun loadAll(force: Boolean) {
        viewModelScope.launch {
            _uiState.update { it.copy(isRefreshing = true, fatal = null) }
            try {
                coroutineScope {
                    _uiState.value.sections
                        .filter { it.items.isEmpty() || force }
                        .map { async { loadSection(it) } }
                        .awaitAll()
                }
                _uiState.update { it.copy(isRefreshing = false) }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                _uiState.update {
                    it.copy(
                        isRefreshing = false,
                        fatal = friendlyNetworkError(error, "Your connected catalog server did not respond."),
                    )
                }
            }
        }
    }

    private suspend fun loadSection(section: HomeSection) {
        markSection(section.key) { it.copy(loading = true, error = null) }
        try {
            val results = catalogRepository.getPosts(type = section.type, page = 1, limit = 18).results
            markSection(section.key) { it.copy(items = results, loading = false, error = null) }
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (error: Exception) {
            markSection(section.key) {
                it.copy(loading = false, error = friendlyNetworkError(error, "Could not load this row."))
            }
        }
    }

    private fun markSection(key: String, transform: (HomeSection) -> HomeSection) {
        _uiState.update { state ->
            state.copy(sections = state.sections.map { if (it.key == key) transform(it) else it })
        }
    }
}
