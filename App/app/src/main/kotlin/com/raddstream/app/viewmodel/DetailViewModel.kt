package com.raddstream.app.viewmodel

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.data.UserRegion
import com.raddstream.app.data.downloads.DeviceDownloadResult
import com.raddstream.app.data.downloads.DeviceDownloadsRepository
import com.raddstream.app.data.local.WatchHistoryDao
import com.raddstream.app.data.local.WatchHistoryEntity
import com.raddstream.app.network.friendlyNetworkError
import com.raddstream.app.network.models.LinkClassification
import com.raddstream.app.network.models.LinkState
import com.raddstream.app.network.models.PostDetail
import com.raddstream.app.network.models.SourceDetail
import com.raddstream.app.player.LadderForScope
import com.raddstream.app.player.LadderRung
import com.raddstream.app.player.PlayerSessionStore
import com.raddstream.app.player.QualityLadder
import com.raddstream.app.player.QualityOption
import com.raddstream.app.repository.CatalogRepository
import com.raddstream.app.repository.FavoritesRepository
import com.raddstream.app.sync.SyncAccountRepository
import com.raddstream.app.ui.navigation.Screen
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

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
)

sealed class DetailNavigationEvent {
    /** Navigate by OPAQUE HANDLE only — a URL in a route would live in the back stack. */
    data class PlayStream(val streamId: String, val title: String) : DetailNavigationEvent()

    /** The one hand-off this app makes, and it carries OUR OWN address. */
    data class OpenExternal(val streamId: String, val playUrl: String) : DetailNavigationEvent()

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
    private val syncAccountRepository: SyncAccountRepository,
    private val settingsRepository: ServerSettingsRepository,
    private val watchHistoryDao: WatchHistoryDao,
) : ViewModel() {

    private val postId: Int = (savedStateHandle[Screen.Detail.ARG_POST_ID] as? String)?.toIntOrNull()
        ?: (savedStateHandle[Screen.Detail.ARG_POST_ID] as? Int)
        ?: -1

    private val _uiState = MutableStateFlow(DetailUiState())
    val uiState = _uiState.asStateFlow()

    private val _navEvents = MutableSharedFlow<DetailNavigationEvent>()
    val navEvents: SharedFlow<DetailNavigationEvent> = _navEvents.asSharedFlow()

    init {
        loadDetail()
        observeFavorite()
        observeEntitlement()
    }

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
            settingsRepository.userRegion.collect { region ->
                userRegion = region
                publishViewerContent()
            }
        }
    }

    private var serverVip: Boolean = false
    private var rewardedExpiresAt: Long = 0L

    /**
     * The operator's switch, not this screen's opinion. Off is the shipped default, so the
     * catalog stays whole for a free viewer until the owner decides 1080p/4K should cost
     * something; [premiumAccess] is what every gate call below actually passes.
     */
    private var qualityGateEnabled: Boolean = false

    /**
     * The viewer's regional-dub preference; [UserRegion.DEFAULT] until DataStore answers,
     * which already is the shipped default. It only reorders the release selector.
     */
    private var userRegion: String = UserRegion.DEFAULT

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
            VipQualityGate.hasPremiumPrints(full) ||
                scope.options.any { VipQualityGate.isPremiumBand(it.band) || VipQualityGate.isPremiumLabel(it.title) }
            )
        _uiState.update {
            it.copy(
                layout = VipQualityGate.gate(full, premiumAccess),
                ladder = VipQualityGate.gate(scope, premiumAccess),
                vip = serverVip,
                premiumSourcesLocked = premiumLocked,
                adFree = RewardedVipPass.isAdFree(serverVip, rewardedExpiresAt),
            )
        }
    }

    private fun observeFavorite() {
        if (postId < 0) return
        viewModelScope.launch {
            favoritesRepository.isFavorite(postId).collect { fav ->
                _uiState.update { it.copy(isFavorite = fav) }
            }
        }
    }

    fun loadDetail() {
        if (postId < 0) {
            _uiState.update { it.copy(isLoading = false, error = "This title could not be opened.") }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            try {
                val detail = catalogRepository.getPostDetail(postId)
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
                    // A row saved before this app had a handle becomes syncable the moment the
                    // catalog finally names its work. Nothing here fabricates a handle: an absent
                    // key is a no-op, and a present one is the server's own.
                    syncAccountRepository.adoptWorkRef(postId, detail.workRef)
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
            _uiState.update { it.copy(actionMessage = VipQualityGate.LOCKED_MESSAGE) }
            return
        }
        _uiState.update { it.copy(selectedBand = option.band) }
        keep(
            handle = option.streamId,
            printLabel = option.title,
        )
    }

    /** A premium rung the current viewer may not take, decided from the same gate the UI uses. */
    private fun isLocked(option: QualityOption): Boolean =
        !VipQualityGate.allowsBand(option.band, premiumAccess) ||
            (!premiumAccess && VipQualityGate.isPremiumLabel(option.title))

    /**
     * Ask Android's DownloadManager for one public file, by OUR opaque handle.
     *
     * Every branch answers out loud: an accepted download routes to the Downloads screen where
     * its row is already moving; a legacy device learns it must grant storage first, because a
     * button that quietly does nothing is worse than one that says no. The address handed to
     * DownloadManager is our own redirector — the server verified the handle, and the upstream
     * location never enters this app.
     */
    private fun keep(handle: String, printLabel: String) {
        lastDownload = handle to printLabel
        if (handle.isBlank()) {
            _uiState.update { it.copy(actionMessage = "Nothing to download on this rung yet.") }
            return
        }
        val workTitle = _uiState.value.post?.let { it.cleanTitle ?: it.title } ?: "Stream"
        viewModelScope.launch {
            when (val outcome = deviceDownloads.enqueue(handle, workTitle, printLabel)) {
                is DeviceDownloadResult.Enqueued -> {
                    lastDownload = null
                    _navEvents.emit(DetailNavigationEvent.DownloadStarted(printLabel))
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

    /** Re-run the request that stopped for a storage grant, once the viewer allows it. */
    fun retryLastDownload() {
        lastDownload?.let { (handle, label) -> keep(handle, label) }
    }

    private var lastDownload: Pair<String, String>? = null

    /**
     * Play one rung of the ladder. The rung's runner-ups and the ladder itself are staged
     * for the player first, so a CDN that refuses mid-play costs a silent hop instead of a
     * dialog, and a viewer who chose Auto can be moved along these same rungs by the
     * measured throughput — while the navigation route still carries one opaque handle only.
     */
    fun playLadder(option: QualityOption, external: Boolean = false) {
        if (isLocked(option)) {
            _uiState.update { it.copy(actionMessage = VipQualityGate.LOCKED_MESSAGE) }
            return
        }
        val title = _uiState.value.post?.let { it.cleanTitle ?: it.title } ?: "Stream"
        if (option.streamId.isBlank()) {
            _uiState.update { it.copy(actionMessage = "Nothing playable on this rung yet.") }
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
        return scope
    }

    /** Play the best link this print offers. The server already ranked them. */
    fun playPrint(print: RankedPrint, external: Boolean = false) {
        if (!VipQualityGate.allowsResolution(print.resolution, premiumAccess)) {
            _uiState.update { it.copy(actionMessage = VipQualityGate.LOCKED_MESSAGE) }
            return
        }
        val link = print.links.firstOrNull { it.playableHere } ?: print.links.firstOrNull { it.keepable }
        if (link == null) {
            _uiState.update { it.copy(actionMessage = "Nothing playable on this print yet.") }
            return
        }
        playLink(link, external, print.season, print.episodeFrom)
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

    /** Entry point for a bare link model handed over from another screen. */
    fun playSource(source: SourceDetail, external: Boolean = false) {
        playLink(linkFrom(source), external)
    }

    fun keepPrint(print: RankedPrint) {
        if (!VipQualityGate.allowsResolution(print.resolution, premiumAccess)) {
            _uiState.update { it.copy(actionMessage = VipQualityGate.LOCKED_MESSAGE) }
            return
        }
        val link = print.links.firstOrNull { !it.streamId.isBlank() }
        keep(
            handle = link?.streamId.orEmpty(),
            printLabel = print.qualityLabel,
        )
    }

    private fun linkFrom(source: SourceDetail): RankedLink = RankedLink(
        streamId = source.streamId.orEmpty(),
        linkId = source.linkId,
        health = LinkState.ACTIVE,
        ephemeral = source.isEphemeral,
        resumable = source.isResumableLink,
        playUrl = source.bestUrl,
        label = source.label,
        kind = source.kind,
        playability = source.classification.playability,
        score = LinkClassification.rankOf(source),
    )
}
