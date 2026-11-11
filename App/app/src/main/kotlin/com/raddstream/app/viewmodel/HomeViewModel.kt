package com.raddstream.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.brand.Brand
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.data.UserRegion
import com.raddstream.app.data.cache.ConnectivityProbe
import com.raddstream.app.data.cache.NetworkClass
import com.raddstream.app.data.local.SyncedProgressDao
import com.raddstream.app.data.local.WatchHistoryDao
import com.raddstream.app.data.local.WatchHistoryEntity
import com.raddstream.app.data.local.WatchHistoryMerge
import com.raddstream.app.network.friendlyNetworkError
import com.raddstream.app.network.models.FacetsResponse
import com.raddstream.app.network.models.Post
import com.raddstream.app.network.models.PanelBroadcast
import com.raddstream.app.network.models.VipRemoteConfig
import com.raddstream.app.network.models.WireText
import com.raddstream.app.player.AdCadenceGovernor
import com.raddstream.app.player.AdSurface
import com.raddstream.app.repository.CatalogRepository
import com.raddstream.app.repository.FavoritesRepository
import com.raddstream.app.sync.DeviceTrial
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
 * can actually serve. Continue Watching renders from the device's own watch
 * history (no server needed), and the panel's sections render from the feed.
 * "Because you watch" renders from GET /api/v1/related, seeded from the
 * first Continue Watching post, and the genre/language jump-off renders
 * from GET /api/v1/facets — both are real server answers now, so neither
 * is reserved any more. "Most watched" used to sit in that list; it does
 * not any more, because the sort it needs already exists on the live route
 * (`/api/v1/posts?sort=trending`) — see [initialHomeSections].
 */
/**
 * The rails Home actually renders, in order. Continue Watching counts as a
 * row: the rule is at most 10 rows total, CW first and pinned, so the
 * content rails behind it are 9 when CW is showing and 10 when it is not.
 * A panel that publishes 12 sections does not get 12 rails on a phone —
 * the cap is the phone's, and the first rails win.
 */
fun visibleHomeRows(sections: List<HomeSection>, hasContinueWatching: Boolean): List<HomeSection> {
    val contentRows = if (hasContinueWatching) MAX_HOME_ROWS - 1 else MAX_HOME_ROWS
    return sections.take(contentRows)
}

/** At most 10 rows on Home, Continue Watching included. */
const val MAX_HOME_ROWS = 10

data class HomeSection(
    val key: String,
    val title: String,
    val type: String?,
    val items: List<Post> = emptyList(),
    val loading: Boolean = false,
    val error: String? = null,
    /**
     * The server sort this rail asks for (`/api/v1/posts?sort=`), or null for
     * the server default (`p.id DESC`, freshest first). Only "Most watched"
     * sets one today: `sort=trending` ranks by how many prints and mirrors
     * the catalog holds for a work — the ledger has no play-count column,
     * so the rail is labelled for the viewer, never "Trending" (which would
     * promise popularity data that does not exist).
     */
    val sort: String? = null,
    /**
     * The v1 post id this rail is related to (`/api/v1/related?work_id=`),
     * or null for an ordinary list rail. Only "Because you watch" sets
     * one: it is seeded from the first Continue Watching post, and it
     * hides when there is no seed or the server answers an empty page.
     */
    val relatedWorkId: Int? = null,
    /**
     * True when the operator's feed, not a posts call, owns this rail. A
     * panel rail already has its rows — it is never loaded, retried, or
     * refreshed through [HomeViewModel.loadSection]; the next remote-config
     * fetch rebuilds it.
     */
    val panelManaged: Boolean = false,
) {
    val visible: Boolean get() = items.isNotEmpty() && error == null

    /**
     * True when Browse can reproduce this rail's order. Browse takes a type
     * but no sort, so a rail ordered by a server sort has no "See all": the
     * Browse page would silently re-sort it to freshest-first. A related
     * rail has no Browse equivalent either — Browse cannot reproduce a
     * seed's neighbours.
     */
    val browseEquivalent: Boolean get() = sort == null && relatedWorkId == null

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
    /**
     * Whole days of free VIP trial left, live from the ledger — null when there is
     * no trial to explain (no grant recorded, trial over, viewer is VIP, or the
     * note was dismissed). The screen renders the number, never a hardcoded "3".
     */
    val trialDaysRemaining: Int? = null,
    /**
     * True when the device had no network at the last load. The banner that
     * reads this only shows when something saved is on screen — an offline
     * phone with nothing saved gets the error state, not a banner over a
     * blank page.
     */
    val isOffline: Boolean = false,
    /**
     * The daily check-in, on Home where the viewer actually is. The count is
     * this device's own (one open a day, recorded at launch); the ladder and
     * the wallet are the server's. The card renders only once the ladder
     * arrives — an absent plan is never shown as a zero. `serverStreak` is
     * the server's claimed-days count, the only number the card may present
     * as "Day N"; null until the overview answers, and the card must not
     * print a day number from the local count in the meantime (HO-6).
     */
    val streakCount: Int = 0,
    val serverStreak: Int? = null,
    val streakLadder: Map<Int, Int> = emptyMap(),
    val coinBalance: Int = 0,
    val signedIn: Boolean = false,
    val claimedToday: Boolean = false,
    val isClaiming: Boolean = false,
    val claimMessage: String? = null,
    /** Session 121 (P-26): the ids on this device's My List, so the hero's toggle reads live. */
    val favoriteIds: Set<Int> = emptySet(),
    /**
     * Phase 7 (M1): the same membership by server handle. A v2 row's `id` is
     * the negative work-id sentinel, never a v1 post id, so the id set alone
     * cannot say whether a v2 tile is saved — the handle set can.
     */
    val favoriteWorkRefs: Set<String> = emptySet(),
    /** Phase 7 (D1): the title of the Continue Watching tile just removed, until Undo or dismiss. */
    val removedResumeTitle: String? = null,
    /**
     * Gap A5: when the cached Home on screen was last refreshed from the
     * server (null until Home has ever loaded). The screen dates the rows
     * from this, never from a hardcoded "just now".
     */
    val lastHomeSyncMs: Long? = null,
    /** Gap A6: true once the first-run "Pick 3 you like" card is done (picked 3 or dismissed). */
    val pickThreeDone: Boolean = false,
    /**
     * The browse jump-off chips from GET /api/v1/facets (genres, languages,
     * industries, types, each with the count its tap delivers). Null until
     * the call answers, and null again when it fails — no chips, never a
     * failed Home, and the screen must not pretend the silence means "no
     * genres exist". Language chips are not rendered yet: Search has no
     * language filter to land on, so the group waits for one.
     */
    val facets: FacetsResponse? = null,
) {
    /**
     * Gap A6: the three titles the first-run card offers — the first rail
     * with at least three rows, first three only. Empty when no rail can
     * offer three yet, so the card waits instead of inventing titles.
     */
    val pickThreeCandidates: List<Post>
        get() = sections.firstOrNull { it.items.size >= 3 }?.items?.take(3).orEmpty()

    /**
     * Gap A6: the card shows only to a brand-new viewer — nothing
     * continued, nothing saved, card not done — and only once a rail can
     * offer three real titles to pick from.
     */
    val showPickThree: Boolean
        get() = !pickThreeDone && continueWatching.isEmpty() && favoriteIds.isEmpty() &&
            pickThreeCandidates.size >= 3
}

/**
 * A build the operator published through remote config.
 *
 * The published body carries the APK's version code when the operator set
 * one, so this can compare versions instead of guessing: a published code
 * at or below this build means this build already has it, and no notice
 * shows. A body with no code (0) falls back to the old rule — a published,
 * http(s) URL is the whole signal. `required` is true only when the
 * operator set a minimum this build falls below: that update is not
 * optional, and the dialog offers no "Later".
 *
 * @param required true when this build is below the operator's minimum version.
 * @param sizeBytes the published APK's size in bytes, 0 when unpublished;
 * the dialog shows it so a viewer on mobile data knows what the tap costs.
 */
data class AppUpdate(
    val url: String,
    val publishedAt: Long,
    val required: Boolean = false,
    val sizeBytes: Long = 0,
) {
    companion object {
        /** Null unless the operator actually published a usable download link. */
        fun from(config: VipRemoteConfig?, currentVersionCode: Int = 0): AppUpdate? {
            val url = config?.apkUpdateUrl?.trim().orEmpty()
            if (!WireText.isHttpUrl(url)) return null
            // A published code is the operator's own verdict on whether this
            // build is behind: at or below it, this build already has the
            // update. A code of 0 means "no code published", and the link
            // alone is the signal, as before.
            val publishedCode = config?.apkUpdateVersionCode ?: 0
            if (publishedCode > 0 && currentVersionCode > 0 &&
                publishedCode <= currentVersionCode
            ) {
                return null
            }
            val minCode = config?.minVersionCode ?: 0
            val required = minCode > 0 && currentVersionCode > 0 &&
                currentVersionCode < minCode
            return AppUpdate(
                url = url,
                publishedAt = config?.updatedAt ?: 0L,
                required = required,
                sizeBytes = config?.apkUpdateSizeBytes ?: 0,
            )
        }
    }
}

private const val RESERVE_NOTE = """
    Reserved rails awaiting server support (see docs/HANDOFF_appui.md):
      - (none — "Because you watch" shipped with GET /api/v1/related and
        the genre / language jump-off with GET /api/v1/facets.)
    None of these render until the backend returns real rows; they are NOT faked.
    "Most watched" left this list in D2.2: its order already exists as
    sort=trending on /api/v1/posts (most prints and mirrors — no play counts
    exist, so it is not popularity), and the app already calls that sort.
"""

/** The key of the "Because you watch" rail, inserted after "Recently added". */
private const val BECAUSE_YOU_WATCH_KEY = "because_you_watch"

/**
 * The rails Home actually renders, in order. Pure, so the test can pin the
 * questions that matter without a repository: five rails, "Most watched"
 * last, and only that rail asks the server for a sort.
 *
 * Only rails v1 can honestly serve today. `type = null` == recently added
 * (the API default order is `p.id DESC` per viewer.py:1905, i.e. freshest
 * scrape). "Most watched" is `sort=trending` on the same live route — the
 * server ranks by how many prints and mirrors the catalog holds for a work,
 * because the ledger has no play-count column; the label says what the
 * order is, and "Trending" would promise popularity data that does not
 * exist (the same naming rule SearchViewModel's [SearchSort] follows).
 */
internal fun initialHomeSections(): List<HomeSection> = listOf(
    HomeSection(key = "recent", title = "Recently added", type = null, loading = true),
    HomeSection(key = "movie", title = "Movies", type = "movie", loading = true),
    HomeSection(key = "series", title = "Series", type = "series", loading = true),
    HomeSection(key = "season", title = "Seasons", type = "complete_season", loading = true),
    HomeSection(key = "most_sources", title = "Most watched", type = null, sort = "trending", loading = true),
)

/**
 * D2.7: the Home trial note, as a pure decision. The note shows only while the
 * trial is genuinely running (seconds left above zero), the viewer is not already
 * VIP (a VIP has nothing to be warned about), and the viewer has not dismissed it
 * (dismissal is persisted — the note never returns). Days round up, the way
 * [DeviceTrial.daysRemaining] rounds them everywhere else: 20 hours left is
 * "1 day remaining", never "0 days" on a trial that is still live.
 */
internal fun trialNoteDaysRemaining(
    trialSecondsLeft: Double?,
    isVip: Boolean,
    dismissed: Boolean,
): Int? {
    if (isVip || dismissed) return null
    val seconds = trialSecondsLeft ?: return null
    return DeviceTrial.daysRemaining(seconds).takeIf { it > 0 }
}

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
    private val connectivityProbe: ConnectivityProbe,
) : ViewModel() {

    private val _uiState = MutableStateFlow(HomeUiState())
    val uiState = _uiState.asStateFlow()

    /** A URL the viewer already declined stays declined for this app session. */
    private var dismissedUpdateUrl: String? = null

    /** A broadcast the viewer dismissed stays dismissed for this app session. */
    private val dismissedBroadcastIds = mutableSetOf<Int>()

    init {
        observeContinueWatching()
        observeFavorites()
        observeDailyCheckIn()
        observeTrialNote()
        observePickThreeDone()
        _uiState.update { it.copy(sections = initialHomeSections()) }
        // Gap A5: cache-first — the saved Home renders before the network
        // answers, and the refresh runs behind it. The restore is awaited
        // first so a fresh load can never be overwritten by stale rows.
        viewModelScope.launch {
            restoreCachedHome()
            loadAll(force = true)
        }
        loadFacets()
        checkForUpdate()
        askAppOpenAd()
    }

    /** The seed post id the "Because you watch" rail is loaded for, or null when no rail is loaded. */
    private var relatedSeedId: Int? = null

    /**
     * The daily check-in's facts, read not written: the streak count is this
     * device's own, the ladder and the wallet are the server's, and the claim
     * is the same call the VIP screen makes — one owner, so Home and VIP can
     * never disagree about what today pays.
     */
    private fun observeDailyCheckIn() {
        viewModelScope.launch {
            settingsRepository.loginStreakCount.collect { count ->
                _uiState.update { it.copy(streakCount = count) }
            }
        }
        viewModelScope.launch {
            syncAccountRepository.signedIn.collect { signed ->
                _uiState.update { it.copy(signedIn = signed) }
                if (signed) loadCheckInWallet()
            }
        }
    }

    private fun loadCheckInWallet() {
        viewModelScope.launch {
            val ladder = syncAccountRepository.loadStreakLadder()
            val balance = syncAccountRepository.loadCoinBalance()
            val overview = syncAccountRepository.loadAccountOverview()
            _uiState.update {
                it.copy(
                    streakLadder = ladder.ifEmpty { it.streakLadder },
                    coinBalance = balance ?: it.coinBalance,
                    serverStreak = overview?.streak?.currentStreak ?: it.serverStreak,
                )
            }
        }
    }

    /**
     * Claim today's check-in — the same call, guards and words as the VIP
     * screen's claim, so a grant the server paid is never presented twice
     * and an unreachable server is never presented as "already claimed".
     */
    fun claimDailyLogin() {
        val state = _uiState.value
        if (!state.signedIn || state.isClaiming || state.claimedToday) return
        viewModelScope.launch {
            _uiState.update { it.copy(isClaiming = true, claimMessage = null) }
            try {
                val earned = syncAccountRepository.claimDailyLogin()
                if (earned == null) {
                    _uiState.update {
                        it.copy(claimMessage = "Could not reach the server — try again later.")
                    }
                    return@launch
                }
                val balance = syncAccountRepository.loadCoinBalance()
                _uiState.update {
                    it.copy(
                        claimedToday = true,
                        coinBalance = balance ?: it.coinBalance,
                        // The claim answer carries the server's count — keep
                        // the card on it without waiting for a re-read.
                        serverStreak = earned.currentStreak,
                        claimMessage = when {
                            earned.status == "same_day_noop" -> "Already claimed today."
                            earned.currentStreak > 7 ->
                                "Streak day ${earned.currentStreak} — the 7-day ladder is complete."
                            earned.pass != null ->
                                "+${earned.coinsGranted} coins — Day ${earned.currentStreak} of 7, and a 24-hour pass."
                            earned.coinsGranted > 0 ->
                                "+${earned.coinsGranted} coins — Day ${earned.currentStreak} of 7."
                            else -> "Day ${earned.currentStreak} of 7."
                        },
                    )
                }
            } finally {
                _uiState.update { it.copy(isClaiming = false) }
            }
        }
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
                    syncBecauseYouWatch(items.firstOrNull()?.post?.id)
                }
        }
    }

    /**
     * GET /api/v1/facets — the browse jump-off chips. One call per Home
     * load; a failed call means no chips, never a failed Home, and the
     * last good facets stay on screen rather than being wiped by a
     * failed refresh.
     */
    private fun loadFacets() {
        viewModelScope.launch {
            val facets = try {
                catalogRepository.getFacets()
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                null
            }
            if (facets != null) {
                _uiState.update { it.copy(facets = facets) }
            }
        }
    }

    /**
     * The "Because you watch" rail, seeded from the first Continue Watching
     * post. The rail is inserted after "Recently added" and loaded once;
     * a later refresh reloads it like any other rail through [loadSection].
     * A new seed replaces the rail and reloads it; no seed removes it.
     * A seed that is already loaded is a no-op, so a re-emitted watch
     * history does not reload the rail for nothing.
     */
    private fun syncBecauseYouWatch(seedPostId: Int?) {
        if (seedPostId == relatedSeedId) return
        relatedSeedId = seedPostId
        val current = _uiState.value.sections
        if (seedPostId == null) {
            if (current.any { it.key == BECAUSE_YOU_WATCH_KEY }) {
                _uiState.update { state ->
                    state.copy(sections = state.sections.filterNot { it.key == BECAUSE_YOU_WATCH_KEY })
                }
            }
            return
        }
        val existing = current.firstOrNull { it.key == BECAUSE_YOU_WATCH_KEY }
        val section = (existing ?: HomeSection(
            key = BECAUSE_YOU_WATCH_KEY,
            title = "Because you watch",
            type = null,
            loading = true,
        )).copy(relatedWorkId = seedPostId, loading = true, error = null)
        val sections = if (existing != null) {
            current.map { if (it.key == BECAUSE_YOU_WATCH_KEY) section else it }
        } else {
            val index = current.indexOfFirst { it.key == "recent" }
                .takeIf { it >= 0 }?.plus(1) ?: 1
            current.toMutableList().apply { add(index.coerceIn(0, size), section) }
        }
        _uiState.update { it.copy(sections = sections) }
        viewModelScope.launch { loadSection(section) }
    }

    /**
     * Session 121 (P-26): the hero's My List toggle reads live — a favorite added
     * on the details page flips the hero's button without a reload, and vice versa.
     */
    private fun observeFavorites() {
        viewModelScope.launch {
            favoritesRepository.getAllFavorites().collect { favorites ->
                _uiState.update {
                    it.copy(
                        favoriteIds = favorites.map { fav -> fav.id }.toSet(),
                        favoriteWorkRefs = favorites.mapNotNull { fav -> fav.workRef }.toSet(),
                    )
                }
                // Gap A6: the third pick completes the card — the viewer has
                // a My List now, so the first-run card retires itself instead
                // of asking for a fourth pick.
                if (favorites.size >= 3 && !_uiState.value.pickThreeDone) {
                    setPickThreeDone()
                }
            }
        }
    }

    /**
     * Gap A6: the card's done flag, persisted so a finished card never
     * returns. Dismissal and the third pick both land here.
     */
    private fun observePickThreeDone() {
        viewModelScope.launch {
            settingsRepository.pickThreeDone.collect { done ->
                _uiState.update { it.copy(pickThreeDone = done) }
            }
        }
    }

    fun dismissPickThree() {
        setPickThreeDone()
    }

    private fun setPickThreeDone() {
        _uiState.update { it.copy(pickThreeDone = true) }
        viewModelScope.launch {
            runCatching { settingsRepository.setPickThreeDone(true) }
        }
    }

    /**
     * Gap A5: show the last good Home instantly. A corrupt or empty cache
     * is a no-op — the network load below proceeds exactly as before.
     */
    private suspend fun restoreCachedHome() {
        val json = runCatching { settingsRepository.homeCacheJson.first() }.getOrNull() ?: return
        val payload = decodeHomeCache(json) ?: return
        _uiState.update {
            it.copy(sections = restoreHomeSections(payload), lastHomeSyncMs = payload.updatedAtMs)
        }
    }

    /** Gap A5: keep the cache behind the screen — only a load that actually returned rows. */
    private suspend fun saveHomeCacheIfWorthwhile() {
        val sections = _uiState.value.sections
        if (sections.none { it.items.isNotEmpty() }) return
        val nowMs = System.currentTimeMillis()
        runCatching { settingsRepository.saveHomeCacheJson(encodeHomeCache(sections, nowMs)) }
        _uiState.update { it.copy(lastHomeSyncMs = nowMs) }
    }

    /**
     * Session 121 (P-26): the hero's My List toggle — the same add/remove the details page uses.
     *
     * A v2 row has no v1 post id (its `id` is the negative work-id sentinel),
     * so Room cannot key it: the toggle first resolves the work to its v1 post
     * through the `work_ref` bridge and toggles THAT row. An unresolvable work
     * is a no-op here — the detail screen runs the same resolution and is the
     * place that can say why.
     */
    fun toggleFavorite(post: Post) {
        viewModelScope.launch {
            val target = resolveV1Post(post) ?: return@launch
            if (favoritesRepository.isFavorite(target.id).first()) {
                favoritesRepository.removeFavorite(target.id)
            } else {
                favoritesRepository.addFavorite(target)
            }
        }
    }

    /** The v1 post for a row, or the row itself when it already is one. Null when unresolvable. */
    private suspend fun resolveV1Post(post: Post): Post? {
        if (post.workId == null) return post
        val ref = post.workRef?.takeIf { it.isNotBlank() } ?: return null
        return runCatching {
            catalogRepository.getPosts(workRef = ref, page = 1, limit = 1).results.firstOrNull()
        }.getOrNull()
    }

    /**
     * Phase 7 (D1): remove one title from Continue Watching. The server row goes
     * first (the `removeProgress` endpoint the app defined but never called),
     * then the local rows — the tile disappears either way, because a row the
     * server kept while the device forgot it would come back on the next sync.
     * The tile is kept in memory for Undo: the position it held is the one
     * thing a re-watch cannot give back.
     */
    private var lastRemovedTile: ResumeTile? = null

    fun removeFromContinueWatching(tile: ResumeTile) {
        lastRemovedTile = tile
        _uiState.update { it.copy(removedResumeTitle = tile.post.title) }
        viewModelScope.launch {
            runCatching {
                syncAccountRepository.removeProgress(
                    workRef = tile.workRef,
                    season = tile.season,
                    episode = tile.episode,
                )
            }
            runCatching { watchHistoryDao.remove(tile.workRef, tile.season, tile.episode) }
            runCatching { syncedProgressDao.remove(tile.workRef, tile.season, tile.episode) }
        }
    }

    /** Put the removed tile back: the local row first, then a forced progress report. */
    fun undoRemoveFromContinueWatching() {
        val tile = lastRemovedTile ?: return
        lastRemovedTile = null
        _uiState.update { it.copy(removedResumeTitle = null) }
        viewModelScope.launch {
            runCatching {
                watchHistoryDao.insertIfAbsent(
                    WatchHistoryEntity(
                        workRef = tile.workRef,
                        postId = tile.post.id,
                        title = tile.post.title,
                        posterUrl = tile.post.posterUrl,
                        seasonNumber = tile.season,
                        episodeNumber = tile.episode,
                        positionMs = tile.positionMs,
                        durationMs = tile.durationMs,
                        updatedAt = System.currentTimeMillis(),
                    ),
                )
            }
            runCatching {
                syncAccountRepository.reportProgress(
                    workRef = tile.workRef,
                    season = tile.season,
                    episode = tile.episode,
                    positionMs = tile.positionMs,
                    durationMs = tile.durationMs,
                    forced = true,
                )
            }
        }
    }

    fun clearRemovedResumeNotice() {
        lastRemovedTile = null
        _uiState.update { it.copy(removedResumeTitle = null) }
    }

    fun refresh() {
        loadAll(force = true)
        loadFacets()
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
     * The trial note, read the way Settings reads the same countdown: collected,
     * not sampled, so a grant that landed while Home was closed shows up on the
     * next open. Mirrors SettingsViewModel.observeTrial — the seconds the server
     * said were left, minus the time since this device heard the answer. The
     * entitlement is only a veto for a *known* VIP: a null entitlement (no key,
     * or not loaded yet) does not hide the note, because the trial is granted
     * to the install itself and most trial viewers hold no key at all.
     */
    private fun observeTrialNote() {
        viewModelScope.launch {
            combine(
                settingsRepository.trialRecordedAtMs,
                settingsRepository.trialNoteDismissed,
                syncAccountRepository.entitlement,
            ) { recordedAtMs, dismissed, entitlement ->
                val seconds = if (recordedAtMs <= 0L) {
                    null
                } else {
                    DeviceTrial.secondsRemaining(
                        storedSecondsRemaining = settingsRepository.trialSecondsRemaining.first(),
                        storedAtMs = recordedAtMs,
                        nowMs = System.currentTimeMillis(),
                    )
                }
                trialNoteDaysRemaining(seconds, isVip = entitlement?.vip == true, dismissed = dismissed)
            }.collect { days ->
                _uiState.update { it.copy(trialDaysRemaining = days) }
            }
        }
    }

    /** The trial note is dismissed once, for good — the dismissal is persisted. */
    fun dismissTrialNote() {
        _uiState.update { it.copy(trialDaysRemaining = null) }
        viewModelScope.launch {
            settingsRepository.setTrialNoteDismissed(true)
        }
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
            // A degraded body is a shape guarantee, not the operator's
            // decision: the settings row could not be read, so its sections,
            // broadcasts, hides and update link are shipped defaults. Merging
            // any of it would wipe the operator's real rails with defaults —
            // the fail-open the server's own docstring warns about. Keep the
            // last good state instead, exactly as the watcher does.
            if (config.settingsUnavailable) return@launch
            val notice = AppUpdate.from(config, Brand.versionCode)
                ?.takeUnless { it.url == dismissedUpdateUrl }
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
            // Read once per load, not per rail: the banner that reads this
            // says "offline" about the load that just happened, and four
            // rails asking the same question would answer four times.
            val offline = connectivityProbe.current() == NetworkClass.NONE
            _uiState.update { it.copy(isRefreshing = true, fatal = null, isOffline = offline) }
            // The rows before this load, so the cache is only re-stamped when
            // the network actually returned new rows: re-saving the restored
            // rows with a fresh timestamp after a failed refresh would claim
            // a freshness the load never earned.
            val beforeItems = _uiState.value.sections.associate { it.key to it.items }
            try {
                coroutineScope {
                    _uiState.value.sections
                        .filter { !it.panelManaged && (it.items.isEmpty() || force) }
                        .map { async { loadSection(it) } }
                        .awaitAll()
                }
                _uiState.update { it.copy(isRefreshing = false) }
                val changed = _uiState.value.sections.any { it.items != beforeItems[it.key] }
                if (changed) saveHomeCacheIfWorthwhile()
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
            val results = when {
                section.relatedWorkId != null -> {
                    // "Because you watch": the dedicated route, seeded from
                    // the first Continue Watching post. An empty page hides
                    // the rail; the v2 list cannot serve a seed, so there
                    // is no v2 path here.
                    catalogRepository.getRelated(
                        workId = section.relatedWorkId, page = 1, limit = 18,
                    ).results
                }
                else -> {
                    // Phase 7 (M1): the v2 list first — one row per work, keyset-safe —
                    // with the v1 list as the fallback. An empty v2 page falls back too:
                    // a section type the v2 side cannot serve must not read as "no titles".
                    // A rail that asks for a server sort (only "Most watched" today) keeps
                    // it on both paths; the others keep the v2 default sort.
                    val page = catalogRepository.browseWorksV2(type = section.type, sort = section.sort ?: "trending", limit = 18)
                    if (page != null && page.posts.isNotEmpty()) {
                        page.posts
                    } else if (section.sort == "trending") {
                        // "Most watched": the dedicated /api/v1/trending route
                        // first, the list it replaces behind it — an old
                        // server answers the old route, so the rail never
                        // loses rows to a route it does not have yet.
                        try {
                            catalogRepository.getTrending(type = section.type, page = 1, limit = 18).results
                        } catch (cancelled: CancellationException) {
                            throw cancelled
                        } catch (_: Exception) {
                            catalogRepository.getPosts(type = section.type, sort = section.sort, page = 1, limit = 18).results
                        }
                    } else {
                        catalogRepository.getPosts(type = section.type, sort = section.sort, page = 1, limit = 18).results
                    }
                }
            }
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
