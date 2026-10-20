package com.raddstream.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.network.models.StatsResponse
import com.raddstream.app.repository.CatalogRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class SettingsUiState(
    val serverUrl: String = "",
    val isTesting: Boolean = false,
    val testMessage: String? = null,
    val testIsError: Boolean = false,
    val stats: StatsResponse? = null,
    val isLoadingStats: Boolean = false,
)

@HiltViewModel
class SettingsViewModel @Inject constructor(
    private val settingsRepository: ServerSettingsRepository,
    private val catalogRepository: CatalogRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(SettingsUiState())
    val uiState = _uiState.asStateFlow()

    init {
        loadServerUrlAndStats()
    }

    private fun loadServerUrlAndStats() {
        viewModelScope.launch {
            val url = settingsRepository.serverUrl.first() ?: ""
            _uiState.update { it.copy(serverUrl = url, isLoadingStats = true) }
            if (url.isNotBlank()) {
                try {
                    val stats = catalogRepository.getStats()
                    _uiState.update { it.copy(stats = stats, isLoadingStats = false) }
                } catch (_: Exception) {
                    _uiState.update { it.copy(isLoadingStats = false) }
                }
            } else {
                _uiState.update { it.copy(isLoadingStats = false) }
            }
        }
    }

    fun onServerUrlChanged(newUrl: String) {
        _uiState.update { it.copy(serverUrl = newUrl, testMessage = null) }
    }

    fun testAndSaveServer() {
        val url = _uiState.value.serverUrl.trim()
        if (url.isBlank()) return

        viewModelScope.launch {
            _uiState.update { it.copy(isTesting = true, testMessage = null) }
            try {
                val stats = catalogRepository.testAndSaveServer(url)
                _uiState.update {
                    it.copy(
                        isTesting = false,
                        testMessage = "Connected successfully. Found ${stats.posts} titles.",
                        testIsError = false,
                        stats = stats,
                    )
                }
            } catch (ex: Exception) {
                _uiState.update {
                    it.copy(
                        isTesting = false,
                        testMessage = ex.message ?: "Connection failed.",
                        testIsError = true,
                    )
                }
            }
        }
    }
}
