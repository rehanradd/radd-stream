package com.raddstream.app.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.data.RegionChoices
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.data.UserRegion
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** The region the viewer is looking at, plus whether its save is still in flight. */
data class RegionUiState(
    val selectedId: String = UserRegion.DEFAULT,
    val isSaving: Boolean = false,
    /**
     * Set only by a write that actually threw. The screen owns the sentence; this carries the
     * fact — the exception's own text names internals a viewer has no use for.
     */
    val saveFailed: Boolean = false,
)

/**
 * The first-run content preference.
 *
 * Choosing writes one atomic record: the region, the audio/subtitle defaults that region
 * implies, and the fact that the question was answered. It is deliberately the only place
 * that sets `region_choice_recorded` — a default that could not be told apart from an answer
 * would send every returning viewer back through this screen.
 *
 * The stored region is read once, at construction, rather than continuously: this screen
 * lets a viewer tap a card before anything is saved, and an echo of the old stored value
 * would silently undo the tap they just made.
 */
@HiltViewModel
class RegionViewModel @Inject constructor(
    private val settingsRepository: ServerSettingsRepository,
) : ViewModel() {

    private val _ui = MutableStateFlow(RegionUiState())
    val uiState = _ui.asStateFlow()

    init {
        viewModelScope.launch {
            val stored = settingsRepository.userRegion.first()
            _ui.update { it.copy(selectedId = UserRegion.normalize(stored)) }
        }
    }

    fun select(id: String) {
        _ui.update { it.copy(selectedId = UserRegion.normalize(id), saveFailed = false) }
    }

    /** The card's own words about what picking it does — never re-invented by the caller. */
    fun choiceFor(id: String) = RegionChoices.byId(id)

    /**
     * Save the answer, then go. A DataStore write can fail — a full disk, a corrupted preferences
     * file, a process killed mid-edit — and this call is the only place that sets
     * `region_choice_recorded`, so a swallowed failure would leave the screen reporting a success
     * that storage never got. The caller is invoked only when the write returned.
     */
    fun saveAndContinue(onSaved: () -> Unit) {
        if (_ui.value.isSaving) return
        val choice = RegionChoices.byId(_ui.value.selectedId)
        _ui.update { it.copy(isSaving = true, saveFailed = false) }
        viewModelScope.launch {
            val stored = runCatching {
                settingsRepository.saveRegionChoice(
                    region = choice.id,
                    audioLanguage = choice.audioLanguage,
                    subtitleLanguage = choice.subtitleLanguage,
                )
            }
            _ui.update { it.copy(isSaving = false, saveFailed = stored.isFailure) }
            if (stored.isSuccess) onSaved()
        }
    }
}
