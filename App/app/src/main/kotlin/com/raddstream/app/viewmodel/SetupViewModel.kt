package com.raddstream.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.brand.Brand
import com.raddstream.app.network.friendlyNetworkError
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
    // Prefilled with the address the brand file ships, so reaching this screen is a
    // one-tap "Connect" instead of typing an IP — and so a self-hoster who lands here
    // can see the default they are about to replace.
    private val _uiState = MutableStateFlow(SetupUiState(serverUrl = Brand.defaultServerUrl))
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
                        message = CatalogScale.connectionNotice(stats.posts),
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
                        message = friendlyNetworkError(error, "Could not connect to that server."),
                        messageIsError = true,
                    )
                }
            }
        }
    }
}
