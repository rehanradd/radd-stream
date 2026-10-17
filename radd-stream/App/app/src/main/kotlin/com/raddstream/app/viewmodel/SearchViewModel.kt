package com.raddstream.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.network.models.Post
import com.raddstream.app.repository.CatalogRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class SearchUiState(
    val query: String = "",
    val selectedType: String? = null,
    val posts: List<Post> = emptyList(),
    val isLoading: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class SearchViewModel @Inject constructor(
    private val catalogRepository: CatalogRepository,
) : ViewModel() {
    private val _uiState = MutableStateFlow(SearchUiState())
    val uiState = _uiState.asStateFlow()
    private var searchJob: Job? = null

    fun onQueryChanged(query: String) {
        _uiState.update { it.copy(query = query, posts = emptyList(), error = null) }
        scheduleSearch()
    }

    fun selectType(type: String?) {
        if (_uiState.value.selectedType == type) return
        _uiState.update { it.copy(selectedType = type, posts = emptyList(), error = null) }
        scheduleSearch()
    }

    private fun scheduleSearch() {
        searchJob?.cancel()
        val query = _uiState.value.query.trim()
        val type = _uiState.value.selectedType
        if (query.isBlank()) {
            _uiState.update { it.copy(posts = emptyList(), isLoading = false, error = null) }
            return
        }

        searchJob = viewModelScope.launch {
            delay(300)
            _uiState.update { it.copy(isLoading = true, error = null) }
            try {
                val posts = catalogRepository.getPosts(
                    query = query,
                    type = type,
                    page = 1,
                    limit = 50,
                ).results
                _uiState.update { it.copy(posts = posts, isLoading = false) }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        error = error.message ?: "Search failed. Check the server connection.",
                    )
                }
            }
        }
    }
}
