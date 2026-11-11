package com.raddstream.app.viewmodel

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.data.UserRegion
import com.raddstream.app.data.cache.CacheCoordinator
import com.raddstream.app.data.cache.ConnectivityProbe
import com.raddstream.app.data.cache.KeepIdentity
import com.raddstream.app.data.cache.NetworkClass
import com.raddstream.app.data.downloads.DeviceDownloadResult
import com.raddstream.app.data.downloads.DeviceDownloadsRepository
import com.raddstream.app.data.local.SyncedProgressDao
import com.raddstream.app.data.local.WatchHistoryDao
import com.raddstream.app.data.local.WatchHistoryEntity
import com.raddstream.app.network.ApiProvider
import com.raddstream.app.network.friendlyNetworkError
import com.raddstream.app.network.models.LinkState
import com.raddstream.app.network.models.PostDetail
import com.raddstream.app.network.models.parseCastNames
import com.raddstream.app.network.streamRedirectUrl
import com.raddstream.app.network.withVipPass
import com.raddstream.app.player.AdoptRequest
import com.raddstream.app.player.CacheAffordance
import com.raddstream.app.player.CacheEngineHolder
import com.raddstream.app.player.CacheSessionKey
import com.raddstream.app.player.DataSaver
import com.raddstream.app.player.KeepResult
import com.raddstream.app.player.LadderForScope
import com.raddstream.app.player.LadderRung
import com.raddstream.app.player.PlayerSessionStore
import com.raddstream.app.player.PreviewRequest
import com.raddstream.app.player.QualityLadder
import com.raddstream.app.player.QualityOption
import com.raddstream.app.player.SubtitleTrackInfo
import com.raddstream.app.player.webDownloadUrl
import com.raddstream.app.player.webDownloadUrlWithCredit
import com.raddstream.app.repository.CatalogRepository
import com.raddstream.app.repository.FavoritesRepository
import com.raddstream.app.repository.V2PlayResult
import com.raddstream.app.sync.SyncAccountRepository
import com.raddstream.app.ui.navigation.Screen
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout

data class DetailUiState(
    val post: PostDetail? = null,
    val layout: ReleaseLayout? = null,
    val selectedSeason: Int? = null,
    val isLoading: Boolean = true,
    val isFavorite: Boolean = false,
    val error: String? = null,
    val actionMessage: String? = null,
    /** One row per quality band, as the server collapsed them. Empty until it has any. */
    val ladder: LadderForScope = LadderForScope.EMPTY,
    /**
     * The viewer's regional-dub preference ([UserRegion]), mirrored so the
     * quality card can lead with the viewer's own audio (audit #32).
     * [UserRegion.DEFAULT] until DataStore answers.
     */
    val region: String = UserRegion.DEFAULT,
    /** The scope [ladder] belongs to. Both null = the whole work; the card says which. */
    val ladderSeason: Int? = null,
    val ladderEpisode: Int? = null,
    /** null / [LadderForScope.AUTO] = let the ladder's own pointer choose the rung. */
    val selectedBand: String? = LadderForScope.AUTO,
    /**
     * Whether the house sponsor card may be shown for this viewer at all. False is the
     * ordinary case; a confirmed membership or a live rewarded pass turns the card off, which
     * is what both of those offers say they do.
     */
    val adFree: Boolean = false,
    /** The ledger's answer, mirrored so the quality gate and its upsell read one fact. */
    val vip: Boolean = false,
    /** True when this title has 4K/1080p sources that the current viewer cannot play. */
    val premiumSourcesLocked: Boolean = false,
    /** The latest scope this device stopped in, if any — the Resume button. */
    val resume: ResumePoint? = null,
    /** True when the Resume button has a print to play; false shows plain Play. */
    val resumePlayable: Boolean = false,
    /**
     * True once the resume lookup has answered — including "never watched".
     * Session 123 (DE-1): `resume` being null is ambiguous (not loaded yet,
     * or never watched), and autoplay must not decide until it knows which.
     * False until [loadResume] settles, on every path out of it.
     */
    val resumeLoaded: Boolean = false,
    /** Per-episode progress, keyed by (season, episode) — the marks on episode rows. */
    val episodeProgress: Map<Pair<Int, Int>, EpisodeProgress> = emptyMap(),
    /**
     * What this viewer can actually watch of this title, in one line. Null
     * when the title has no prints at all — then "no playable releases"
     * says it instead.
     */
    val includedLine: String? = null,
    /**
     * A download the viewer has been asked to confirm, with the size and the
     * quality in front of them. Null when nothing is waiting — the download
     * only starts on Confirm.
     */
    val pendingKeep: PendingKeep? = null,
    /**
     * Session 76 (Build 4): the direct-download price (coins for one movie)
     * and the viewer's balance, read when the keep dialog opens so a free
     * viewer can see what a direct link costs and whether they can afford it.
     * Zero price means the server predates the credit — no direct link is offered.
     */
    val downloadCreditPrice: Int = 0,
    val coinBalance: Int = 0,
    /** The answer to a [directDownloadUrlFor] ask that could not open a link. */
    val directLinkMessage: String? = null,
)

/**
 * A download waiting for the viewer's Confirm. The size comes from the one
 * metadata ask that also decides which download system owns the copy, so
 * the dialog never guesses it; null means the server did not name a size,
 * and the dialog says "Size unknown" instead of inventing one.
 *
 * Public because it is part of the public [DetailUiState] shape (and of the
 * screen's confirm dialog): a public state class cannot expose an internal
 * type, and neither can its own `target` — so [KeepTarget] is public too.
 */
data class PendingKeep(
    val handle: String,
    val printLabel: String,
    val title: String,
    val sizeBytes: Long?,
    val resumable: Boolean,
    val target: KeepTarget,
)

/** The size line of the keep-confirm dialog: a real size, or an honest unknown. */
fun keepSizeLabel(sizeBytes: Long?): String =
    sizeBytes?.takeIf { it > 0 }?.let { CacheAffordance.formatBytes(it) } ?: "Size unknown"

/**
 * The dialog's one primary action (audit #10/#11): the version and its
 * size are named together, so the size is tied to the choice being made.
 * "Download 480p · 730 MB"; a size the server never named says so
 * instead of inventing one.
 */
fun downloadConfirmLabel(printLabel: String, sizeBytes: Long?): String {
    val label = printLabel.trim().ifBlank { "this version" }
    val size = sizeBytes?.takeIf { it > 0 }?.let { CacheAffordance.formatBytes(it) }
    return if (size != null) "Download $label · $size" else "Download $label"
}

/**
 * What a keep request needs is a file. A page is not one: DownloadManager would fetch HTML and
 * the Downloads row would then claim a film had been kept. The screen offers the page instead,
 * and says why it is not in the kept list.
 */
private const val PAGE_NOT_A_FILE =
    "This source is a page on the provider's site, not a file — open it instead of keeping it."

sealed class DetailNavigationEvent {
    /** Navigate by OPAQUE HANDLE only — a URL in a route would live in the back stack. */
    data class PlayStream(val streamId: String, val title: String) : DetailNavigationEvent()

    /** The one hand-off this app makes, and it carries OUR OWN address. */
    data class OpenExternal(val streamId: String, val playUrl: String) : DetailNavigationEvent()

    /**
     * The server says this link is a page, not a file (`ProviderPageLinks`), so our player has
     * nothing to load. The provider's own page is shown, in the foreground, with its own controls
     * and its own conditions. It carries the OPAQUE HANDLE for the reason [PlayStream] does: the
     * screen rebuilds our redirector from the server the viewer connected to, and no upstream
     * address ever enters a back stack.
     */
    data class OpenProviderPage(val streamId: String, val title: String) : DetailNavigationEvent()

    /** A download Android accepted: its public file is already moving, so show Downloads. */
    data class DownloadStarted(val label: String) : DetailNavigationEvent()

    /** A legacy device must grant storage before a public download can start. */
    data object DownloadNeedsPermission : DetailNavigationEvent()
}

@HiltViewModel
class DetailViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    private val catalogRepository: CatalogRepository,
    private val favoritesRepository: FavoritesRepository,
    private val deviceDownloads: DeviceDownloadsRepository,
    private val apiProvider: ApiProvider,
    private val syncAccountRepository: SyncAccountRepository,
    private val settingsRepository: ServerSettingsRepository,
    private val watchHistoryDao: WatchHistoryDao,
    private val syncedProgressDao: SyncedProgressDao,
    private val connectivityProbe: ConnectivityProbe,
) : ViewModel() {

    private val postId: Int = (savedStateHandle[Screen.Detail.ARG_POST_ID] as? String)?.toIntOrNull()
        ?: (savedStateHandle[Screen.Detail.ARG_POST_ID] as? Int)
        ?: -1

    /**
     * Phase 7 (M1): the v2 work id, when this screen was opened from a v2 list.
     * -1 means "not a v2 row" — the v1 path below. A nav argument arrives as a
     * Long from the typed argument, or as a String from a deep link; both read.
     */
    private val workId: Long = (savedStateHandle[Screen.Detail.ARG_WORK_ID] as? Long)
        ?: (savedStateHandle[Screen.Detail.ARG_WORK_ID] as? String)?.toLongOrNull()
        ?: (savedStateHandle[Screen.Detail.ARG_WORK_ID] as? Int)?.toLong()
        ?: -1L

    /** The v1 post id the favorite/resume/adoption calls may use — 0 until the v2 bridge resolves. */
    private var resolvedPostId: Int = postId

    private val _uiState = MutableStateFlow(DetailUiState())
    val uiState = _uiState.asStateFlow()

    private val _navEvents = MutableSharedFlow<DetailNavigationEvent>()
    val navEvents: SharedFlow<DetailNavigationEvent> = _navEvents.asSharedFlow()

    init {
        loadDetail()
        observeFavorite()
        observeEntitlement()
        observeServerBase()
    }

    /**
     * Session 73 (Phase 5): keep the server origin for the [Get Free Web Link]
     * action — the link opens `<origin>/api/v1/download?id=<handle>&via=web`
     * in the external browser, never inside the app.
     */
    private fun observeServerBase() {
        viewModelScope.launch {
            settingsRepository.serverUrl.collect { base ->
                serverBaseUrl = base ?: ""
            }
        }
    }

    /**
     * Session 73 (Phase 5): the external-browser download URL for a pending keep's
     * handle. Pure builder in [webDownloadUrl]; the browser, not the app, is
     * what follows the server's redirect — the app never shortens anything itself.
     */
    fun webDownloadUrlFor(handle: String): String = webDownloadUrl(serverBaseUrl, handle)

    /**
     * Whether this viewer is owed a page without the house card. Both inputs are pushed, so a
     * membership approved while this screen was open removes the card without a reload; the
     * rule itself lives in [RewardedVipPass.isAdFree], which the player applies identically.
     *
     * The entitlement also decides which sources exist on this page (see [VipQualityGate]), so
     * the same push rebuilds the gated layout and ladder — a viewer who upgrades while looking
     * at a title gets its 4K rungs without reopening the screen.
     */
    private fun observeEntitlement() {
        viewModelScope.launch {
            syncAccountRepository.entitlement.collect { earned ->
                serverVip = earned?.vip == true
                publishViewerContent()
            }
        }
        viewModelScope.launch {
            settingsRepository.rewardedVipExpiresAt.collect { expiresAt ->
                rewardedExpiresAt = expiresAt
                publishViewerContent()
            }
        }
        viewModelScope.launch {
            settingsRepository.qualityGateEnabled.collect { enabled ->
                qualityGateEnabled = enabled
                publishViewerContent()
            }
        }
        viewModelScope.launch {
            settingsRepository.freeQualityCap.collect { cap ->
                freeQualityCap = cap
                publishViewerContent()
            }
        }
        viewModelScope.launch {
            settingsRepository.dataSaver.collect { enabled ->
                dataSaver = enabled
            }
        }
        viewModelScope.launch {
            settingsRepository.wifiOnlyDownloads.collect { enabled ->
                wifiOnlyDownloads = enabled
            }
        }
        viewModelScope.launch {
            settingsRepository.userRegion.collect { region ->
                userRegion = region
                _uiState.update { it.copy(region = region) }
                publishViewerContent()
            }
        }
        viewModelScope.launch {
            settingsRepository.downloadsFeatureEnabled.collect { enabled ->
                downloadsEnabled = enabled
            }
        }
    }

    private var serverVip: Boolean = false
    private var rewardedExpiresAt: Long = 0L
    /** Session 73 (Phase 5): the server origin this install talks to, kept for the Web Download link. Empty until DataStore answers. */
    private var serverBaseUrl: String = ""

    /**
     * The operator's switch, not this screen's opinion. Off is the shipped default, so the
     * catalog stays whole for a free viewer until the owner decides 1080p/4K should cost
     * something; [premiumAccess] is what every gate call below actually passes.
     */
    private var qualityGateEnabled: Boolean = false
    private var freeQualityCap: String = "720p"
    /** Data Saver and Wi-Fi-only downloads — both on by default, both the viewer's own choice. */
    private var dataSaver: Boolean = true
    private var wifiOnlyDownloads: Boolean = true

    /** True while the network is Wi-Fi; anything else is mobile data for these two switches. */
    private val onWifi: Boolean get() = connectivityProbe.current() == NetworkClass.WIFI

    /**
     * The viewer's regional-dub preference; [UserRegion.DEFAULT] until DataStore answers,
     * which already is the shipped default. It only reorders the release selector.
     */
    private var userRegion: String = UserRegion.DEFAULT

    /**
     * The operator's `feature_flags.downloads`, on until the board says otherwise. Obeyed at
     * [keep], the one choke point every keep affordance on this screen funnels through, so
     * switching the feature off stops bytes reaching the device rather than merely hiding a row.
     */
    private var downloadsEnabled: Boolean = true

    /** Who may see the top rungs: a confirmed member, or everyone while the switch is off. */
    private val premiumAccess: Boolean get() = VipQualityGate.premiumAccess(qualityGateEnabled, serverVip)

    /** The ungated catalog answer; every gated view is derived from it on entitlement change. */
    private var rawDetail: PostDetail? = null

    /**
     * Rebuild the presentation from the raw detail and the current viewer. Both the print list
     * and the quality ladder go through [VipQualityGate]; a VIP viewer gets the original objects
     * back unchanged, so this costs nothing on the ordinary paid path.
     */
    private fun publishViewerContent() {
        val detail = rawDetail
        if (detail == null) {
            _uiState.update {
                it.copy(adFree = RewardedVipPass.isAdFree(serverVip, rewardedExpiresAt))
            }
            return
        }
        val artwork = detail.backdropList.ifEmpty {
            listOfNotNull(detail.posterUrl?.takeIf(String::isNotBlank))
        }
        val full = ReleaseLayoutBuilder.build(
            detail.contentType,
            detail.releases,
            artwork,
            detail.seasonArtwork,
            region = userRegion,
        )
        val state = _uiState.value
        val scope = QualityLadder.forNumberedScope(
            detail.optionGroups,
            state.ladderSeason,
            state.ladderEpisode,
        )
        val premiumLocked = qualityGateEnabled && !serverVip && (
            VipQualityGate.hasPlayablePremiumPrints(full, freeQualityCap) ||
                scope.options.any {
                    (VipQualityGate.isPremiumBand(it.band, freeQualityCap) || VipQualityGate.isPremiumLabel(it.title, freeQualityCap)) &&
                        it.band !in scope.downloadOnlyBands
                }
            )
        // What this viewer can watch, in one line — the free cap is the
        // operator's, so the line names it rather than a hardcoded 720p.
        val hasPrints = full.workPrints.isNotEmpty() ||
            full.seasons.any { it.episodes.isNotEmpty() || it.packedPrints.isNotEmpty() }
        val includedLine = if (!hasPrints) {
            null
        } else if (serverVip) {
            "Included with VIP — up to 4K"
        } else if (!qualityGateEnabled) {
            "Included in your plan — up to 4K"
        } else if (premiumLocked) {
            if (freeQualityCap == "480p") {
                "480p included — 720p, 1080p and 4K need VIP"
            } else {
                "720p included — 1080p and 4K need VIP"
            }
        } else {
            "Included in free — up to $freeQualityCap"
        }
        _uiState.update {
            it.copy(
                layout = VipQualityGate.gate(full, premiumAccess, freeQualityCap),
                ladder = VipQualityGate.gate(scope, premiumAccess, freeQualityCap),
                vip = serverVip,
                premiumSourcesLocked = premiumLocked,
                includedLine = includedLine,
                adFree = RewardedVipPass.isAdFree(serverVip, rewardedExpiresAt),
            )
        }
        loadResume()
    }

    /**
     * The resume point and episode marks for this title, from the history
     * this device wrote. A title never watched has neither, and the screen
     * shows a plain Play button instead of a Resume one.
     */
    private fun loadResume() {
        val workRef = _uiState.value.post?.workRef?.takeIf { it.isNotBlank() }
        if (workRef == null) {
            // No work identity, so no history to look up — the lookup is
            // settled with "never watched", not left hanging.
            _uiState.update { it.copy(resumeLoaded = true) }
            return
        }
        viewModelScope.launch {
            val rows = runCatching { watchHistoryDao.findWork(workRef) }.getOrNull()
            if (rows == null) {
                _uiState.update { it.copy(resumeLoaded = true) }
                return@launch
            }
            val resume = resumePointFor(rows)
            // The button only shows when its print is still on the page:
            // a resume whose episode lost every print is a dead button.
            val playable = _uiState.value.layout?.let { resumePrintFor(it, resume) != null } ?: false
            _uiState.update {
                it.copy(
                    resume = resume,
                    resumePlayable = playable,
                    resumeLoaded = true,
                    episodeProgress = episodeProgressFor(rows),
                )
            }
        }
    }

    /** Play the Resume button's episode: its best print, not the work's. */
    fun playResume() {
        val layout = _uiState.value.layout ?: return
        val print = resumePrintFor(layout, _uiState.value.resume) ?: return
        playPrint(print)
    }

    private fun observeFavorite() {
        if (resolvedPostId <= 0) return
        viewModelScope.launch {
            favoritesRepository.isFavorite(resolvedPostId).collect { fav ->
                _uiState.update { it.copy(isFavorite = fav) }
            }
        }
    }

    fun loadDetail() {
        if (postId < 0 && workId < 0) {
            _uiState.update { it.copy(isLoading = false, error = "This title could not be opened.") }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            try {
                // Phase 7 (M1): a v2 row opens through the v2 detail route —
                // the work id is the only key it has. The repository bridges
                // the work_ref back to a v1 post for cast + season art, and
                // the returned detail carries that post id (0 when the bridge
                // found no post: the title still loads, but nothing may write
                // a Room row under id 0).
                val detail = if (workId >= 0) {
                    catalogRepository.getWorkDetailV2(workId)
                } else {
                    catalogRepository.getPostDetail(postId)
                }
                if (detail != null) {
                    // Wide art only: a portrait poster cropped into a 16:9 still looks broken,
                    // so it is used just when the catalog has no backdrop at all.
                    val artwork = detail.backdropList.ifEmpty {
                        listOfNotNull(detail.posterUrl?.takeIf(String::isNotBlank))
                    }
                    val layout = ReleaseLayoutBuilder.build(
                        detail.contentType,
                        detail.releases,
                        artwork,
                        detail.seasonArtwork,
                        region = userRegion,
                    )
                    rawDetail = detail
                    _uiState.update {
                        it.copy(
                            post = detail,
                            selectedSeason = layout.seasons.firstOrNull()?.number,
                            isLoading = false,
                        )
                    }
                    // The catalog answer is ungated; what the viewer may SEE is decided here,
                    // from the entitlement the repository already holds.
                    publishViewerContent()
                    // Gap A2: pre-resolve the top link now, while the viewer
                    // is still reading the page, so Play does not pay the
                    // `playV2` round trip first.
                    preresolveTopLink()
                    // A row saved before this app had a handle becomes syncable the moment the
                    // catalog finally names its work. Nothing here fabricates a handle: an absent
                    // key is a no-op, and a present one is the server's own. On the v2 path the
                    // bridge's post id is the only id these calls may use — a 0 must never
                    // reach Room or the sync account.
                    if (detail.id > 0) {
                        if (workId >= 0) {
                            resolvedPostId = detail.id
                            observeFavorite()
                        }
                        syncAccountRepository.adoptWorkRef(detail.id, detail.workRef)
                    }
                } else {
                    _uiState.update {
                        it.copy(isLoading = false, error = "This title is not available on the connected server.")
                    }
                }
            } catch (ex: Exception) {
                _uiState.update {
                    it.copy(isLoading = false, error = friendlyNetworkError(ex, "Failed to load details. Check connection."))
                }
            }
        }
    }

    fun selectSeason(season: Int) {
        _uiState.update { it.copy(selectedSeason = season) }
        // A season that ships as one packed file has a season-level ladder; a season of
        // separate episode releases does not, and the card goes away until an episode asks.
        showRungsFor(season, null)
    }

    fun toggleFavorite() {
        val currentPost = _uiState.value.post ?: return
        // Phase 7 (M1): a v2 detail whose work_ref bridge found no v1 post
        // carries id 0 — toggling it would write a junk Room row under 0.
        // The title is still viewable; only saving is refused, honestly.
        if (currentPost.id <= 0) {
            _uiState.update { it.copy(actionMessage = "Could not save this title right now.") }
            return
        }
        viewModelScope.launch {
            val isNowFav = favoritesRepository.toggleFavorite(currentPost)
            _uiState.update {
                it.copy(
                    isFavorite = isNowFav,
                    actionMessage = if (isNowFav) "Added to My List" else "Removed from My List",
                )
            }
        }
    }

    /**
     * Phase 7 (D1): "Start over" — forget where viewing stopped for the scope
     * the Resume button would play. The server row goes first (the
     * `removeProgress` endpoint the app defined but never called), then the
     * local rows; the resume state clears either way, so a refused server
     * delete can only bring the row back on the next sync, never by keeping
     * a button the viewer just removed.
     */
    fun removeProgress() {
        val detail = _uiState.value.post ?: return
        val ref = detail.workRef?.takeIf { it.isNotBlank() } ?: return
        val resume = _uiState.value.resume
        val season = resume?.season ?: 0
        val episode = resume?.episode ?: 0
        viewModelScope.launch {
            runCatching { syncAccountRepository.removeProgress(workRef = ref, season = season, episode = episode) }
            runCatching { watchHistoryDao.remove(ref, season, episode) }
            runCatching { syncedProgressDao.remove(ref, season, episode) }
            _uiState.update {
                it.copy(
                    resume = null,
                    resumePlayable = false,
                    actionMessage = "Removed from Continue Watching",
                )
            }
        }
    }

    fun clearActionMessage() {
        _uiState.update { it.copy(actionMessage = null) }
    }

    /**
     * The server's one-row-per-band ladder for one scope. A movie is a single null/null
     * group; a series asks per episode. An unmatched episode gets NOTHING rather than
     * another episode's links, and a ledger that has exactly one group is treated as the
     * whole title, because that is what a movie's payload looks like.
     */
    fun ladderFor(season: Int?, episode: Int?): LadderForScope =
        VipQualityGate.gate(
            QualityLadder.forNumberedScope(
                _uiState.value.post?.optionGroups.orEmpty(),
                season,
                episode,
            ),
            premiumAccess,
            freeQualityCap,
        )

    /**
     * Point the quality card at one scope. A series has a ladder per episode — offering
     * S02E05's 1080p copy while the viewer is looking at S01E01 would be a lie about what
     * they are about to get — so an episode row asks for its own rung list and the card
     * says which scope it belongs to. A season with no packed file has no season-level
     * ladder, and the card correctly disappears.
     */
    fun showRungsFor(season: Int?, episode: Int?) {
        _uiState.update {
            it.copy(
                ladder = VipQualityGate.gate(
                    QualityLadder.forNumberedScope(
                        _uiState.value.post?.optionGroups.orEmpty(),
                        season,
                        episode,
                    ),
                    premiumAccess,
                    freeQualityCap,
                ),
                ladderSeason = season,
                ladderEpisode = episode,
                selectedBand = LadderForScope.AUTO,
            )
        }
    }

    /** A rung this app cannot present is downloaded, and the row says so — no hidden failure. */
    fun keepRung(option: QualityOption) {
        if (isLocked(option)) {
            _uiState.update { it.copy(actionMessage = VipQualityGate.lockedMessage(freeQualityCap)) }
            return
        }
        if (option.isProviderPage) {
            _uiState.update { it.copy(actionMessage = PAGE_NOT_A_FILE) }
            return
        }
        _uiState.update { it.copy(selectedBand = option.band) }
        keep(
            handle = option.streamId,
            printLabel = option.title,
        )
    }

    /**
     * The tier a rung requires: VIP when the operator's gate reserves its band,
     * Standard otherwise. A property of the stream and the operator's policy,
     * never of the viewer — a VIP viewer reads "VIP" on the 1080p row they can
     * play, and a free viewer never sees that row at all (the gate removed it
     * and VipSourcesCard says where it went). With the gate off, every rung is
     * Standard because nothing requires VIP.
     */
    fun tierLabelFor(option: QualityOption): String =
        if (qualityGateEnabled &&
            (VipQualityGate.isPremiumBand(option.band, freeQualityCap) ||
                VipQualityGate.isPremiumLabel(option.title, freeQualityCap))
        ) "VIP" else "Standard"

    /** A premium rung the current viewer may not take, decided from the same gate the UI uses. */
    private fun isLocked(option: QualityOption): Boolean =
        !VipQualityGate.allowsBand(option.band, premiumAccess, freeQualityCap) ||
            (!premiumAccess && VipQualityGate.isPremiumLabel(option.title, freeQualityCap))

    /**
     * Keep one rung for offline playback, by OUR opaque handle.
     *
     * Which system owns the copy depends on what it is: a single file goes to the
     * device download (a public file in Movies/RaddStream); a segmented playlist
     * goes to the keep engine, which fetches the segments and plays them back
     * offline in-app. A page is neither and is refused before either is asked.
     *
     * Every branch answers out loud: an accepted download routes to the Downloads
     * screen where its row is already moving; a legacy device learns it must grant
     * storage first, because a button that quietly does nothing is worse than one
     * that says no. The address handed to either system is our own redirector —
     * the server verified the handle, and the upstream location never enters this app.
     */
    private fun keep(handle: String, printLabel: String) {
        lastDownload = handle to printLabel
        if (!downloadsEnabled) {
            lastDownload = null
            _uiState.update { it.copy(actionMessage = "Keeping files for offline is switched off for this server.") }
            return
        }
        if (handle.isBlank()) {
            _uiState.update { it.copy(actionMessage = "Nothing to download on this rung yet.") }
            return
        }
        // Session 123: the Wi-Fi-only gate, at the tap — the same gate
        // `keepPrint` already honours. The dialog must not offer a download
        // the switch forbids, and the viewer must hear why now, not after
        // confirming a size for a file that will never start.
        if (DataSaver.wifiOnlyBlocks(wifiOnlyDownloads, onWifi)) {
            _uiState.update {
                it.copy(actionMessage = "Wi-Fi only is on — connect to Wi-Fi to download this title. You can change it in Settings.")
            }
            return
        }
        val workTitle = _uiState.value.post?.let { it.cleanTitle ?: it.title } ?: "Stream"
        viewModelScope.launch {
            // One metadata ask decides which download system owns this copy. A failed
            // ask falls through to the device path, which refuses with the same words it
            // always used — no new failure shape for a server that cannot answer. The
            // download does NOT start here: the size and the quality go in front of the
            // viewer first, and only Confirm starts either system.
            val meta = runCatching { catalogRepository.resolveStream(handle) }.getOrNull()
            val target = if (meta != null && meta.success) {
                keepTargetFor(meta.mimeType)
            } else {
                KeepTarget.DeviceFile
            }
            _uiState.update {
                it.copy(
                    pendingKeep = PendingKeep(
                        handle = handle,
                        printLabel = printLabel,
                        title = workTitle,
                        sizeBytes = meta?.fileSizeBytes?.takeIf { it > 0 },
                        resumable = meta?.resumable ?: false,
                        target = target,
                    ),
                    directLinkMessage = null,
                )
            }
            // Session 76 (Build 4): a free viewer asking for a file can also
            // buy a direct link with coins — read the price and the balance
            // while the dialog is open, so the button can say what it costs
            // and whether the wallet covers it. VIP viewers never see it;
            // their downloads are already direct.
            if (!_uiState.value.vip) {
                val price = syncAccountRepository.loadDownloadCreditPrice()
                val balance = syncAccountRepository.loadCoinBalance()
                _uiState.update {
                    it.copy(
                        downloadCreditPrice = price,
                        coinBalance = balance ?: it.coinBalance,
                    )
                }
            }
        }
    }

    /**
     * Session 76 (Build 4): buy one direct download of [handle] with coins and
     * hand back the browser URL that spends the credit. Null when the server
     * cannot be reached or the credit is already spent — the reason is in
     * [DetailUiState.directLinkMessage], never invented here.
     */
    suspend fun directDownloadUrlFor(handle: String): String? {
        val credit = syncAccountRepository.redeemDownloadCredit(handle)
        if (credit == null) {
            _uiState.update {
                it.copy(directLinkMessage = "Could not reach the server — try again.")
            }
            return null
        }
        val token = credit.token
        if (token.isNullOrBlank()) {
            _uiState.update {
                it.copy(directLinkMessage = "That direct link was already used.")
            }
            return null
        }
        _uiState.update { it.copy(coinBalance = credit.balance, directLinkMessage = null) }
        return webDownloadUrlWithCredit(serverBaseUrl, handle, token)
    }

    /**
     * Report one share of this title, after the chooser already fired. The
     * server pays once a day, so the message shows only when the server says
     * it granted — a second share the same day is silent, not a nag. A failed
     * report is silent too: the share already left the phone, and a coin
     * report must never undo it.
     */
    fun reportShare(workRef: String?) {
        val ref = workRef?.takeIf { it.isNotBlank() } ?: return
        viewModelScope.launch {
            val share = syncAccountRepository.reportShare(ref)
            if (share != null && share.granted && share.coins > 0) {
                _uiState.update {
                    it.copy(actionMessage = "+${share.coins} coins for sharing",
                            coinBalance = share.balance)
                }
            }
        }
    }

    /** The viewer confirmed the size and the quality: start whichever system owns the copy. */
    fun confirmKeep() {
        val pending = _uiState.value.pendingKeep ?: return
        _uiState.update { it.copy(pendingKeep = null, directLinkMessage = null) }
        // Session 123: the gate again, at confirm time — the Wi-Fi state can
        // change while the dialog is open, and the confirm is the moment the
        // bytes would actually start. A viewer who walked out of Wi-Fi range
        // while reading the size hears why nothing started.
        if (DataSaver.wifiOnlyBlocks(wifiOnlyDownloads, onWifi)) {
            _uiState.update {
                it.copy(actionMessage = "Wi-Fi only is on — connect to Wi-Fi to download this title. You can change it in Settings.")
            }
            return
        }
        viewModelScope.launch {
            if (pending.target == KeepTarget.EngineHls) {
                keepViaEngine(pending.handle, pending.printLabel, pending.title, pending.sizeBytes, pending.resumable)
                return@launch
            }
            when (val outcome = deviceDownloads.enqueue(pending.handle, pending.title, pending.printLabel)) {
                is DeviceDownloadResult.Enqueued -> {
                    lastDownload = null
                    _navEvents.emit(DetailNavigationEvent.DownloadStarted(pending.printLabel))
                }
                is DeviceDownloadResult.NeedsPermission ->
                    _navEvents.emit(DetailNavigationEvent.DownloadNeedsPermission)
                is DeviceDownloadResult.Refused -> {
                    lastDownload = null
                    _uiState.update { it.copy(actionMessage = outcome.message) }
                }
            }
        }
    }

    /** The viewer declined the download: nothing started, nothing to clean up except the ask. */
    fun dismissKeep() {
        lastDownload = null
        _uiState.update { it.copy(pendingKeep = null, directLinkMessage = null) }
    }

    /**
     * Keep one HLS title through the in-app keep engine: it fetches the playlist's
     * segments from our redirector and plays them back offline. Adopt pins the row,
     * so the sweeper never ages out a file the Downloads list calls kept.
     */
    private suspend fun keepViaEngine(
        handle: String,
        printLabel: String,
        title: String,
        sizeBytes: Long?,
        resumable: Boolean,
    ) {
        val engine = CacheEngineHolder.engine
        if (engine == null) {
            lastDownload = null
            _uiState.update { it.copy(actionMessage = "Download engine not wired into this build yet") }
            return
        }
        val baseUrl = runCatching { apiProvider.currentBaseUrl() }.getOrNull()
        if (baseUrl == null) {
            lastDownload = null
            _uiState.update { it.copy(actionMessage = "Connect to a catalog server before downloading.") }
            return
        }
        val url = withVipPass(
            streamRedirectUrl(baseUrl, handle),
            // Session 123: the keep fetches bytes through the same redirector
            // the player uses, so the same pass rides it — a VIP keep of a
            // premium print downloads instead of 402ing.
            syncAccountRepository.currentVipPass(),
        )
        val request = AdoptRequest(
            key = CacheSessionKey(renditionKey = handle, url = url),
            url = url,
            fetchedBytesSoFar = 0L,
            isByteCursorKnown = false,
            positionMs = 0L,
            bufferedMs = 0L,
            durationMs = 0L,
            expectedTotalBytes = sizeBytes?.takeIf { it > 0 },
            resumable = resumable,
            printLabel = printLabel,
            title = title,
            sharesCacheStorage = false,
        )
        val result = try {
            engine.adopt(request)
        } catch (t: Throwable) {
            KeepResult.Failed(t.message ?: "engine error")
        }
        when (result) {
            is KeepResult.Stored, is KeepResult.OnlyPlayableInApp -> {
                lastDownload = null
                _navEvents.emit(DetailNavigationEvent.DownloadStarted(printLabel))
            }
            is KeepResult.StorageFull -> {
                lastDownload = null
                _uiState.update {
                    it.copy(
                        actionMessage = "Not enough space to keep this title — needs " +
                            CacheAffordance.formatBytes(result.requiredBytes) + ", " +
                            CacheAffordance.formatBytes(result.availableBytes) + " free.",
                    )
                }
            }
            is KeepResult.Failed -> {
                lastDownload = null
                _uiState.update { it.copy(actionMessage = result.message) }
            }
            is KeepResult.Interrupted -> {
                lastDownload = null
                _uiState.update { it.copy(actionMessage = "Download paused — it will resume on its own.") }
            }
            KeepResult.EngineNotWired -> {
                lastDownload = null
                _uiState.update { it.copy(actionMessage = "Download engine not wired into this build yet") }
            }
        }
    }

    /** Re-run the request that stopped for a storage grant, once the viewer allows it. */
    fun retryLastDownload() {
        lastDownload?.let { (handle, label) -> keep(handle, label) }
    }

    private var lastDownload: Pair<String, String>? = null

    /**
     * Gap A2 — the pre-resolved top link: the `playV2` bundle for the best
     * print, resolved when the detail opened, so Play reuses it instead of
     * calling the server again. A failed pre-resolve leaves all three null
     * and Play falls back to its own call — a warm-up that fails is silent,
     * never an error the viewer sees.
     */
    private var preresolvedReleaseId: Int? = null
    private var preresolvedResult: V2PlayResult? = null
    private var preresolvedAtMs: Long? = null
    private var preresolveJob: Job? = null

    /**
     * Gap A2: resolve the best print's `playV2` bundle while the viewer is
     * still on the detail page. Same 2 s ceiling and same quality
     * preference as the Play-press call, same print Play would pick, and a
     * locked print is never warmed — warming a rung the viewer may not
     * play would spend the server's answer on nothing.
     *
     * On Wi-Fi the winner's first bytes are also pre-buffered through the
     * engine's preview seed (the same bounded, silent seed the player uses
     * for the next episode): the budget there decides whether the bytes are
     * affordable, and a preview that fails is silent — Play still works, it
     * just waits on the first bytes again. Mobile data never pre-buffers.
     */
    private fun preresolveTopLink() {
        preresolveJob?.cancel()
        preresolvedReleaseId = null
        preresolvedResult = null
        preresolvedAtMs = null
        val best = bestPrintOf(_uiState.value.layout) ?: return
        if (!VipQualityGate.allowsResolution(best.resolution, premiumAccess)) return
        preresolveJob = viewModelScope.launch {
            val result = runCatching {
                withTimeout(2_000) {
                    catalogRepository.playV2(
                        best.releaseId,
                        prefer = DataSaver.playPrefer(dataSaver, onWifi),
                    )
                }
            }.getOrNull() ?: return@launch
            if (result.bundle.renditions.isEmpty()) return@launch
            preresolvedReleaseId = best.releaseId
            preresolvedResult = result
            preresolvedAtMs = System.currentTimeMillis()
            if (onWifi) seedPreviewTopLink(best, result)
        }
    }

    /** Gap A2: the Wi-Fi pre-buffer for the pre-resolved winner. Silent by contract. */
    private suspend fun seedPreviewTopLink(best: RankedPrint, result: V2PlayResult) {
        val winner = result.bundle.renditions.firstOrNull() ?: return
        val playUrl = winner.playUrl?.takeIf { it.isNotBlank() } ?: return
        val handle = winner.streamId?.takeIf { it.isNotBlank() } ?: return
        val engine = CacheEngineHolder.engine ?: return
        val url = withVipPass(playUrl, runCatching { syncAccountRepository.currentVipPass() }.getOrNull())
        runCatching {
            engine.seedPreview(
                PreviewRequest(
                    key = CacheSessionKey(renditionKey = handle, url = url),
                    url = url,
                    expectedTotalBytes = best.sizeBytes?.takeIf { it > 0L },
                    resumable = winner.resumable,
                    printLabel = winner.label ?: best.rawTitle ?: "Top link",
                ),
            )
        }
    }

    /**
     * Play one rung of the ladder. The rung's runner-ups and the ladder itself are staged
     * for the player first, so a CDN that refuses mid-play costs a silent hop instead of a
     * dialog, and a viewer who chose Auto can be moved along these same rungs by the
     * measured throughput — while the navigation route still carries one opaque handle only.
     */
    fun playLadder(option: QualityOption, external: Boolean = false) {
        if (isLocked(option)) {
            _uiState.update { it.copy(actionMessage = VipQualityGate.lockedMessage(freeQualityCap)) }
            return
        }
        val title = _uiState.value.post?.let { it.cleanTitle ?: it.title } ?: "Stream"
        if (option.streamId.isBlank()) {
            _uiState.update { it.copy(actionMessage = "Nothing playable on this rung yet.") }
            return
        }
        // A rung that is a page is not staged and not played: nothing starts, so there is no
        // resume point to write and no position for Auto to hop to. Staging it would put an HTML
        // page in the failover list the player walks when a CDN refuses.
        if (option.isProviderPage) {
            _uiState.update { it.copy(selectedBand = option.band) }
            viewModelScope.launch {
                _navEvents.emit(DetailNavigationEvent.OpenProviderPage(option.streamId, title))
            }
            return
        }
        PlayerSessionStore.Instance.stageFailover(option.streamId, option.backupHandles)
        stageAutoLadder(option)
        stageSyncScope(
            streamId = option.streamId,
            season = _uiState.value.ladderSeason,
            episode = _uiState.value.ladderEpisode,
            // Every rung of this scope's ladder plus each rung's runner-ups: Auto moves
            // playback onto another address without coming back through this screen, and a
            // resume point belongs to the episode, not to whichever address served it.
            backupHandles = _uiState.value.ladder.options.flatMap { listOf(it.streamId) + it.backupHandles },
        )
        _uiState.update { it.copy(selectedBand = option.band) }
        viewModelScope.launch {
            if (external && option.playUrl != null) {
                _navEvents.emit(DetailNavigationEvent.OpenExternal(option.streamId, option.playUrl))
            } else if (option.playsHere) {
                _navEvents.emit(DetailNavigationEvent.PlayStream(option.streamId, title))
            } else {
                // Not a failure and not a silent no-op: the rung can be downloaded, and
                // saying so is the honest answer to a tap on a picture we cannot stream here.
                keep(option.streamId, option.title)
            }
        }
    }

    /**
     * Hand the player the rungs Auto may move along, in the CURRENT scope only: a ladder is
     * per season/episode, and offering another episode's copies would be a lie about what
     * the viewer is watching. Bands and handles only — no addresses, nothing displayable.
     *
     * Auto is armed exactly when the tapped row IS the ladder's own auto pointer. A
     * hand-picked band is a decision, and a decision outranks any throughput estimate: the
     * director then reports the rung and never moves it.
     */
    private fun stageAutoLadder(option: QualityOption) {
        val ladder = _uiState.value.ladder
        val auto = ladder.autoBand != null && option.band == ladder.autoBand
        val rungs = ladder.options
            .filter { it.playsHere && it.streamId.isNotBlank() && it.band.isNotBlank() }
            .map { LadderRung(band = it.band, streamId = it.streamId, backupHandles = it.backupHandles, label = it.title) }
        PlayerSessionStore.Instance.stageAutoLadder(
            streamId = option.streamId,
            rungs = rungs,
            startBand = option.band,
            auto = auto,
        )
    }

    /**
     * Which work a launched rung is, in the only form the sync account accepts: the handle the
     * server minted for this post. Nothing is staged when the catalog named no handle, so a
     * deep-linked or un-named playback simply syncs nothing instead of guessing at an
     * identifier — the player reads these back from [PlayerSessionStore].
     *
     * A rung's silent runner-ups are staged under the same scope, because a CDN that refuses
     * moves playback onto one of them without anybody choosing a new work: the resume point
     * belongs to the episode, not to the address that happened to serve it.
     */
    private fun stageSyncScope(
        streamId: String,
        season: Int?,
        episode: Int?,
        backupHandles: List<String> = emptyList(),
    ): PlayerSessionStore.SyncScope? {
        val workRef = _uiState.value.post?.workRef?.takeIf { it.isNotBlank() } ?: return null
        val post = _uiState.value.post
        val scope = PlayerSessionStore.SyncScope(
            workRef = workRef,
            season = season ?: 0,
            episode = episode ?: 0,
            postId = post?.id ?: 0,
            workType = post?.contentType,
        )
        PlayerSessionStore.Instance.stageWorkRef(streamId = streamId, scope = scope)
        backupHandles.forEach { PlayerSessionStore.Instance.stageWorkRef(it, scope) }
        // D-35: stage the display metadata beside the scope, so the player can show
        // the poster behind its loading state instead of a black void. The poster is
        // the detail's own posterUrl; the cast is parsed the same way the detail
        // screen parses it (parseCastNames, cap 12).
        val meta = PlayerSessionStore.TitleMeta(
            posterUrl = post?.posterUrl,
            year = post?.year,
            castNames = parseCastNames(post?.castNames),
        )
        PlayerSessionStore.Instance.stageTitleMeta(streamId = streamId, meta = meta)
        backupHandles.forEach { PlayerSessionStore.Instance.stageTitleMeta(it, meta) }
        return scope
    }

    /** Play the best link this print offers. The server already ranked them. */
    fun playPrint(print: RankedPrint, external: Boolean = false) {
        if (!VipQualityGate.allowsResolution(print.resolution, premiumAccess)) {
            _uiState.update { it.copy(actionMessage = VipQualityGate.lockedMessage(freeQualityCap)) }
            return
        }
        val link = print.links.firstOrNull { it.playableHere } ?:
            print.links.firstOrNull { it.isProviderPage } ?:
            print.links.firstOrNull { it.keepable }
        if (link == null) {
            _uiState.update { it.copy(actionMessage = "Nothing playable on this print yet.") }
            return
        }
        // The server's own bundle first (plan §5 step 13): its winner is ranked from
        // the server's probes, and only it carries the print's coverage. Any failure
        // — a 403 while nginx still blocks the route, a timeout, a dead socket — falls
        // back to the client-side link above, so Play never gets slower or stricter
        // than it was. Two seconds is the ceiling: the server is on the same host,
        // so a healthy call answers in milliseconds.
        viewModelScope.launch {
            // Gap A2: the detail-open pre-resolve, when it is fresh and for
            // this very print — Play then starts on the bundle that is
            // already here instead of paying for the same call again.
            val cached = preresolvedResult.takeIf {
                isPreresolveFresh(preresolvedReleaseId, preresolvedAtMs, print.releaseId, System.currentTimeMillis())
            }
            if (cached != null && playV2Bundle(cached, print, external)) return@launch
            val v2 = runCatching {
                withTimeout(2_000) {
                    catalogRepository.playV2(
                        print.releaseId,
                        prefer = DataSaver.playPrefer(dataSaver, onWifi),
                    )
                }
            }.getOrNull()
            val playedV2 = v2 != null && v2.bundle.renditions.isNotEmpty() &&
                playV2Bundle(v2, print, external)
            if (!playedV2) {
                playLink(link, external, print.season, print.episodeFrom)
            }
        }
    }

    /**
     * Session 121 (P-26): play the best print of the loaded title — the hero's Watch
     * Now. The "best" is the same print the screen's own Play button offers
     * (highest `rankKey` across every print of the title), so the hero and the
     * details page never disagree about what plays. A title with no print, a
     * locked print, or a print with nothing playable degrades gracefully: the
     * viewer stays on the details page with the reason in front of them, because
     * `playPrint` says so instead of navigating anywhere.
     */
    fun playBest() {
        val best = bestPrintOf(_uiState.value.layout)
        if (best == null) {
            _uiState.update { it.copy(actionMessage = "Nothing playable on this title yet.") }
            return
        }
        playPrint(best)
    }

    /**
     * Play the server's own bundle for this print (plan §5 step 13). The winner is
     * the server's best copy — ranked from its probes, not our formula — so it is
     * the handle that plays. Its runner-ups stage as the silent failover and its
     * coverage stages as the print's chapters, both under the winner's handle, so
     * the player reads them back without the route carrying anything new.
     * Returns false when the bundle cannot be played after all, so the caller falls
     * back to the client-side link instead of leaving the viewer with nothing.
     */
    private fun playV2Bundle(result: V2PlayResult, print: RankedPrint, external: Boolean): Boolean {
        val winner = result.bundle.renditions.firstOrNull() ?: return false
        val streamId = winner.streamId?.takeIf { it.isNotBlank() } ?: return false
        val playUrl = winner.playUrl?.takeIf { it.isNotBlank() } ?: return false
        PlayerSessionStore.Instance.stageFailover(
            streamId,
            result.bundle.renditions.drop(1).mapNotNull { it.streamId },
        )
        PlayerSessionStore.Instance.stageCoverage(streamId, result.coverage)
        // Gap A3: the winner's subtitle tracks ride the handle the same way
        // its coverage does — the player stamps them onto the rendition
        // when it opens the handle. A track with no URL can never be
        // fetched, so it is dropped here rather than staged to fail on.
        PlayerSessionStore.Instance.stageTracks(
            streamId,
            winner.tracks.mapNotNull { track ->
                val url = track.url?.takeIf { it.isNotBlank() } ?: return@mapNotNull null
                SubtitleTrackInfo(
                    language = track.language,
                    kind = track.kind,
                    url = url,
                    format = track.format,
                    isDefault = track.isDefault,
                    forced = track.forced,
                )
            },
        )
        val link = RankedLink(
            streamId = streamId,
            linkId = winner.linkId?.toInt(),
            // A stream candidate is, by the server's own verdict, playable and not
            // dead — the dead ones never reach this list. Anything else would be
            // the client re-judging the server's ranking.
            health = LinkState.ACTIVE,
            ephemeral = winner.ephemeral,
            resumable = winner.resumable,
            playUrl = playUrl,
            label = winner.label,
            // kind is not served on a rendition: the playability alone decides
            // whether this is a page, and a stream candidate never is one.
            kind = null,
            playability = winner.playability,
            score = winner.linkScore,
        )
        playLink(link, external, print.season, print.episodeFrom)
        return true
    }

    /**
     * Nothing is resolved here: the server hands us an opaque handle plus OUR OWN redirector
     * for it, and the 302 happens at playback time. A link without either is not a link.
     *
     * [season] / [episode] are the scope this row belongs to, when the caller knows it. They
     * decide which resume point the player looks up, so an unknown scope is passed on as the
     * card's own rather than as a guess of 0/0.
     */
    fun playLink(link: RankedLink, external: Boolean = false, season: Int? = null, episode: Int? = null) {
        val title = _uiState.value.post?.let { it.cleanTitle ?: it.title } ?: "Stream"
        val playUrl = link.playUrl
        if (link.streamId.isBlank() || playUrl.isNullOrBlank()) {
            _uiState.update { it.copy(actionMessage = "This option is download-only.") }
            return
        }
        // Nothing plays here, so nothing is staged: no resume scope, no Continue-watching row,
        // no position lookup waiting on bytes that will never arrive. The provider's page opens
        // instead, and the viewer leaves this screen having watched nothing on our side.
        if (link.isProviderPage) {
            viewModelScope.launch {
                _navEvents.emit(DetailNavigationEvent.OpenProviderPage(link.streamId, title))
            }
            return
        }
        val scope = stageSyncScope(
            link.streamId,
            season ?: _uiState.value.ladderSeason,
            episode ?: _uiState.value.ladderEpisode,
        )
        rememberWatchStart(scope)
        viewModelScope.launch {
            if (external) _navEvents.emit(DetailNavigationEvent.OpenExternal(link.streamId, playUrl))
            else _navEvents.emit(DetailNavigationEvent.PlayStream(link.streamId, title))
        }
    }

    /**
     * Put this scope at the top of Continue watching the moment playback is launched. The row
     * carries the catalog title and art so the rail never has to guess what a handle means;
     * [PlayerViewModel] owns the position from here on. A work the server could not name has
     * no handle, so there is no row to write — the player's own in-memory resume still works.
     */
    private fun rememberWatchStart(scope: PlayerSessionStore.SyncScope?) {
        val bound = scope ?: return
        val post = _uiState.value.post ?: return
        val title = post.cleanTitle?.takeIf { it.isNotBlank() } ?: post.title
        val now = System.currentTimeMillis()
        viewModelScope.launch {
            watchHistoryDao.insertIfAbsent(
                WatchHistoryEntity(
                    workRef = bound.workRef,
                    postId = post.id,
                    title = title,
                    posterUrl = post.posterUrl?.takeIf { it.isNotBlank() },
                    seasonNumber = bound.season,
                    episodeNumber = bound.episode,
                    positionMs = 0L,
                    durationMs = 0L,
                    updatedAt = now,
                ),
            )
            // A row that already existed keeps its position but still moves to the top and
            // picks up art the detail screen may have learned since it was first written.
            watchHistoryDao.touch(
                workRef = bound.workRef,
                season = bound.season,
                episode = bound.episode,
                postId = post.id,
                title = title,
                posterUrl = post.posterUrl?.takeIf { it.isNotBlank() },
                updatedAt = now,
            )
        }
    }

    fun keepPrint(print: RankedPrint) {
        if (!VipQualityGate.allowsResolution(print.resolution, premiumAccess)) {
            _uiState.update { it.copy(actionMessage = VipQualityGate.lockedMessage(freeQualityCap)) }
            return
        }
        // Wi-Fi-only is a gate, not a suggestion: starting a hundreds-of-megabytes
        // download on mobile data by accident is the expensive mistake it exists
        // to prevent. The message says where the switch lives, so the viewer is
        // never left guessing why the tap did nothing.
        if (DataSaver.wifiOnlyBlocks(wifiOnlyDownloads, onWifi)) {
            _uiState.update {
                it.copy(actionMessage = "Wi-Fi only is on — connect to Wi-Fi to download this title. You can change it in Settings.")
            }
            return
        }
        val link = print.links.firstOrNull { !it.streamId.isBlank() && !it.isPageLink }
        if (link == null) {
            _uiState.update {
                it.copy(
                    actionMessage = if (print.links.any { row -> row.isPageLink }) PAGE_NOT_A_FILE
                    else "Nothing to download on this print yet.",
                )
            }
            return
        }
        keep(
            handle = link.streamId,
            printLabel = print.qualityLabel,
        )
    }
}

/** Which download system owns a copy. */
enum class KeepTarget { DeviceFile, EngineHls }

/**
 * Which download system owns a copy, from its resolved mime alone. A segmented
 * playlist goes to the keep engine, which fetches segments; everything else stays
 * a device file. The rule is the engine's own [KeepIdentity.linkKindFor], so the
 * detail screen and the engine can never disagree about what HLS is.
 */
internal fun keepTargetFor(mimeType: String?): KeepTarget =
    if (KeepIdentity.linkKindFor(mimeType, null) == CacheCoordinator.KIND_HLS) {
        KeepTarget.EngineHls
    } else {
        KeepTarget.DeviceFile
    }

/**
 * One scope's progress, as an episode row shows it. `fraction` is null when
 * the file never reported a duration — the row paints no bar rather than
 * inventing one. `watched` is true only when the viewer ran to the end, not
 * when they merely opened it.
 */
data class EpisodeProgress(
    val fraction: Float?,
    val watched: Boolean,
    val remainingLabel: String?,
)

/** The Resume button's target: the latest scope this device stopped in. */
data class ResumePoint(
    val season: Int,
    val episode: Int,
    val positionMs: Long,
    val durationMs: Long,
) {
    /** "Resume S1:E3 · 23 min left", or "Resume · 23 min left" for a whole work. */
    val label: String
        get() = "Resume" +
            (ContinueWatchingTile.scopeLabel(season, episode)?.let { " $it" } ?: "") +
            (ContinueWatchingTile.progressLabel(positionMs, durationMs)?.let { " · $it" } ?: "")
}

/**
 * The latest resumable row, newest first — a finished row is not a resume.
 * `rows` arrives newest first from the DAO; a caller passing them in any
 * other order gets the first resumable row of the list it gave.
 */
fun resumePointFor(rows: List<WatchHistoryEntity>): ResumePoint? {
    val row = rows.firstOrNull { it.resumable } ?: return null
    return ResumePoint(row.seasonNumber, row.episodeNumber, row.positionMs, row.durationMs)
}

/** One entry per watched scope, keyed by (season, episode). */
fun episodeProgressFor(rows: List<WatchHistoryEntity>): Map<Pair<Int, Int>, EpisodeProgress> =
    rows.associate { row ->
        val watched = row.durationMs > 0L &&
            row.positionMs >= row.durationMs - WatchHistoryEntity.END_GUARD_MS
        (row.seasonNumber to row.episodeNumber) to EpisodeProgress(
            fraction = ContinueWatchingTile.progressFraction(row.positionMs, row.durationMs),
            watched = watched,
            // A watched episode has nothing left to promise: "Less than a minute left"
            // under a full bar is a lie about a finished episode.
            remainingLabel = if (watched) null
                else ContinueWatchingTile.progressLabel(row.positionMs, row.durationMs),
        )
    }

/** The print the Resume button would play, or null when it has none. */
fun resumePrintFor(layout: ReleaseLayout, resume: ResumePoint?): RankedPrint? {
    if (resume == null) return null
    return if (resume.season > 0 && resume.episode > 0) {
        layout.seasons
            .firstOrNull { it.number == resume.season }
            ?.episodes?.firstOrNull { it.numberWithinSeason == resume.episode }
            ?.bestPrint
    } else {
        layout.workPrints.maxByOrNull { it.rankKey }
    }
}

/** "2 h 10 m", "1 h 40 m", "96 min" — null when the server sent no runtime. */
fun formatRuntimeMinutes(minutes: Int?): String? {
    if (minutes == null || minutes <= 0) return null
    return if (minutes < 60) "$minutes min"
    else {
        val hours = minutes / 60
        val rest = minutes % 60
        if (rest == 0) "$hours h" else "$hours h $rest m"
    }
}
