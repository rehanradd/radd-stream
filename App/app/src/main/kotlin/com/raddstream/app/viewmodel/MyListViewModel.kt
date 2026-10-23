package com.raddstream.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.data.local.FavoritePost
import com.raddstream.app.network.models.Post
import com.raddstream.app.repository.FavoritesRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

enum class ListSort(val label: String) { RECENT("Recently added"), TITLE("Title A–Z") }

data class MyListUiState(
    val favorites: List<Post> = emptyList(),
    val sort: ListSort = ListSort.RECENT,
    val isLoading: Boolean = false,
)

@HiltViewModel
class MyListViewModel @Inject constructor(
    private val favoritesRepository: FavoritesRepository,
) : ViewModel() {

    private val sortFlow = MutableStateFlow(ListSort.RECENT)

    val uiState: StateFlow<MyListUiState> = combine(
        favoritesRepository.getAllFavorites(),
        sortFlow,
    ) { list, sort ->
        val sorted: List<FavoritePost> = when (sort) {
            ListSort.RECENT -> list.sortedByDescending { it.addedAt }
            ListSort.TITLE -> list.sortedBy { (it.cleanTitle ?: it.title).lowercase() }
        }
        MyListUiState(favorites = sorted.map(FavoritePost::toPost), sort = sort, isLoading = false)
    }.stateIn(
        scope = viewModelScope,
        started = SharingStarted.WhileSubscribed(5_000),
        initialValue = MyListUiState(isLoading = true),
    )

    fun setSort(sort: ListSort) {
        sortFlow.value = sort
    }

    fun removeFavorite(postId: Int) {
        viewModelScope.launch { favoritesRepository.removeFavorite(postId) }
    }
}
