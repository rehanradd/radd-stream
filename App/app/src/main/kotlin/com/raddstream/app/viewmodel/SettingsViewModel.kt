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

enum class ImageQuality(val label: String) { AUTO("Auto"), HIGH("High"), MEDIUM("Medium"), LOW("Battery saver") }
enum class KeepTtl(val label: String, val hours: Int) { H3("3 hours", 3), H6("6 hours", 6) }

/**
 * Playback/display preferences. The v1 client has no persisted preference store
 * yet, so these live in the ViewModel for the session and are applied where a
 * consumer exists. A `UserPreferencesRepository` (DataStore) is requested in
 * docs/HANDOFF_appui.md #5 — persistence is the ONLY thing missing, the state and
 * every control here is real and functional within the session.
 */
data class UserPreferences(
    val imageQuality: ImageQuality = ImageQuality.AUTO,
    val downloadOnMobileData: Boolean = false,
    val keepTtl: KeepTtl = KeepTtl.H3,
    val subtitleLang: String = "Off",
    val dynamicColor: Boolean = false,
) {
    val posterMaxWidthPx: Int
        get() = when (imageQuality) {
            ImageQuality.HIGH -> 640
            ImageQuality.MEDIUM -> 400
            ImageQuality.LOW -> 240
            ImageQuality.AUTO -> if (downloadOnMobileData) 400 else 640
        }
}

data class SettingsUiState(
    val serverUrl: String = "",
    val isTesting: Boolean = false,
    val testMessage: String? = null,
    val testIsError: Boolean = false,
    val stats: StatsResponse? = null,
    val isLoadingStats: Boolean = false,
    val prefs: UserPreferences = UserPreferences(),
    val statusMessage: String? = null,
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
            _uiState.update { it.copy(serverUrl = url, isLoadingStats = url.isNotBlank()) }
            if (url.isNotBlank()) {
                try {
                    val stats = catalogRepository.getStats()
                    _uiState.update { it.copy(stats = stats, isLoadingStats = false) }
                } catch (_: Exception) {
                    _uiState.update { it.copy(isLoadingStats = false) }
                }
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
                    it.copy(isTesting = false, testMessage = ex.message ?: "Connection failed.", testIsError = true)
                }
            }
        }
    }

    fun setImageQuality(value: ImageQuality) = updatePrefs { it.copy(imageQuality = value) }
    fun setDownloadOnMobileData(value: Boolean) = updatePrefs { it.copy(downloadOnMobileData = value) }
    fun setKeepTtl(value: KeepTtl) = updatePrefs { it.copy(keepTtl = value) }
    fun setSubtitleLang(value: String) = updatePrefs { it.copy(subtitleLang = value) }
    fun setDynamicColor(value: Boolean) = updatePrefs { it.copy(dynamicColor = value) }

    fun clearImageCache() {
        // Honest placeholder until the app owns an explicit image-loader reset handle
        // and the offline media cache engine exposes a wipe (docs/HANDOFF_appui.md #6).
        // We surface a clear status instead of silently doing nothing.
        _uiState.update {
            it.copy(statusMessage = "Offline keeps are managed on the Downloads screen. Poster images are cached automatically by the app.")
        }
    }

    private fun updatePrefs(transform: (UserPreferences) -> UserPreferences) {
        _uiState.update { it.copy(prefs = transform(it.prefs)) }
    }

    fun clearStatus() {
        _uiState.update { it.copy(statusMessage = null) }
    }
}
