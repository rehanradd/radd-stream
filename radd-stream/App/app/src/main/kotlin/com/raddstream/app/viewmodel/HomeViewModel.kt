package com.raddstream.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.network.models.Post
import com.raddstream.app.repository.CatalogRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class HomeUiState(
    val posts: List<Post> = emptyList(),
    val selectedType: String? = null,
    val isLoading: Boolean = true,
    val error: String? = null,
)

@HiltViewModel
class HomeViewModel @Inject constructor(
    private val catalogRepository: CatalogRepository,
) : ViewModel() {
    private val _uiState = MutableStateFlow(HomeUiState())
    val uiState = _uiState.asStateFlow()
    private var loadJob: Job? = null

    init {
        loadPosts()
    }

    fun selectType(type: String?) {
        if (_uiState.value.selectedType == type) return
        _uiState.update { it.copy(selectedType = type, posts = emptyList()) }
        loadPosts()
    }

    fun refresh() = loadPosts()

    private fun loadPosts() {
        loadJob?.cancel()
        val type = _uiState.value.selectedType
        loadJob = viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            try {
                val posts = catalogRepository.getPosts(type = type, page = 1, limit = 30).results
                _uiState.update { it.copy(posts = posts, isLoading = false) }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        error = error.message ?: "Could not load the catalog.",
                    )
                }
            }
        }
    }
}
