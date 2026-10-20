package com.raddstream.app.viewmodel

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
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
    val isLoading: Boolean = true,
    val isFavorite: Boolean = false,
    val resolvingSourceId: Int? = null,
    val error: String? = null,
    val actionMessage: String? = null,
)

sealed class DetailNavigationEvent {
    data class PlayStream(val streamUrl: String, val title: String) : DetailNavigationEvent()
    data class OpenExternal(val streamUrl: String) : DetailNavigationEvent()
}

@HiltViewModel
class DetailViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    private val catalogRepository: CatalogRepository,
    private val favoritesRepository: FavoritesRepository,
) : ViewModel() {

    private val postId: Int = checkNotNull(savedStateHandle[Screen.Detail.ARG_POST_ID]) {
        "postId navigation argument is required"
    }.toString().toInt()

    private val _uiState = MutableStateFlow(DetailUiState())
    val uiState = _uiState.asStateFlow()

    private val _navEvents = MutableSharedFlow<DetailNavigationEvent>()
    val navEvents: SharedFlow<DetailNavigationEvent> = _navEvents.asSharedFlow()

    init {
        loadDetail()
        observeFavorite()
    }

    private fun observeFavorite() {
        viewModelScope.launch {
            favoritesRepository.isFavorite(postId).collect { fav ->
                _uiState.update { it.copy(isFavorite = fav) }
            }
        }
    }

    fun loadDetail() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            try {
                val detail = catalogRepository.getPostDetail(postId)
                if (detail != null) {
                    _uiState.update { it.copy(post = detail, isLoading = false) }
                } else {
                    _uiState.update {
                        it.copy(
                            isLoading = false,
                            error = "Could not load title details from the server.",
                        )
                    }
                }
            } catch (ex: Exception) {
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        error = ex.message ?: "Failed to load details. Check connection.",
                    )
                }
            }
        }
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

    fun playSource(source: SourceDetail, isExternal: Boolean = false) {
        val currentPost = _uiState.value.post
        val title = currentPost?.cleanTitle ?: currentPost?.title ?: "Stream"

        // If source already has a direct final URL
        val directUrl = source.finalUrl?.takeIf { it.startsWith("http") }

        if (directUrl != null) {
            viewModelScope.launch {
                if (isExternal) {
                    _navEvents.emit(DetailNavigationEvent.OpenExternal(directUrl))
                } else {
                    _navEvents.emit(DetailNavigationEvent.PlayStream(directUrl, title))
                }
            }
            return
        }

        // Otherwise resolve live source URL via API
        viewModelScope.launch {
            _uiState.update { it.copy(resolvingSourceId = source.id) }
            try {
                val res = catalogRepository.resolveStream(source.id)
                val streamUrl = res.url
                _uiState.update { it.copy(resolvingSourceId = null) }

                if (res.success && !streamUrl.isNullOrBlank()) {
                    if (isExternal) {
                        _navEvents.emit(DetailNavigationEvent.OpenExternal(streamUrl))
                    } else {
                        _navEvents.emit(DetailNavigationEvent.PlayStream(streamUrl, title))
                    }
                } else {
                    _uiState.update {
                        it.copy(actionMessage = res.error ?: "Source link could not be resolved.")
                    }
                }
            } catch (ex: Exception) {
                _uiState.update {
                    it.copy(
                        resolvingSourceId = null,
                        actionMessage = ex.message ?: "Error resolving source.",
                    )
                }
            }
        }
    }
}
