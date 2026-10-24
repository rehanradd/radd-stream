package com.raddstream.app.viewmodel

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.network.models.LinkClassification
import com.raddstream.app.network.models.PostDetail
import com.raddstream.app.network.models.SourceDetail
import com.raddstream.app.player.LadderRung
import com.raddstream.app.player.PlayerSessionStore
import com.raddstream.app.repository.CacheRepository
import com.raddstream.app.repository.CatalogRepository
import com.raddstream.app.repository.FavoritesRepository
import com.raddstream.app.repository.KeepOutcome
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
)

sealed class DetailNavigationEvent {
    /** Navigate by OPAQUE HANDLE only — a URL in a route would live in the back stack. */
    data class PlayStream(val streamId: String, val title: String) : DetailNavigationEvent()

    /** The one hand-off this app makes, and it carries OUR OWN address. */
    data class OpenExternal(val streamId: String, val playUrl: String) : DetailNavigationEvent()

    /** A keep the engine accepted: its row is already moving, so show the Downloads screen. */
    data class KeepRung(val label: String) : DetailNavigationEvent()
}

@HiltViewModel
class DetailViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    private val catalogRepository: CatalogRepository,
    private val favoritesRepository: FavoritesRepository,
    private val cacheRepository: CacheRepository,
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
                    val layout = ReleaseParser.build(detail.contentType, detail.releases)
                    _uiState.update {
                        it.copy(
                            post = detail,
                            layout = layout,
                            ladder = QualityLadder.forNumberedScope(detail.optionGroups, null, null),
                            selectedSeason = layout.seasons.firstOrNull()?.number,
                            isLoading = false,
                        )
                    }
                } else {
                    _uiState.update {
                        it.copy(isLoading = false, error = "This title is not available on the connected server.")
                    }
                }
            } catch (ex: Exception) {
                _uiState.update {
                    it.copy(isLoading = false, error = ex.message ?: "Failed to load details. Check connection.")
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
        QualityLadder.forNumberedScope(
            _uiState.value.post?.optionGroups.orEmpty(),
            season,
            episode,
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
                ladder = QualityLadder.forNumberedScope(
                    _uiState.value.post?.optionGroups.orEmpty(),
                    season,
                    episode,
                ),
                ladderSeason = season,
                ladderEpisode = episode,
                selectedBand = LadderForScope.AUTO,
            )
        }
    }

    /** A rung this app cannot present is kept, and the row says so — no hidden failure. */
    fun keepRung(option: QualityOption) {
        _uiState.update { it.copy(selectedBand = option.band) }
        keep(
            handle = option.streamId,
            sizeBytes = option.sizeBytes,
            resumable = option.resumable,
            printLabel = option.title,
        )
    }

    /**
     * Ask the cache engine for one copy, by OUR opaque handle.
     *
     * Every branch answers out loud: a keep that started routes to the Downloads screen where
     * its row is already moving, and a refusal stays here with the real numbers, because a
     * download button that quietly does nothing is worse than one that says no.
     */
    private fun keep(handle: String, sizeBytes: Long?, resumable: Boolean, printLabel: String) {
        if (handle.isBlank()) {
            _uiState.update { it.copy(actionMessage = "Nothing to keep on this rung yet.") }
            return
        }
        val workTitle = _uiState.value.post?.let { it.cleanTitle ?: it.title } ?: "Stream"
        viewModelScope.launch {
            when (val outcome =
                cacheRepository.keep(handle, workTitle, sizeBytes, resumable, printLabel)) {
                is KeepOutcome.Enqueued, is KeepOutcome.AlreadyKept ->
                    _navEvents.emit(DetailNavigationEvent.KeepRung(printLabel))
                is KeepOutcome.NoSpace -> _uiState.update {
                    it.copy(
                        actionMessage = "Not enough room: needs " +
                            QualityOption.formatBytes(outcome.requiredBytes) +
                            ", " + QualityOption.formatBytes(outcome.availableBytes) + " free."
                    )
                }
                KeepOutcome.Unavailable -> _uiState.update {
                    it.copy(actionMessage = "This copy can't be kept yet.")
                }
            }
        }
    }

    /**
     * Play one rung of the ladder. The rung's runner-ups and the ladder itself are staged
     * for the player first, so a CDN that refuses mid-play costs a silent hop instead of a
     * dialog, and a viewer who chose Auto can be moved along these same rungs by the
     * measured throughput — while the navigation route still carries one opaque handle only.
     */
    fun playLadder(option: QualityOption, external: Boolean = false) {
        val title = _uiState.value.post?.let { it.cleanTitle ?: it.title } ?: "Stream"
        if (option.streamId.isBlank()) {
            _uiState.update { it.copy(actionMessage = "Nothing playable on this rung yet.") }
            return
        }
        PlayerSessionStore.Instance.stageFailover(option.streamId, option.backupHandles)
        stageAutoLadder(option)
        _uiState.update { it.copy(selectedBand = option.band) }
        viewModelScope.launch {
            if (external && option.playUrl != null) {
                _navEvents.emit(DetailNavigationEvent.OpenExternal(option.streamId, option.playUrl))
            } else if (option.playsHere) {
                _navEvents.emit(DetailNavigationEvent.PlayStream(option.streamId, title))
            } else {
                // Not a failure and not a silent no-op: the rung is keepable, and saying
                // so is the honest answer to a tap on a picture we cannot stream here.
                _navEvents.emit(DetailNavigationEvent.KeepRung(option.title))
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
            .map { LadderRung(band = it.band, streamId = it.streamId, backupHandles = it.backupHandles) }
        PlayerSessionStore.Instance.stageAutoLadder(
            streamId = option.streamId,
            rungs = rungs,
            startBand = option.band,
            auto = auto,
        )
    }

    /** Play the best link this print offers. The server already ranked them. */
    fun playPrint(print: RankedPrint, external: Boolean = false) {
        val link = print.links.firstOrNull { it.playableHere } ?: print.links.firstOrNull { it.keepable }
        if (link == null) {
            _uiState.update { it.copy(actionMessage = "Nothing playable on this print yet.") }
            return
        }
        playLink(link, external)
    }

    /**
     * Nothing is resolved here: the server hands us an opaque handle plus OUR OWN redirector
     * for it, and the 302 happens at playback time. A link without either is not a link.
     */
    fun playLink(link: RankedLink, external: Boolean = false) {
        val title = _uiState.value.post?.let { it.cleanTitle ?: it.title } ?: "Stream"
        val playUrl = link.playUrl
        if (link.streamId.isBlank() || playUrl.isNullOrBlank()) {
            _uiState.update { it.copy(actionMessage = "This option is download-only.") }
            return
        }
        viewModelScope.launch {
            if (external) _navEvents.emit(DetailNavigationEvent.OpenExternal(link.streamId, playUrl))
            else _navEvents.emit(DetailNavigationEvent.PlayStream(link.streamId, title))
        }
    }

    /** Entry point for a bare link model handed over from another screen. */
    fun playSource(source: SourceDetail, external: Boolean = false) {
        playLink(linkFrom(source), external)
    }

    fun keepPrint(print: RankedPrint) {
        val link = print.links.firstOrNull { !it.streamId.isBlank() }
        keep(
            handle = link?.streamId.orEmpty(),
            sizeBytes = print.sizeBytes,
            resumable = link?.resumable ?: false,
            printLabel = print.qualityLabel,
        )
    }

    private fun linkFrom(source: SourceDetail): RankedLink = RankedLink(
        streamId = source.streamId.orEmpty(),
        linkId = source.linkId,
        health = LinkHealth.ACTIVE,
        ephemeral = source.isEphemeral,
        resumable = source.isResumableLink,
        playUrl = source.bestUrl,
        label = source.label,
        kind = source.kind,
        playability = source.classification.playability,
        score = LinkClassification.rankOf(source),
    )
}
