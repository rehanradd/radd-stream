package com.raddstream.app.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.raddstream.app.R
import com.raddstream.app.ui.components.raddFilterChipColors
import com.raddstream.app.viewmodel.LanguagesViewModel
import com.raddstream.app.viewmodel.UserPreferences

/**
 * One Languages screen: the audio language, the subtitle language and the
 * subtitle size in force, all in one place, each showing the value the next
 * playback will actually use.
 *
 * Four surfaces used to write these three values without ever showing them
 * together — the Region card, the Settings chips, the Settings subtitle-size
 * row, and the player sheet — and a viewer could change one without knowing
 * what the others said. They all write the same stored keys, so this screen
 * changes them through the same repository methods and every surface follows.
 * Nothing is removed here: the old surfaces stay until this screen is proven.
 */
@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun LanguagesScreen(
    onBackClick: () -> Unit,
    viewModel: LanguagesViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = { Text("Languages") },
                navigationIcon = {
                    IconButton(onClick = onBackClick) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        },
    ) { contentPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(contentPadding)
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(20.dp),
        ) {
            // F5a (Batch A): each value names where it came from — "your choice"
            // or "<Region> default" — so this screen and the Settings card can
            // never disagree without saying why.
            Text(
                "Audio: ${state.audioLanguage} (${state.audioProvenance}). " +
                    "Subtitles: ${state.subtitleLanguage} (${state.subtitleProvenance}). " +
                    "Subtitle size: ${state.subtitleSizePercent}%.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            LanguageSection(title = "Preferred audio language") {
                // The chips wrap: eight options do not fit one row on a phone, and a
                // row that scrolls sideways hides the choice a viewer is looking for.
                LanguageChipRow(
                    options = UserPreferences.AUDIO_LANGUAGE_OPTIONS,
                    selectedIndex = UserPreferences.AUDIO_LANGUAGE_OPTIONS
                        .indexOf(state.audioLanguage).coerceAtLeast(0),
                    onSelect = { idx -> viewModel.setAudioLanguage(UserPreferences.AUDIO_LANGUAGE_OPTIONS[idx]) },
                )
                // F1 (Batch A): the old paragraph explained the track-picking rule in
                // implementation words ("dual audio", "the player picks the track that
                // says so"). What the viewer needs is one plain sentence.
                Text(
                    stringResource(R.string.languages_audio_help),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            LanguageSection(title = "Default subtitle language") {
                LanguageChipRow(
                    options = subtitleOptions,
                    selectedIndex = subtitleOptions
                        .indexOf(state.subtitleLanguage).coerceAtLeast(0),
                    onSelect = { idx -> viewModel.setSubtitleLanguage(subtitleOptions[idx]) },
                )
                Text(
                    "The subtitles a new title starts with. Off means none until you turn " +
                        "them on in the player. Saved on this device.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            LanguageSection(title = "Subtitle size") {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Text(
                        "${state.subtitleSizePercent}%",
                        style = MaterialTheme.typography.labelLarge,
                        color = MaterialTheme.colorScheme.primary,
                    )
                    Slider(
                        value = state.subtitleSizePercent.toFloat(),
                        onValueChange = { viewModel.setSubtitleSize(it.toInt()) },
                        valueRange = 50f..200f,
                        modifier = Modifier.weight(1f),
                    )
                }
                Text(
                    "The same size the player sheet offers while watching; it applies from the next playback.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            // F1 (Batch A): the old paragraph explained the shared-storage plumbing
            // ("one stored value underneath them") — an implementation detail no
            // viewer needs. The behaviour is one plain sentence now.
            Text(
                stringResource(R.string.languages_sync_help),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/** One headed section: a title, then the controls under it. */
@Composable
private fun LanguageSection(
    title: String,
    content: @Composable () -> Unit,
) {
    Column(
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text(
            text = title,
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onSurface,
            fontWeight = FontWeight.SemiBold,
        )
        content()
    }
}

/** The chip row, wrapping: the audio list is eight long and must not scroll sideways. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun LanguageChipRow(
    options: List<String>,
    selectedIndex: Int,
    onSelect: (Int) -> Unit,
) {
    FlowRow(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        options.forEachIndexed { idx, label ->
            FilterChip(
                selected = idx == selectedIndex,
                onClick = { onSelect(idx) },
                label = { Text(label) },
                // F3 (Batch A): this was the one bare FilterChip in the app — no
                // emerald selected treatment. It now uses the shared token, and
                // the selected chip also carries a check, so the choice is not
                // colour-only (a viewer who cannot tell the greens apart can
                // still see which language is picked).
                colors = raddFilterChipColors(),
                leadingIcon = if (idx == selectedIndex) {
                    {
                        Icon(
                            imageVector = Icons.Filled.Check,
                            contentDescription = null, // the chip label already says which language
                            modifier = Modifier.size(18.dp),
                        )
                    }
                } else {
                    null
                },
                // Audit #54: a FilterChip is 32 dp tall — the touch-target floor is 48 dp, so the chip itself carries it.
                modifier = Modifier.heightIn(min = 48.dp),
            )
        }
    }
}
