package com.raddstream.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.data.local.FavoritePost
import com.raddstream.app.network.models.Post
import com.raddstream.app.repository.FavoritesRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

data class MyListUiState(
    val favorites: List<Post> = emptyList(),
    val isLoading: Boolean = false,
)

@HiltViewModel
class MyListViewModel @Inject constructor(
    private val favoritesRepository: FavoritesRepository,
) : ViewModel() {

    val uiState: StateFlow<MyListUiState> = favoritesRepository.getAllFavorites()
        .map { list ->
            MyListUiState(
                favorites = list.map(FavoritePost::toPost),
                isLoading = false,
            )
        }
        .stateIn(
            scope = viewModelScope,
            started = SharingStarted.WhileSubscribed(5000),
            initialValue = MyListUiState(isLoading = true),
        )

    fun removeFavorite(postId: Int) {
        viewModelScope.launch {
            favoritesRepository.removeFavorite(postId)
        }
    }
}
