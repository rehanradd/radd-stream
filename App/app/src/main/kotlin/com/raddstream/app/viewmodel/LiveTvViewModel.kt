package com.raddstream.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.network.friendlyNetworkError
import com.raddstream.app.network.models.LiveTvChannel
import com.raddstream.app.repository.CatalogRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * The Live TV tab's state: one server fetch, then client-side filtering.
 *
 * The served list is small (17 channels at v1), so the category chips and
 * the name search filter the rows already on the device instead of a
 * network round-trip per tap. The endpoint's own `?category=` filter stays
 * available for a day the list grows large enough to page.
 *
 * A channel is played by its signed `stream_id` handle through the existing
 * player — this ViewModel never holds, shows or routes an upstream URL.
 */
@HiltViewModel
class LiveTvViewModel @Inject constructor(
    private val repository: CatalogRepository,
) : ViewModel() {

    data class UiState(
        val isLoading: Boolean = true,
        val channels: List<LiveTvChannel> = emptyList(),
        val categories: List<String> = emptyList(),
        val selectedCategory: String? = null,
        val query: String = "",
        val error: String? = null,
    ) {
        /** What the grid shows: the chosen category, then the name search. */
        val visibleChannels: List<LiveTvChannel>
            get() {
                val byCategory = if (selectedCategory == null) {
                    channels
                } else {
                    channels.filter { it.category == selectedCategory }
                }
                val needle = query.trim().lowercase()
                return if (needle.isEmpty()) {
                    byCategory
                } else {
                    byCategory.filter { it.name.lowercase().contains(needle) }
                }
            }
    }

    private val _uiState = MutableStateFlow(UiState())
    val uiState = _uiState.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            try {
                val response = repository.getLiveTvChannels()
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        channels = response.channels,
                        categories = response.categories,
                        error = null,
                    )
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        error = friendlyNetworkError(
                            error, "Could not load live channels.",
                        ),
                    )
                }
            }
        }
    }

    fun onCategorySelected(category: String?) {
        _uiState.update { it.copy(selectedCategory = category) }
    }

    fun onQueryChanged(query: String) {
        _uiState.update { it.copy(query = query) }
    }
}
