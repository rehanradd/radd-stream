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
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Star
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
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.raddstream.app.brand.Brand
import com.raddstream.app.data.RegionChoices
import com.raddstream.app.data.RemoteFeatures
import com.raddstream.app.player.AudioBoost
import com.raddstream.app.player.AudioBoostUi
import com.raddstream.app.share.LanShareStatus
import com.raddstream.app.viewmodel.CatalogScale
import com.raddstream.app.viewmodel.ImageQuality
import com.raddstream.app.viewmodel.KeepTtl
import com.raddstream.app.viewmodel.SettingsViewModel
import com.raddstream.app.viewmodel.UserPreferences

/** The subtitle chips, in the order the row shows them. Readable by the region test, which
 * pins that a card can only ever seed a word this row can actually display. */
internal val subtitleOptions = listOf("Off", "English", "Hindi", "Tamil", "Telugu")

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    /**
     * The operator's board. Two cards on this screen offer a feature it can switch off, and an
     * "Open Downloads" button that enqueues nothing is worse than no button at all.
     */
    features: RemoteFeatures = RemoteFeatures(),
    onOpenDownloads: () -> Unit = {},
    onOpenVipUpgrade: () -> Unit = {},
    onOpenRegionChoice: () -> Unit = {},
    viewModel: SettingsViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()

    // A status line this screen used to print inside the About card as a button that did
    // nothing. It is a transient answer to an action, so it lives where every other screen
    // in this app puts one: a snack bar, shown once, then cleared back through the ViewModel
    // so rotating the device does not re-announce a tap from ten minutes ago.
    val snackbarHostState = remember { SnackbarHostState() }
    LaunchedEffect(state.statusMessage) {
        val message = state.statusMessage ?: return@LaunchedEffect
        snackbarHostState.showSnackbar(message)
        viewModel.clearStatus()
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        snackbarHost = { SnackbarHost(snackbarHostState) },
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
                    placeholder = { Text("http://<host> — one address, any catalog you may use") },
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
                        StatBox(
                            label = CatalogScale.WORKS_LABEL,
                            value = stats.posts.toString(),
                        )
                        StatBox(
                            label = CatalogScale.RELEASES_LABEL,
                            value = stats.releases.toString(),
                        )
                        StatBox(
                            label = CatalogScale.LINKS_LABEL,
                            value = stats.sources.toString(),
                        )
                    }
                    Text(
                        CatalogScale.SCOPE_NOTE,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }

            // ── Downloads entry ────────────────────────────────────────
            if (features.downloads) {
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
            }

            // ── VIP membership ─────────────────────────────────────────
            SettingsCard(title = "VIP Membership", icon = Icons.Default.Star) {
                Text(
                    "Support the catalog with a monthly or yearly membership. Pay through " +
                        "JazzCash, EasyPaisa or Raast, then submit the transaction ID from " +
                        "your confirmation.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Button(onClick = onOpenVipUpgrade, modifier = Modifier.fillMaxWidth()) {
                    Text("Upgrade to VIP")
                }
            }

            // ── Share kept files on the local network ──────────────────
            // Gone, not disabled, when the operator switched sharing off: the row would otherwise
            // read "on" while LanShareRunner has already closed the socket it promises to open.
            if (features.sharing) {
                SettingsCard(title = "Share on your network") {
                    SwitchRow(
                        checked = state.lanShareEnabled,
                        onCheckedChange = viewModel::setLanShareEnabled,
                        label = "Let devices on this network play kept files",
                    )
                    Text(
                        lanShareStatusLine(state.lanShareStatus),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        "While this is on, anything on your local network can read your kept files.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }

            // ── The optional sync account ──────────────────────────────
            SettingsCard(title = "Account", icon = Icons.Default.Person) {
                val account = state.account
                Text(
                    if (account.signedIn) {
                        "Signed in on this device. Your saved list, watch history and resume points " +
                            "are kept on the connected server as well as here."
                    } else {
                        "Guest mode. Everything in this app works without an account: your saved " +
                            "list, watch history and resume points stay on this device. Sign in only " +
                            "if you want them on another device."
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )

                account.revealedKey?.let { key ->
                    OutlinedTextField(
                        value = key,
                        onValueChange = {},
                        readOnly = true,
                        label = { Text("Your sync key") },
                        textStyle = MaterialTheme.typography.bodySmall,
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                        trailingIcon = {
                            val clipboard = LocalClipboardManager.current
                            TextButton(onClick = { clipboard.setText(AnnotatedString(key)) }) {
                                Text("Copy")
                            }
                        },
                    )
                    // Honest, and it must stay honest: this deployment has no TLS, so the copy
                    // says the key crosses the network in the clear instead of implying a
                    // protection the transport does not provide.
                    Text(
                        SettingsViewModel.REVEAL_WARNING,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                    TextButton(onClick = viewModel::hideRevealedKey) { Text("Done showing this key") }
                }

                if (account.signedIn && account.revealedKey == null && account.keyHint.isNotEmpty()) {
                    Text(
                        "Key on this device: ${account.keyHint}. The full key was shown once, when it " +
                            "was created, and is not stored anywhere it can be re-displayed.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }

                if (!account.signedIn) {
                    OutlinedTextField(
                        value = account.quickInput,
                        onValueChange = viewModel::onQuickInputChanged,
                        label = { Text("Sync key") },
                        placeholder = { Text("The 16-character key from your other device") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    // The sentence this card used to print — "anyone who knows it can derive the
                    // same key" — described a feature that is now deleted, so it is replaced by
                    // the two facts that are true of what is left: a number cannot open an
                    // account, and the key is the whole account.
                    Text(
                        "Enter the key this app showed once, when it created the account. A mobile " +
                            "number is not a key and this app cannot turn one into a key: knowing " +
                            "someone's number gets them nowhere. An account is only as strong as " +
                            "its key, so keep the key somewhere safe, and sign out on any device " +
                            "that is not yours.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    AccountLabelField(
                        value = account.labelInput,
                        onValueChange = viewModel::onAccountLabelChanged,
                        onSave = null,
                    )
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        Button(
                            onClick = viewModel::quickSignIn,
                            enabled = !account.isBusy && account.quickInput.isNotBlank(),
                            modifier = Modifier.weight(1f),
                        ) {
                            BusyLabel(account.isBusy, "Sign in")
                        }
                        OutlinedButton(
                            onClick = viewModel::createAccount,
                            enabled = !account.isBusy,
                            modifier = Modifier.weight(1f),
                        ) {
                            Text("Create a random key")
                        }
                    }
                } else {
                    AccountLabelField(
                        value = if (account.labelInput.isEmpty()) account.accountLabel else account.labelInput,
                        onValueChange = viewModel::onAccountLabelChanged,
                        onSave = viewModel::saveAccountLabel,
                    )
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        Button(
                            onClick = viewModel::syncNow,
                            enabled = !account.isBusy,
                            modifier = Modifier.weight(1f),
                        ) {
                            BusyLabel(account.isBusy, "Sync now")
                        }
                        OutlinedButton(
                            onClick = viewModel::signOut,
                            enabled = !account.isBusy,
                            modifier = Modifier.weight(1f),
                        ) {
                            Text("Sign out (revokes the key)")
                        }
                    }
                }

                account.message?.let { msg ->
                    Text(
                        msg,
                        style = MaterialTheme.typography.labelSmall,
                        color = if (account.messageIsError) {
                            MaterialTheme.colorScheme.error
                        } else {
                            MaterialTheme.colorScheme.onSurfaceVariant
                        },
                    )
                }
                Text(
                    "Sync only ever names a title by the reference the server gave it, so a " +
                        "title this app cannot reference stays on this device. Your saved list " +
                        "is read from this device either way — offline, it shows exactly what it " +
                        "always showed.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            // ── Playback & Display preferences ─────────────────────────
            SettingsCard(title = "Playback & Display") {
                PreferenceRowTitle("Watching region")
                val region = RegionChoices.byId(state.userRegion)
                Text(
                    region.title,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Text(
                    region.preferenceLine(),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                TextButton(onClick = onOpenRegionChoice) {
                    Text("Change what you watch")
                }

                Spacer(Modifier.height(10.dp))
                PreferenceRowTitle("Image quality")
                ChipRow(ImageQuality.entries.toList().map { it.label }, ImageQuality.entries.indexOf(state.prefs.imageQuality)) { idx ->
                    viewModel.setImageQuality(ImageQuality.entries.toList()[idx])
                }

                Spacer(Modifier.height(10.dp))
                PreferenceRowTitle("Poster loading on mobile data")
                SwitchRow(
                    checked = state.prefs.downloadOnMobileData,
                    onCheckedChange = viewModel::setDownloadOnMobileData,
                    label = "Load poster images over mobile data",
                )
                // A keep you asked for downloads on any network, always — that promise is not
                // what this switch is for, so it no longer claims to be.
                Text(
                    "A title you kept offline downloads whatever network you are on; this only " +
                        "governs the thumbnails on the screens you browse.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
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
                        value = state.prefs.audioBoost.coerceIn(0f, AudioBoostUi.MAX_OFFERED_LEVEL),
                        onValueChange = viewModel::setAudioBoost,
                        valueRange = 0f..AudioBoostUi.MAX_OFFERED_LEVEL,
                        modifier = Modifier.weight(1f),
                    )
                }
                // Still worth saying: below the ceiling the boost is real, but it rides on the
                // viewer's own system volume, so the caption states what is applied, not what
                // was asked. The range above is already the range this build can honour.
                Text(
                    AudioBoostUi.honestSummary(state.prefs.audioBoost, 1f),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )

                // Wallpaper colour is a brand decision, not a user one: this brand file
                // locks the palette (features.dynamic_color=false), and a switch that is
                // overruled by the build it ships in is worse than no switch. It appears
                // the moment a re-skin permits it.
                if (Brand.dynamicColorAllowed) {
                    Spacer(Modifier.height(10.dp))
                    SwitchRow(
                        checked = state.prefs.dynamicColor,
                        onCheckedChange = viewModel::setDynamicColor,
                        label = "Dynamic colour from wallpaper",
                    )
                }
                Text(
                    "Saved on this device, and applied the next time each one matters: image size " +
                        "from the next poster, the keep duration from the next download, audio and " +
                        "subtitle language from the next playback.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            // ── Cache ──────────────────────────────────────────────────
            SettingsCard(title = "Storage & cache") {
                Button(onClick = viewModel::clearImageCache, modifier = Modifier.fillMaxWidth()) {
                    Text("Clear poster images")
                }
                Text(
                    "This clears only the poster images the app has fetched; they come back as you " +
                        "browse. Videos you kept for offline are not touched here — they are removed " +
                        "individually on the Downloads screen.",
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
                    "Version ${Brand.versionName} (${Brand.versionCode}) • ${Brand.schemeName}\n" +
                        "Connection: " +
                        if (state.serverUrl.trim().startsWith("https", ignoreCase = true)) {
                            "secured with TLS."
                        } else {
                            "plain HTTP — the server address you set does not use https, so anything " +
                                "this app sends, including a sync key, can be read on the local network."
                        },
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
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

/**
 * A button label that shows its own request. Kept to one helper so the account card's two
 * network-touching buttons spin the same indicator the server card already uses, and a tap
 * that is still in flight never looks like a tap that did nothing.
 */
@Composable
private fun BusyLabel(busy: Boolean, label: String) {
    if (busy) {
        CircularProgressIndicator(
            Modifier.size(18.dp),
            strokeWidth = 2.dp,
            color = MaterialTheme.colorScheme.onPrimary,
        )
    } else {
        Text(label)
    }
}

/**
 * The optional label the viewer types about themselves, and the only place a phone number is
 * ever asked for in this app.
 *
 * It is one field and, when signed in, one button. There is no derivation behind it: the text
 * goes to `ServerSettingsRepository.saveAccountLabel` and to no endpoint, and no decision about
 * whether a request is allowed reads it. [onSave] is null in the sign-in block, where pressing
 * Sign in commits whatever was typed, and non-null once an account is open and the label can be
 * edited on its own.
 */
@Composable
private fun AccountLabelField(
    value: String,
    onValueChange: (String) -> Unit,
    onSave: (() -> Unit)?,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        label = { Text("Label (optional)") },
        placeholder = { Text("A name or number, shown on this device only") },
        singleLine = true,
        modifier = Modifier.fillMaxWidth(),
    )
    Text(
        "Only so you can tell your own account apart. This stays on the device and is never sent.",
        style = MaterialTheme.typography.labelSmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    if (onSave != null) {
        TextButton(onClick = onSave) { Text("Save label") }
    }
}

@Composable
private fun PreferenceRowTitle(text: String) {    Text(text, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurface)
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

/**
 * Renders the socket's real state as one short line. Reports what is actually bound, not what was
 * asked: a share that could not bind says so plainly, and a live share names the concrete address and
 * the number of files currently servable so the row never advertises a URL that nothing answers on.
 */
private fun lanShareStatusLine(status: LanShareStatus): String = when (status) {
    LanShareStatus.Off -> "Off — nothing is shared on your network."
    LanShareStatus.Failed -> "On, but it could not start (port busy). No files are being shared."
    is LanShareStatus.Listening -> {
        val where = status.address?.let { "$it:${status.port}" } ?: "port ${status.port}"
        "Listening on $where · ${status.servableCount} kept ${if (status.servableCount == 1) "file" else "files"}"
    }
}
