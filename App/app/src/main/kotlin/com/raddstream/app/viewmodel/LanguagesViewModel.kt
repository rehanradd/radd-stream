package com.raddstream.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.player.LanguageDefaults
import com.raddstream.app.player.SubtitleUiSettings
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * The Languages screen's state: the three values in force — the audio language, the
 * subtitle language, and the subtitle size — each one already resolved to what the
 * player will actually use, not what the store happens to hold.
 */
data class LanguagesUiState(
    val audioLanguage: String = UserPreferences.AUDIO_LANGUAGE_DEFAULT,
    val subtitleLanguage: String = UserPreferences.SUBTITLE_DEFAULT,
    val subtitleSizePercent: Int = 100,
)

/**
 * The one mapping from stored values to the screen's state, kept pure so it is
 * testable on this JVM without a DataStore: a stored pick always wins; a viewer who
 * never chose gets their region's default (Desi: Hindi audio, English subtitles);
 * a region with no stance on a row falls back to the player's own pick for audio
 * ("Player default") and off for subtitles. An explicit "Off" is stored as the word
 * itself, so it never falls back to the region's English — only a stored null does.
 * The size is the stored style's size, 50..200 %; the other four style fields are
 * the player sheet's business and this screen does not touch them.
 */
internal fun languagesStateOf(
    region: String,
    audio: String?,
    subtitle: String?,
    style: SubtitleUiSettings,
): LanguagesUiState = LanguagesUiState(
    audioLanguage = LanguageDefaults.effectiveAudioLanguage(audio, region)
        ?: UserPreferences.AUDIO_LANGUAGE_DEFAULT,
    subtitleLanguage = LanguageDefaults.effectiveSubtitleLanguage(subtitle, region)
        ?: UserPreferences.SUBTITLE_DEFAULT,
    subtitleSizePercent = style.sizePercent,
)

/**
 * One Languages screen, one source of truth. The Region card, the Settings chips,
 * the Settings size row and the player sheet all write the same three stored values
 * this screen reads — the two language keys and the subtitle style — so changing a
 * value here changes what every other surface shows, and what the next playback
 * picks, because there is only one store underneath them all.
 *
 * Nothing is removed by this screen: the Region card still picks them at first run,
 * the Settings chips still change them in place, and the player sheet still changes
 * the size mid-title. This screen is the single place to SEE all three at once; the
 * old surfaces stay until the screen is proven and the follow-up decides their fate.
 */
@HiltViewModel
class LanguagesViewModel @Inject constructor(
    private val settingsRepository: ServerSettingsRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(LanguagesUiState())
    val uiState = _uiState.asStateFlow()

    init {
        viewModelScope.launch {
            // One combine, not four collectors, so a region change and a language
            // change can never show a half-old pair — the audio row, the subtitle
            // row and the size always answer the same moment.
            combine(
                settingsRepository.userRegion,
                settingsRepository.preferredAudioLanguage,
                settingsRepository.preferredSubtitleLanguage,
                settingsRepository.subtitleStyle,
            ) { region, audio, subtitle, style ->
                languagesStateOf(region, audio, subtitle, style)
            }.collect { _uiState.value = it }
        }
    }

    /**
     * The persisted audio language, stored as the word itself — including
     * [UserPreferences.AUDIO_LANGUAGE_DEFAULT], so an explicit "leave it to the
     * player" is never mistaken for a viewer who never chose. The state updates
     * at once, the way the Settings chips do, and the store confirms it.
     */
    fun setAudioLanguage(value: String) {
        _uiState.update { it.copy(audioLanguage = value) }
        viewModelScope.launch { settingsRepository.savePreferredAudioLanguage(value) }
    }

    /** [UserPreferences.SUBTITLE_DEFAULT] is stored as the word itself, like the audio row. */
    fun setSubtitleLanguage(value: String) {
        _uiState.update { it.copy(subtitleLanguage = value) }
        viewModelScope.launch { settingsRepository.savePreferredSubtitleLanguage(value) }
    }

    /**
     * The subtitle size, 50..200 % — the same number the player sheet's slider
     * writes. Only the size moves: the other four style fields ride along
     * untouched, read fresh from the store at the moment of the write.
     */
    fun setSubtitleSize(percent: Int) {
        val safe = percent.coerceIn(50, 200)
        _uiState.update { it.copy(subtitleSizePercent = safe) }
        viewModelScope.launch {
            val current = settingsRepository.subtitleStyle.first()
            settingsRepository.saveSubtitleStyle(current.copy(sizePercent = safe))
        }
    }
}
