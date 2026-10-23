package com.raddstream.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.repository.CatalogRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class SetupUiState(
    val serverUrl: String = "",
    val isChecking: Boolean = false,
    val isConnected: Boolean = false,
    val message: String? = null,
    val messageIsError: Boolean = false,
)

@HiltViewModel
class SetupViewModel @Inject constructor(
    private val catalogRepository: CatalogRepository,
) : ViewModel() {
    private val _uiState = MutableStateFlow(SetupUiState())
    val uiState = _uiState.asStateFlow()

    fun onServerUrlChanged(value: String) {
        _uiState.update {
            it.copy(
                serverUrl = value,
                isConnected = false,
                message = null,
                messageIsError = false,
            )
        }
    }

    fun testConnection() {
        if (_uiState.value.isChecking) return
        viewModelScope.launch {
            val submittedUrl = _uiState.value.serverUrl
            _uiState.update { it.copy(isChecking = true, message = null, isConnected = false) }
            try {
                val stats = catalogRepository.testAndSaveServer(submittedUrl)
                _uiState.update {
                    it.copy(
                        serverUrl = com.raddstream.app.network.normalizeServerUrl(submittedUrl),
                        isChecking = false,
                        isConnected = true,
                        message = "Connected. ${stats.posts} catalog titles available.",
                        messageIsError = false,
                    )
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                _uiState.update {
                    it.copy(
                        isChecking = false,
                        isConnected = false,
                        message = error.message ?: "Could not connect to that server.",
                        messageIsError = true,
                    )
                }
            }
        }
    }
}
