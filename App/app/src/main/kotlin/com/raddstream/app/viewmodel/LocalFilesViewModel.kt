package com.raddstream.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.data.local.LocalFilesRepository
import com.raddstream.app.data.local.LocalVideoFile
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class LocalFilesUiState(
    val isLoading: Boolean = true,
    val needsPermission: Boolean = false,
    val files: List<LocalVideoFile> = emptyList(),
    val loadFailed: Boolean = false,
)

/**
 * The phone's own videos, as the Media Vault's "on this phone" list. The
 * screen owns the permission question — this class only answers it: granted
 * loads the list, denied shows the honest state with a way back to settings.
 * A revoked permission mid-read answers as an empty list from the
 * repository, never as a crash.
 */
@HiltViewModel
class LocalFilesViewModel @Inject constructor(
    private val repository: LocalFilesRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(LocalFilesUiState())
    val uiState: StateFlow<LocalFilesUiState> = _uiState.asStateFlow()

    fun onPermissionResult(granted: Boolean) {
        if (granted) load() else {
            _uiState.value = LocalFilesUiState(isLoading = false, needsPermission = true)
        }
    }

    fun load() {
        viewModelScope.launch {
            _uiState.value = LocalFilesUiState(isLoading = true)
            runCatching { repository.loadVideos() }
                .onSuccess { files ->
                    _uiState.value = LocalFilesUiState(isLoading = false, files = files)
                }
                .onFailure {
                    _uiState.value = LocalFilesUiState(isLoading = false, loadFailed = true)
                }
        }
    }

    fun refresh() = load()
}
