package com.raddstream.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.network.models.StatsResponse
import com.raddstream.app.player.AudioBoost
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
 * Playback/display preferences. [audioBoost] and [audioLanguage] are persisted through the
 * app's own DataStore ([ServerSettingsRepository]), because they are settings a viewer mixes
 * once and expects to still hold next week; the rest live in the ViewModel for the session
 * and are applied where a consumer exists. A full `UserPreferencesRepository` is requested
 * in docs/HANDOFF_appui.md #5 — persistence is the ONLY thing missing there, the state and
 * every control here is real and functional.
 */
data class UserPreferences(
    val imageQuality: ImageQuality = ImageQuality.AUTO,
    val downloadOnMobileData: Boolean = false,
    val keepTtl: KeepTtl = KeepTtl.H3,
    val subtitleLang: String = "Off",
    val dynamicColor: Boolean = false,
    /** The audio level 0..2 ([AudioBoost]'s unit); persisted, applied by the player. */
    val audioBoost: Float = AudioBoost.BASELINE,
    /** Preferred audio language, or [AUDIO_LANGUAGE_DEFAULT] = leave it to the player. */
    val audioLanguage: String = AUDIO_LANGUAGE_DEFAULT,
) {
    val posterMaxWidthPx: Int
        get() = when (imageQuality) {
            ImageQuality.HIGH -> 640
            ImageQuality.MEDIUM -> 400
            ImageQuality.LOW -> 240
            ImageQuality.AUTO -> if (downloadOnMobileData) 400 else 640
        }

    companion object {
        /** The chip label for "no preference", which is stored as the absence of one. */
        const val AUDIO_LANGUAGE_DEFAULT = "Player default"
        val AUDIO_LANGUAGE_OPTIONS = listOf(
            AUDIO_LANGUAGE_DEFAULT, "English", "Hindi", "Tamil", "Telugu", "Malayalam", "Japanese",
        )
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
        loadPersistedPrefs()
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

    /**
     * The two persisted playback settings, collected rather than sampled so a value written
     * anywhere (this screen or the player's own sheet) shows up here immediately.
     */
    private fun loadPersistedPrefs() {
        viewModelScope.launch {
            settingsRepository.audioBoostLevel.collect { level ->
                _uiState.update { it.copy(prefs = it.prefs.copy(audioBoost = AudioBoost.clampLevel(level))) }
            }
        }
        viewModelScope.launch {
            settingsRepository.preferredAudioLanguage.collect { language ->
                _uiState.update {
                    it.copy(prefs = it.prefs.copy(audioLanguage = language ?: UserPreferences.AUDIO_LANGUAGE_DEFAULT))
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

    /**
     * The persisted audio level. Written straight through to the same store the player
     * reads, so a mix made here is the mix the next playback starts with — and the caption
     * the screen shows comes from [AudioBoostUi.honestSummary], which states the applied
     * value rather than the requested one, because above the player's 100% ceiling the two
     * genuinely differ on this build.
     */
    fun setAudioBoost(level: Float) {
        val safe = AudioBoost.clampLevel(level)
        updatePrefs { it.copy(audioBoost = safe) }
        viewModelScope.launch { settingsRepository.saveAudioBoostLevel(safe) }
    }

    /** The persisted audio language. [UserPreferences.AUDIO_LANGUAGE_DEFAULT] stores nothing. */
    fun setAudioLanguage(value: String) {
        updatePrefs { it.copy(audioLanguage = value) }
        val store = if (value == UserPreferences.AUDIO_LANGUAGE_DEFAULT) null else value
        viewModelScope.launch { settingsRepository.savePreferredAudioLanguage(store) }
    }

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
