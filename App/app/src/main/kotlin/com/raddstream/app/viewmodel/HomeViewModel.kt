package com.raddstream.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.brand.Brand
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.data.UserRegion
import com.raddstream.app.data.local.SyncedProgressDao
import com.raddstream.app.data.local.WatchHistoryDao
import com.raddstream.app.data.local.WatchHistoryMerge
import com.raddstream.app.network.friendlyNetworkError
import com.raddstream.app.network.models.Post
import com.raddstream.app.network.models.PanelBroadcast
import com.raddstream.app.network.models.VipRemoteConfig
import com.raddstream.app.network.models.WireText
import com.raddstream.app.player.AdCadenceGovernor
import com.raddstream.app.player.AdSurface
import com.raddstream.app.repository.CatalogRepository
import com.raddstream.app.repository.FavoritesRepository
import com.raddstream.app.sync.SyncAccountRepository
import com.raddstream.app.ui.navigation.BroadcastTargeting
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
import kotlinx.coroutines.flow.first
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
    /**
     * True when the rail came from the admin panel, not from a posts call. A
     * panel rail already has its rows — it is never loaded, retried, or
     * refreshed through [HomeViewModel.loadSection]; the next remote-config
     * fetch rebuilds it.
     */
    val panelManaged: Boolean = false,
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
    /** Live broadcasts from the admin panel; a dismissed one stays dismissed for this session. */
    val broadcasts: List<PanelBroadcast> = emptyList(),
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

/**
 * The operator's feed, merged over the built-in rails. Pure, so the test can pin
 * the questions that matter without a repository: panel sections first, in the
 * panel's order, then the built-in rails that no panel section owns by key; every
 * row the operator hid is dropped from both, because the server hides it too but
 * a phone must never trust one layer alone; a dismissed broadcast never returns
 * until the next app start. A panel section with no rows renders nothing — an
 * empty operator rail is not a loading state.
 */
internal fun mergePanelFeed(
    current: List<HomeSection>,
    config: VipRemoteConfig,
    dismissedBroadcastIds: Set<Int>,
    regionId: String = UserRegion.DEFAULT,
    isVip: Boolean? = null,
    appVersion: String = "",
): Pair<List<HomeSection>, List<PanelBroadcast>> {
    val hidden = config.hiddenWorkIds.toSet()
    val panelSections = config.sections.map { panel ->
        HomeSection(
            key = "panel:${panel.key}",
            title = panel.title,
            type = null,
            items = panel.items.filter { it.id !in hidden },
            panelManaged = true,
        )
    }.filter { it.items.isNotEmpty() }
    val panelKeys = config.sections.map { it.key }.toSet()
    val builtIn = current
        .filter { !it.panelManaged && it.key !in panelKeys }
        .map { it.copy(items = it.items.filter { post -> post.id !in hidden }) }
    val broadcasts = config.broadcasts.filter {
        it.id !in dismissedBroadcastIds && it.title.isNotBlank() &&
            BroadcastTargeting.visible(it, regionId, isVip, appVersion)
    }
    return (panelSections + builtIn) to broadcasts
}

@HiltViewModel
class HomeViewModel @Inject constructor(
    private val catalogRepository: CatalogRepository,
    private val watchHistoryDao: WatchHistoryDao,
    private val syncedProgressDao: SyncedProgressDao,
    private val favoritesRepository: FavoritesRepository,
    private val adCadence: AdCadenceGovernor,
    private val adFreeReader: AdFreeReader,
    private val settingsRepository: ServerSettingsRepository,
    private val syncAccountRepository: SyncAccountRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(HomeUiState())
    val uiState = _uiState.asStateFlow()

    /** A URL the viewer already declined stays declined for this app session. */
    private var dismissedUpdateUrl: String? = null

    /** A broadcast the viewer dismissed stays dismissed for this app session. */
    private val dismissedBroadcastIds = mutableSetOf<Int>()

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
        askAppOpenAd()
    }

    /**
     * The app-open surface, asked once per Home entry and capped at one impression per four hours
     * of wall clock.
     *
     * Nothing is awaited and nothing is rendered from the answer, and that is the whole design: an
     * app-open ad that the first frame had to wait for *is* the 10-second timer redirect the owner
     * ruled out, in a different costume. The governor records the impression when a network can fill
     * the slot and answers `None` when it cannot, and a `None` costs this screen exactly the work of
     * one suspended call — no placeholder, no spinner, no held catalog.
     */
    private fun askAppOpenAd() {
        viewModelScope.launch {
            val adFree = adFreeReader.isAdFree()
            adCadence.offer(AdSurface.APP_OPEN, adFree = adFree)
        }
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
                favoritesRepository.observeRefusedIds(),
            ) { local, synced, refused ->
                // A resume row is a cached surface like any other: it names a work this device
                // watched, and the ledger may have been refused an answer about it since.
                // `flagOf` is a constant null because `watch_history` keeps no adult column — the
                // table is written by playback, and no payload ever told us a flag. Null is "not
                // told", which [AdultPolicy] reads as no evidence either way, so the refusal is
                // what removes a card here and a 200 later puts it back.
                AdultPolicy.listableRows(
                    rows = WatchHistoryMerge.merge(local, synced),
                    flagOf = { null },
                    refusedOf = { it.postId in refused },
                )
            }
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

    fun dismissBroadcast(id: Int) {
        dismissedBroadcastIds.add(id)
        _uiState.update { it.copy(broadcasts = it.broadcasts.filter { broadcast -> broadcast.id != id }) }
    }

    /**
     * Remote config is decoration on Home: an unreachable endpoint or a malformed body
     * must never turn into an error banner over a catalog that loaded fine. One fetch
     * serves three things — the update notice, the panel's sections and broadcasts,
     * and the hide list — so a phone that got the body has all of them or none.
     */
    private fun checkForUpdate() {
        viewModelScope.launch {
            val config = try {
                catalogRepository.getRemoteConfig()
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                return@launch
            }
            val notice = AppUpdate.from(config)?.takeUnless { it.url == dismissedUpdateUrl }
            // The audience for a targeted broadcast is decided here, from
            // what this phone knows: the viewer's region card, and the tier
            // the account store has actually loaded. A tier that has not
            // loaded yet is unknown, not free — the filter hides both tiered
            // broadcasts until it knows, rather than guessing.
            val regionId = try {
                settingsRepository.userRegion.first()
            } catch (_: Exception) {
                UserRegion.DEFAULT
            }
            val isVip = syncAccountRepository.entitlement.value?.vip
            _uiState.update { state ->
                val (sections, broadcasts) = mergePanelFeed(
                    state.sections, config, dismissedBroadcastIds,
                    regionId = regionId, isVip = isVip,
                    appVersion = Brand.versionName,
                )
                state.copy(sections = sections, broadcasts = broadcasts, updateNotice = notice)
            }
        }
    }

    fun retrySection(key: String) {
        val section = _uiState.value.sections.firstOrNull { it.key == key } ?: return
        // A panel rail has nothing to retry: its rows come with the config, and the
        // next refresh re-fetches them. Retrying through the posts route would
        // overwrite the operator's rail with a generic list.
        if (section.panelManaged) return
        // loadSection is suspend (it hits the repository); run it on the ViewModel's scope.
        viewModelScope.launch { loadSection(section) }
    }

    private fun loadAll(force: Boolean) {
        viewModelScope.launch {
            _uiState.update { it.copy(isRefreshing = true, fatal = null) }
            try {
                coroutineScope {
                    _uiState.value.sections
                        .filter { !it.panelManaged && (it.items.isEmpty() || force) }
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
        if (section.panelManaged) return
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
