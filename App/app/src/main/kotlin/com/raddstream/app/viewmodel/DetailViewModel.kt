package com.raddstream.app.viewmodel

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.network.models.LinkClassification
import com.raddstream.app.network.models.PostDetail
import com.raddstream.app.network.models.SourceDetail
import com.raddstream.app.repository.CatalogRepository
import com.raddstream.app.repository.FavoritesRepository
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
)

sealed class DetailNavigationEvent {
    /** Navigate by OPAQUE HANDLE only — a URL in a route would live in the back stack. */
    data class PlayStream(val streamId: String, val title: String) : DetailNavigationEvent()

    /** The one hand-off this app makes, and it carries OUR OWN address. */
    data class OpenExternal(val streamId: String, val playUrl: String) : DetailNavigationEvent()

    /** Request to persist a print for offline playback. Wired to the cache engine
     *  (docs/CACHE_SPEC.md) once it exists — see HANDOFF request #6. For now the
     *  screen routes this to the Downloads screen which states the honest status. */
    data class KeepPrint(val releaseId: Int, val label: String) : DetailNavigationEvent()
}

@HiltViewModel
class DetailViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    private val catalogRepository: CatalogRepository,
    private val favoritesRepository: FavoritesRepository,
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
        viewModelScope.launch {
            _navEvents.emit(DetailNavigationEvent.KeepPrint(print.releaseId, print.qualityLabel))
        }
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
