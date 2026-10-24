package com.raddstream.app.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Storage
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.raddstream.app.brand.Brand
import com.raddstream.app.player.AudioBoost
import com.raddstream.app.player.AudioBoostUi
import com.raddstream.app.viewmodel.ImageQuality
import com.raddstream.app.viewmodel.KeepTtl
import com.raddstream.app.viewmodel.SettingsViewModel
import com.raddstream.app.viewmodel.UserPreferences

private val subtitleOptions = listOf("Off", "English", "Hindi", "Tamil", "Telugu")

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    onOpenDownloads: () -> Unit = {},
    viewModel: SettingsViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = { TopAppBar(title = { Text("Settings") }) },
    ) { contentPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(contentPadding)
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(18.dp),
        ) {
            // ── Server Connection ──────────────────────────────────────
            SettingsCard(title = "Catalog Server", icon = Icons.Default.Storage) {
                OutlinedTextField(
                    value = state.serverUrl,
                    onValueChange = viewModel::onServerUrlChanged,
                    label = { Text("Server URL") },
                    placeholder = { Text("http://92.4.95.252") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                state.testMessage?.let { msg ->
                    Text(
                        text = msg,
                        color = if (state.testIsError) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                Button(
                    onClick = viewModel::testAndSaveServer,
                    enabled = !state.isTesting && state.serverUrl.isNotBlank(),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    if (state.isTesting) {
                        CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp, color = MaterialTheme.colorScheme.onPrimary)
                    } else {
                        Icon(Icons.Default.Check, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(8.dp))
                        Text("Test & Save Connection")
                    }
                }

                val stats = state.stats
                if (stats != null) {
                    Spacer(Modifier.height(8.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceAround,
                    ) {
                        StatBox(label = "Titles", value = stats.posts.toString())
                        StatBox(label = "Releases", value = stats.releases.toString())
                        StatBox(label = "Streams", value = stats.sources.toString())
                    }
                    Text(
                        "Server totals include titles the browsable catalog hides for policy. Live counts reflect the connected server only.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }

            // ── Downloads entry ────────────────────────────────────────
            SettingsCard(title = "Offline", icon = Icons.Default.Download) {
                Text(
                    "Manage kept-for-offline titles, view storage use and expiry.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                OutlinedButton(onClick = onOpenDownloads, modifier = Modifier.fillMaxWidth()) {
                    Text("Open Downloads")
                }
            }

            // ── Playback & Display preferences ─────────────────────────
            SettingsCard(title = "Playback & Display") {
                PreferenceRowTitle("Image quality")
                ChipRow(ImageQuality.entries.toList().map { it.label }, ImageQuality.entries.indexOf(state.prefs.imageQuality)) { idx ->
                    viewModel.setImageQuality(ImageQuality.entries.toList()[idx])
                }

                Spacer(Modifier.height(10.dp))
                PreferenceRowTitle("Poster loading on mobile data")
                SwitchRow(
                    checked = state.prefs.downloadOnMobileData,
                    onCheckedChange = viewModel::setDownloadOnMobileData,
                    label = "Load images & keep items over mobile data",
                )

                Spacer(Modifier.height(10.dp))
                PreferenceRowTitle("Offline keep duration")
                ChipRow(KeepTtl.entries.map { it.label }, KeepTtl.entries.indexOf(state.prefs.keepTtl)) { idx ->
                    viewModel.setKeepTtl(KeepTtl.entries.toList()[idx])
                }

                Spacer(Modifier.height(10.dp))
                PreferenceRowTitle("Default subtitle language")
                ChipRow(subtitleOptions, subtitleOptions.indexOf(state.prefs.subtitleLang).coerceAtLeast(0)) { idx ->
                    viewModel.setSubtitleLang(subtitleOptions[idx])
                }

                Spacer(Modifier.height(10.dp))
                PreferenceRowTitle("Preferred audio language")
                val audioOptions = UserPreferences.AUDIO_LANGUAGE_OPTIONS
                ChipRow(audioOptions, audioOptions.indexOf(state.prefs.audioLanguage).coerceAtLeast(0)) { idx ->
                    viewModel.setAudioLanguage(audioOptions[idx])
                }
                Text(
                    "Half this catalog is dual audio. The player picks the track that says so; " +
                        "when nothing matches, its own choice is left alone rather than guessing. " +
                        "Saved on this device.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )

                Spacer(Modifier.height(10.dp))
                PreferenceRowTitle("Audio level")
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Text(
                        AudioBoost.labelFor(state.prefs.audioBoost),
                        style = MaterialTheme.typography.labelLarge,
                        color = MaterialTheme.colorScheme.primary,
                    )
                    Slider(
                        value = state.prefs.audioBoost.coerceIn(0f, AudioBoost.MAX),
                        onValueChange = viewModel::setAudioBoost,
                        valueRange = 0f..AudioBoost.MAX,
                        modifier = Modifier.weight(1f),
                    )
                }
                // The honest part: above the player's 100% ceiling this build adds no
                // software gain, so the caption states what is applied, not what was asked.
                Text(
                    AudioBoostUi.honestSummary(state.prefs.audioBoost, 1f),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )

                Spacer(Modifier.height(10.dp))
                SwitchRow(
                    checked = state.prefs.dynamicColor,
                    onCheckedChange = viewModel::setDynamicColor,
                    label = "Dynamic colour from wallpaper",
                )
                Text(
                    "Audio level and audio language are saved and read back by the player. " +
                        "Image size is applied where a consumer exists; full persistence of the " +
                        "remaining rows and dynamic-colour theming are requested from the " +
                        "data/theme owners (see About).",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            // ── Cache ──────────────────────────────────────────────────
            SettingsCard(title = "Storage & cache") {
                Button(onClick = viewModel::clearImageCache, modifier = Modifier.fillMaxWidth()) {
                    Text("Clear cache")
                }
                Text(
                    "Poster images are cached automatically. Offline keeps are cleared individually on the Downloads screen.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            // ── About / Disclaimer (accurate, no misleading claims) ─────
            SettingsCard(
                title = Brand.copy("settings_about_heading", "About ${Brand.name}"),
                icon = Icons.Default.Info,
            ) {
                Text(
                    Brand.copy(
                        "settings_about_body",
                        "${Brand.name} is a metadata catalog browser and source-link resolver for a catalog server "
                            + "you operate or are authorized to use. It aggregates public catalog metadata and resolves "
                            + "source links; it is not a hosting service and it does not display 18+ content.",
                    ),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    "Version: client build ${Brand.versionName} (${Brand.versionCode}) • ${Brand.schemeName}\nTransport: plain HTTP to the connected server (dev only)\n" +
                        "Search facets beyond title/type, server-side sort, and the offline cache engine are pending backend/engine work.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                state.statusMessage?.let { msg ->
                    TextButton(onClick = { }) { Text(msg) }
                }
            }
        }
    }
}

@Composable
private fun SettingsCard(
    title: String,
    icon: androidx.compose.ui.graphics.vector.ImageVector? = null,
    content: @Composable () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(MaterialTheme.colorScheme.surface)
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (icon != null) {
                Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
            }
            Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onBackground)
        }
        content()
    }
}

@Composable
private fun PreferenceRowTitle(text: String) {
    Text(text, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurface)
}

@Composable
private fun SwitchRow(checked: Boolean, onCheckedChange: (Boolean) -> Unit, label: String) {
    Row(
        modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(label, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurface, modifier = Modifier.weight(1f))
        Switch(checked = checked, onCheckedChange = onCheckedChange)
    }
}

@Composable
private fun ChipRow(options: List<String>, selectedIndex: Int, onSelect: (Int) -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        options.forEachIndexed { idx, label ->
            FilterChip(selected = idx == selectedIndex, onClick = { onSelect(idx) }, label = { Text(label) })
        }
    }
}

@Composable
private fun StatBox(label: String, value: String) {
    Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(value, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary)
        Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
