package com.raddstream.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.data.local.SyncedProgressDao
import com.raddstream.app.data.local.WatchHistoryDao
import com.raddstream.app.data.local.WatchHistoryMerge
import com.raddstream.app.network.friendlyNetworkError
import com.raddstream.app.network.models.Post
import com.raddstream.app.network.models.VipRemoteConfig
import com.raddstream.app.network.models.WireText
import com.raddstream.app.repository.CatalogRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.combine
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

    /**
     * A rail that already has rows and whose newest refresh came back empty-handed. Without
     * this the old rows stayed on screen and the failure went nowhere — `visible` was false, so
     * the section rendered no branch at all and the rail simply vanished from the page.
     */
    val refreshFailure: String? get() = error?.takeIf { items.isNotEmpty() }
}

data class HomeUiState(
    val sections: List<HomeSection> = emptyList(),
    val isRefreshing: Boolean = false,
    val fatal: String? = null,
    /** Real local rows only — see [WatchHistoryMerge] for why an unnameable pull is dropped. */
    val continueWatching: List<ResumeTile> = emptyList(),
    /** Set when the operator has published a downloadable build; null means "no news". */
    val updateNotice: AppUpdate? = null,
)

/**
 * A build the operator published through remote config.
 *
 * The published body carries no version code, so this cannot compare versions: a
 * non-empty, http(s) URL is the whole signal, and the copy says "a new build is
 * available" rather than pretending to know whether it is newer than this APK.
 */
data class AppUpdate(
    val url: String,
    val publishedAt: Long,
) {
    companion object {
        /** Null unless the operator actually published a usable download link. */
        fun from(config: VipRemoteConfig?): AppUpdate? {
            val url = config?.apkUpdateUrl?.trim().orEmpty()
            if (!WireText.isHttpUrl(url)) return null
            return AppUpdate(url = url, publishedAt = config?.updatedAt ?: 0L)
        }
    }
}

private const val RESERVE_NOTE = """
    Reserved rails awaiting server support (see docs/HANDOFF_appui.md):
      - trending          : needs GET /api/v1/trending or a play-count field — requested.
      - because_you_watch : needs GET /api/v1/related?work_id= (API_V2.md collections) — requested.
      - genre / language jump-off : needs GET /api/v1/facets (browse facets) — requested.
    None of these render until the backend returns real rows; they are NOT faked.
"""

@HiltViewModel
class HomeViewModel @Inject constructor(
    private val catalogRepository: CatalogRepository,
    private val watchHistoryDao: WatchHistoryDao,
    private val syncedProgressDao: SyncedProgressDao,
) : ViewModel() {

    private val _uiState = MutableStateFlow(HomeUiState())
    val uiState = _uiState.asStateFlow()

    /** A URL the viewer already declined stays declined for this app session. */
    private var dismissedUpdateUrl: String? = null

    init {
        observeContinueWatching()
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
        checkForUpdate()
    }

    /**
     * Continue watching, from rows this device wrote while playing and, when a sync pass
     * pulled a newer position for the same scope, the server's timestamp. The merge is pure
     * ([WatchHistoryMerge]) and drops any handle this device cannot name — a card must never
     * be a guess at what a server row was.
     *
     * A row leaves here as a [ResumeTile], not a bare [Post]: where viewing stopped is the
     * only reason this rail exists, and a tile that hides it is indistinguishable from any
     * other poster on the page.
     */
    private fun observeContinueWatching() {
        viewModelScope.launch {
            combine(
                watchHistoryDao.observeRecent(WatchHistoryMerge.DEFAULT_LIMIT * 2),
                syncedProgressDao.observeRecent(WatchHistoryMerge.DEFAULT_LIMIT * 2),
            ) { local, synced -> WatchHistoryMerge.merge(local, synced) }
                .collect { rows ->
                    val items = rows.mapNotNull { ResumeTile.of(it) }
                    _uiState.update { it.copy(continueWatching = items) }
                }
        }
    }

    fun refresh() {
        loadAll(force = true)
        checkForUpdate()
    }

    fun dismissUpdate() {
        dismissedUpdateUrl = _uiState.value.updateNotice?.url
        _uiState.update { it.copy(updateNotice = null) }
    }

    /**
     * Remote config is decoration on Home: an unreachable endpoint or a malformed body
     * must never turn into an error banner over a catalog that loaded fine.
     */
    private fun checkForUpdate() {
        viewModelScope.launch {
            val notice = try {
                AppUpdate.from(catalogRepository.getRemoteConfig())
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                return@launch
            }
            if (notice != null && notice.url == dismissedUpdateUrl) return@launch
            _uiState.update { it.copy(updateNotice = notice) }
        }
    }

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
