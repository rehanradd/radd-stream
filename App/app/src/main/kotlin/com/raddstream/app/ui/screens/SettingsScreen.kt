package com.raddstream.app.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
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
import androidx.compose.material.icons.filled.Email
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.Storage
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
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
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.raddstream.app.brand.Brand
import com.raddstream.app.data.RegionChoices
import com.raddstream.app.data.RemoteFeatures
import com.raddstream.app.player.AudioBoost
import com.raddstream.app.player.AudioBoostUi
import com.raddstream.app.share.LanShareStatus
import com.raddstream.app.ui.components.RaddDialogTitle
import com.raddstream.app.ui.components.raddFilterChipColors
import com.raddstream.app.viewmodel.AccountCardCopy
import com.raddstream.app.viewmodel.AccountUiState
import com.raddstream.app.viewmodel.ContactUiState
import com.raddstream.app.viewmodel.ImageQuality
import com.raddstream.app.viewmodel.KeepTtl
import com.raddstream.app.viewmodel.MembershipCardCopy
import com.raddstream.app.viewmodel.SettingsViewModel
import com.raddstream.app.viewmodel.UserPreferences

/** The subtitle chips, in the order the row shows them. Readable by the region test, which
 * pins that a card can only ever seed a word this row can actually display. */
internal val subtitleOptions = listOf("Off", "English", "Hindi", "Urdu", "Tamil", "Telugu")

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
    /** Session 123: the account screens — dashboard, profile, coins. */
    onOpenDashboard: () -> Unit = {},
    onOpenProfile: () -> Unit = {},
    onOpenCoins: () -> Unit = {},
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
        // CL-7: the screen's title says "Settings" and so does its nav tab —
        // the title is paint, not a second announcement. The same treatment
        // applies to any other screen whose TopAppBar title exactly matches its
        // nav-tab label; Settings was the one Robo flagged.
        topBar = { TopAppBar(title = { Text("Settings", modifier = Modifier.clearAndSetSemantics { }) }) },
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
                // The address is never printed here: a saved server reads as
                // "Connected", and the field opens only when the viewer asks
                // to change it. The test still fetches the counts for its own
                // message, which never includes the address either.
                if (!state.showServerField) {
                    Text(
                        text = if (state.serverUrl.isNotBlank()) "Connected to your catalog." else "No catalog server set.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(10.dp))
                    OutlinedButton(onClick = viewModel::revealServerField, modifier = Modifier.fillMaxWidth()) {
                        Text("Change")
                    }
                } else {
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
                }

                // No counts here: works/releases/links are the operator's numbers,
                // not something a viewer needs to see on their own Settings screen.
                // The connection test above still fetches them for its own message.
            }

            // The region row lives in its own card at the top of Settings, not
            // buried in Playback & Display: it is the one row the viewer needs
            // after every region change, and it must be findable without
            // scrolling past a dozen cards (Session 114).
            SettingsCard(title = "Watching region") {
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
            }

            // ── Downloads entry ────────────────────────────────────────
            if (features.downloads) {
                SettingsCard(title = "Offline", icon = Icons.Default.Download) {
                    Text(
                        "Manage kept-for-offline titles, view storage use and expiry.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(10.dp))
                    SwitchRow(
                        checked = state.prefs.wifiOnlyDownloads,
                        onCheckedChange = viewModel::setWifiOnlyDownloads,
                        label = "Download only on Wi-Fi",
                    )
                    Text(
                        "A title you keep downloads only when this phone is on Wi-Fi. Turn it off to download on mobile data too.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(10.dp))
                    SwitchRow(
                        checked = state.prefs.autoDeleteWatched,
                        onCheckedChange = viewModel::setAutoDeleteWatched,
                        label = "Delete watched downloads",
                    )
                    Text(
                        "A finished download deletes itself to free space. A finished series episode deletes its own keep too — only the episode you just watched, never the rest of the season.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(10.dp))
                    OutlinedButton(onClick = onOpenDownloads, modifier = Modifier.fillMaxWidth()) {
                        Text("Open Media Vault")
                    }
                }
            }

            // ── VIP membership ─────────────────────────────────────────
            SettingsCard(title = "VIP Membership", icon = Icons.Default.Star) {
                // The plan summary: what this install actually has (VIP with its
                // date, a payment waiting, the free VIP days, or free) plus the
                // operator's published prices when the server sent any. The
                // summary lives in [MembershipCardCopy] so a test can pin it:
                // a trial in progress must never read as "Free plan" here while
                // the Account card says the free days are running (Session 114).
                Text(
                    MembershipCardCopy.summary(
                        planIsVip = state.planIsVip,
                        planVipUntilMillis = state.planVipUntilMillis,
                        planPaymentPending = state.planPaymentPending,
                        trialDays = state.account.trialDays,
                    ),
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.Medium,
                )
                if (state.planMonthlyPkr > 0 || state.planYearlyPkr > 0) {
                    Text(
                        buildString {
                            if (state.planMonthlyPkr > 0) {
                                append("Rs ${"%,d".format(state.planMonthlyPkr)} a month")
                            }
                            if (state.planYearlyPkr > 0) {
                                if (isNotEmpty()) append(" · ")
                                append("Rs ${"%,d".format(state.planYearlyPkr)} a year")
                            }
                        },
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Text(
                    "Support the catalog with a monthly or yearly membership. Pay through " +
                        "JazzCash, EasyPaisa or Raast, then submit the transaction ID from " +
                        "your confirmation.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Button(onClick = onOpenVipUpgrade, modifier = Modifier.fillMaxWidth()) {
                    Text(if (state.planIsVip) "View membership" else "Upgrade to VIP")
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

                // Session 123: the account screens live here — the dashboard
                // that answers "where do I stand?", the profile, and the coins.
                Row {
                    TextButton(onClick = onOpenDashboard) {
                        Text("Dashboard")
                    }
                    TextButton(onClick = onOpenProfile) {
                        Text("Profile")
                    }
                    TextButton(onClick = onOpenCoins) {
                        Text("Coins")
                    }
                }

                // ── the free days this install was granted ───────────────────────
                account.trialSecondsLeft?.let { secondsLeft ->
                    val daysLeft = account.trialDays ?: 0
                    Text(
                        if (daysLeft > 0) AccountCardCopy.trialActive(daysLeft) else AccountCardCopy.TRIAL_ENDED,
                        style = MaterialTheme.typography.bodyMedium,
                        color = if (daysLeft > 0) {
                            MaterialTheme.colorScheme.primary
                        } else {
                            MaterialTheme.colorScheme.onSurfaceVariant
                        },
                        fontWeight = FontWeight.Medium,
                    )
                    if (daysLeft > 0) {
                        Text(
                            AccountCardCopy.TRIAL_HONESTY,
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }

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
                    // Honest, and it must stay honest: the warning names the transport the
                    // server in use actually speaks — plain HTTP in the clear, or TLS for
                    // the shipped default — instead of implying a protection the transport
                    // does not provide.
                    Text(
                        SettingsViewModel.revealWarning(state.serverUrl),
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

                // ── the phone + PIN profile link ─────────────────────────
                //
                // Offered only to a device that holds a key: the route writes onto the account the
                // bearer names, so with no credential there is nothing to link and the honest thing
                // is to hide the form rather than let it fail.
                if (account.signedIn) {
                    Spacer(Modifier.height(10.dp))
                    Text(
                        AccountCardCopy.LINK_TITLE,
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.Medium,
                    )
                    Text(
                        AccountCardCopy.LINK_BONUS,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.primary,
                    )
                    Text(
                        AccountCardCopy.LINK_PIN_MEANING,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    OutlinedButton(
                        onClick = viewModel::openLinkForm,
                        enabled = !account.isLinking,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(if (account.showLinkForm) "Close" else AccountCardCopy.LINK_BUTTON)
                    }
                    if (account.showLinkForm) {
                        ProfileLinkDialog(account = account, viewModel = viewModel, serverUrl = state.serverUrl)
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

            // ── Contact us ───────────────────────────────────────────────────
            SettingsCard(title = "Contact us", icon = Icons.Default.Email) {
                Text(
                    "Report a problem, ask about a payment, or ask for a title to be taken down. No account needed.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                OutlinedButton(
                    onClick = viewModel::openContactForm,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text("Write to us")
                }
                state.contact.message?.let { msg ->
                    Text(
                        msg,
                        style = MaterialTheme.typography.labelSmall,
                        color = if (state.contact.messageIsError) {
                            MaterialTheme.colorScheme.error
                        } else {
                            MaterialTheme.colorScheme.onSurfaceVariant
                        },
                    )
                }
                if (state.contact.showForm) {
                    ContactDialog(contact = state.contact, viewModel = viewModel)
                }
            }

            // ── Disclaimer ───────────────────────────────────────────────────
            // The card shows the effective disclaimer: the panel's text when
            // the operator wrote one, else the shipped default — so there is
            // always one to read, and "No disclaimer published yet" can no
            // longer happen.
            SettingsCard(title = "Disclaimer", icon = Icons.Default.Info) {
                val disclaimer = state.disclaimer.effective()
                Text(
                    "Version ${disclaimer.version} — what this app is, and what it is not.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                OutlinedButton(
                    onClick = viewModel::openDisclaimer,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text("Read the disclaimer")
                }
                if (state.showDisclaimer) {
                    DisclaimerDialog(
                        disclaimer = disclaimer,
                        confirmLabel = "Close",
                        onConfirm = viewModel::closeDisclaimer,
                        onDismissRequest = viewModel::closeDisclaimer,
                    )
                }
            }

            // ── Anonymous usage totals (Tracking A) ──────────────────────
            // Totals only: how many plays, how often playback fails, how
            // often the app crashes. No name, number, location, title, or
            // search — and the switch is the same answer the first-run
            // dialog asked, changeable here at any time.
            SettingsCard(title = "Anonymous usage totals", icon = Icons.Default.Info) {
                Text(
                    "Share anonymous totals with the operator: plays, " +
                        "playback failures, and crashes. Nothing that can " +
                        "identify you or what you watch is ever sent.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                SwitchRow(
                    checked = state.analyticsConsent == true,
                    onCheckedChange = viewModel::setAnalyticsConsent,
                    label = "Share anonymous totals",
                )
            }

            // ── Playback & Display preferences ─────────────────────────
            // ── Languages ──────────────────────────────────────────────
            // The ONE place that shows the languages in force. The Region
            // card picks them, the player sheet changes them mid-title, and
            // these chips change them here — all three write the same keys,
            // and this card shows the effective values, so a viewer never has
            // to guess which one won.
            SettingsCard(title = "Languages") {
                Text(
                    "Audio: ${state.prefs.audioLanguage}. Subtitles: ${state.prefs.subtitleLang}.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )

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
                PreferenceRowTitle("Default subtitle language")
                ChipRow(subtitleOptions, subtitleOptions.indexOf(state.prefs.subtitleLang).coerceAtLeast(0)) { idx ->
                    viewModel.setSubtitleLang(subtitleOptions[idx])
                }
            }

            SettingsCard(title = "Playback & Display") {
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
                // A keep is gated by the Wi-Fi-only switch in the Offline card above,
                // not by this one — this switch only ever governed the thumbnails.
                Text(
                    "A title you keep follows the Wi-Fi-only switch in the Offline card; this only " +
                        "governs the thumbnails on the screens you browse.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )

                Spacer(Modifier.height(10.dp))
                PreferenceRowTitle("Data Saver")
                SwitchRow(
                    checked = state.prefs.dataSaver,
                    onCheckedChange = viewModel::setDataSaver,
                    label = "Save mobile data while watching",
                )
                Text(
                    "On mobile data, titles start at 480p and the server is asked for its data-saving copy. Wi-Fi is untouched, and you can still switch a title up in the player.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )

                Spacer(Modifier.height(10.dp))
                PreferenceRowTitle("Offline keep duration")
                ChipRow(KeepTtl.entries.map { it.label }, KeepTtl.entries.indexOf(state.prefs.keepTtl)) { idx ->
                    viewModel.setKeepTtl(KeepTtl.entries.toList()[idx])
                }

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
                        "from the next poster, the keep duration from the next download.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            // ── Player defaults ──────────────────────────────────────
            // The switches the player itself obeys (plan §5 step 10, P36): autoplay-next
            // gates the auto-advance, autoplay-previews gates the Home hero, default
            // quality is the rung a new title starts on when Play was Auto, and subtitle
            // size is the same number the player sheet's slider writes.
            SettingsCard(title = "Player", icon = Icons.Default.PlayArrow) {
                SwitchRow(
                    checked = state.prefs.autoplayNext,
                    onCheckedChange = viewModel::setAutoplayNext,
                    label = "Play the next episode automatically",
                )
                Text(
                    "When this is off, an episode ends on the Next Episode button instead of moving on by itself.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                SwitchRow(
                    checked = state.prefs.autoplayPreviews,
                    onCheckedChange = viewModel::setAutoplayPreviews,
                    label = "Auto-play previews on Home",
                )
                Text(
                    "When this is off, the Home hero stays on the first poster until you swipe it.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                // PL-10: opt-in auto-enter picture-in-picture. Off by default: a
                // window the viewer did not open is a window they did not ask for.
                SwitchRow(
                    checked = state.prefs.autoPip,
                    onCheckedChange = viewModel::setAutoPip,
                    label = "Auto picture-in-picture",
                )
                Text(
                    "When this is on, leaving the player while a title is playing keeps it playing in a small window.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )

                Spacer(Modifier.height(10.dp))
                PreferenceRowTitle("Default quality")
                val qualityBands = listOf("auto", "480p", "720p", "1080p", "2160p")
                val qualityLabels = listOf("Auto", "480p", "720p", "1080p", "4K")
                ChipRow(qualityLabels, qualityBands.indexOf(state.prefs.defaultQuality).coerceAtLeast(0)) { idx ->
                    viewModel.setDefaultQuality(qualityBands[idx])
                }
                Text(
                    "The quality a new title starts on. Auto lets the player pick; a fixed choice starts there and stays.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )

                Spacer(Modifier.height(10.dp))
                PreferenceRowTitle("Subtitle size")
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Text(
                        "${state.prefs.subtitleSizePercent}%",
                        style = MaterialTheme.typography.labelLarge,
                        color = MaterialTheme.colorScheme.primary,
                    )
                    Slider(
                        value = state.prefs.subtitleSizePercent.toFloat(),
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

            // ── Cache ──────────────────────────────────────────────────
            SettingsCard(title = "Storage & cache") {
                // The poster-image cache as a bar: what it holds now against the
                // loader's own cap. Nothing here is a guess at the device's free
                // space, and the kept videos are not in this number at all — they
                // are listed and removed on the Media Vault screen.
                val cacheBytes = state.posterCacheBytes
                val cacheMax = state.posterCacheMaxBytes
                if (cacheBytes != null && cacheMax != null) {
                    Text(
                        "Poster images: ${viewModel.formatCacheSize(cacheBytes)} of " +
                            viewModel.formatCacheSize(cacheMax),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    LinearProgressIndicator(
                        progress = { cacheBytes.toFloat() / cacheMax.toFloat().coerceAtLeast(1f) },
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
                Button(onClick = viewModel::clearImageCache, modifier = Modifier.fillMaxWidth()) {
                    Text("Clear poster images")
                }
                Text(
                    "This clears only the poster images the app has fetched; they come back as you " +
                        "browse. Videos you kept for offline are not touched here — they are removed " +
                        "individually on the Media Vault screen.",
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
internal fun SwitchRow(checked: Boolean, onCheckedChange: (Boolean) -> Unit, label: String) {
    Row(
        // Robo run 4: the row-level merged name ("<label>, on/off") never
        // reached Robo — the Switch's own toggleable node is what a screen
        // reader hears, and it only announced its bare state ("On"). So the
        // Switch itself carries the label as its spoken name, and its
        // toggleable state is what announces on/off. The painted label is
        // paint-only, so the words are heard once, on the control itself.
        // Internal so the a11y test can pin the spoken name directly.
        modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            label,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.weight(1f).clearAndSetSemantics { },
        )
        Switch(
            checked = checked,
            onCheckedChange = onCheckedChange,
            modifier = Modifier.semantics { contentDescription = label },
        )
    }
}

@Composable
private fun ChipRow(options: List<String>, selectedIndex: Int, onSelect: (Int) -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        options.forEachIndexed { idx, label ->
            FilterChip(colors = raddFilterChipColors(), selected = idx == selectedIndex, onClick = { onSelect(idx) }, label = { Text(label) })
        }
    }
}

@Composable
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

/**
 * The phone + PIN form. Three fields, four sentences, one button.
 *
 * The name field is not decoration: `accounts.link_profile_with_pin` refuses an empty display name
 * (`_check_profile_name`), so a form that collected only a number and a PIN would fail on a route
 * this app cannot change. Every warning below is the truth about the server in use — the transport
 * it speaks, a number that is not a secret, a day that is granted once — because the alternative
 * to saying it here is a viewer discovering it by being harvested.
 */
@Composable
internal fun ProfileLinkDialog(account: AccountUiState, viewModel: SettingsViewModel, serverUrl: String) {
    AlertDialog(
        onDismissRequest = viewModel::closeLinkForm,
        // D-2: one dialog title style everywhere — display family,
        // semibold, 20sp.
        title = { RaddDialogTitle(AccountCardCopy.LINK_TITLE) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    value = account.linkName,
                    onValueChange = viewModel::onLinkNameChanged,
                    label = { Text(AccountCardCopy.LINK_NAME_LABEL) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = account.linkPhone,
                    onValueChange = viewModel::onLinkPhoneChanged,
                    label = { Text(AccountCardCopy.LINK_PHONE_LABEL) },
                    placeholder = { Text("03XXXXXXXXX") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone),
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = account.linkPin,
                    onValueChange = viewModel::onLinkPinChanged,
                    label = { Text(AccountCardCopy.LINK_PIN_LABEL) },
                    singleLine = true,
                    // Masked so the four digits are not readable over a shoulder on the way in. It
                    // says nothing about how they travel, which the sentence below is for.
                    visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(
                        keyboardType = KeyboardType.NumberPassword,
                        autoCorrect = false,
                    ),
                    modifier = Modifier.fillMaxWidth(),
                )
                Text(
                    AccountCardCopy.linkTransportWarning(serverUrl),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.error,
                )
                Text(
                    AccountCardCopy.LINK_ONCE_PER_ACCOUNT,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    AccountCardCopy.LINK_WHICH_SERVER,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                account.linkMessage?.let { message ->
                    Text(
                        message,
                        style = MaterialTheme.typography.labelSmall,
                        color = if (account.linkMessageIsError) {
                            MaterialTheme.colorScheme.error
                        } else {
                            MaterialTheme.colorScheme.onSurfaceVariant
                        },
                    )
                }
            }
        },
        confirmButton = {
            Button(
                onClick = viewModel::linkProfile,
                enabled = !account.isLinking &&
                    account.linkName.isNotBlank() &&
                    account.linkPhone.isNotBlank() &&
                    account.linkPin.isNotEmpty(),
            ) {
                BusyLabel(account.isLinking, "Send")
            }
        },
        dismissButton = {
            TextButton(onClick = viewModel::closeLinkForm, enabled = !account.isLinking) {
                Text("Cancel")
            }
        },
    )
}

/**
 * The contact form. Five categories, one message, one optional email.
 *
 * The chips wrap (FlowRow) because five of them do not fit one row on a
 * narrow phone, and the plain Row the language chips use would clip the
 * last one. The email is optional and the line under it says what the
 * server does with it — stores it shortened — because a form that quietly
 * collects an address is a form that harvests one.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun ContactDialog(contact: ContactUiState, viewModel: SettingsViewModel) {
    AlertDialog(
        onDismissRequest = viewModel::closeContactForm,
        title = { RaddDialogTitle("Write to us") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    ContactUiState.CATEGORY_LABELS.forEachIndexed { idx, label ->
                        FilterChip(
                            colors = raddFilterChipColors(),
                            selected = ContactUiState.CATEGORY_IDS[idx] == contact.category,
                            onClick = { viewModel.onContactCategoryChanged(ContactUiState.CATEGORY_IDS[idx]) },
                            label = { Text(label) },
                        )
                    }
                }
                OutlinedTextField(
                    value = contact.subject,
                    onValueChange = viewModel::onContactSubjectChanged,
                    label = { Text("Subject (optional)") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = contact.body,
                    onValueChange = viewModel::onContactBodyChanged,
                    label = { Text("Your message") },
                    minLines = 4,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = contact.email,
                    onValueChange = viewModel::onContactEmailChanged,
                    label = { Text("Your email (optional)") },
                    placeholder = { Text("So we can reply") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
                    modifier = Modifier.fillMaxWidth(),
                )
                Text(
                    "Your email is stored shortened, so only part of it is ever visible to us.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                contact.message?.let { message ->
                    Text(
                        message,
                        style = MaterialTheme.typography.labelSmall,
                        color = if (contact.messageIsError) {
                            MaterialTheme.colorScheme.error
                        } else {
                            MaterialTheme.colorScheme.onSurfaceVariant
                        },
                    )
                }
            }
        },
        confirmButton = {
            Button(
                onClick = viewModel::submitContact,
                enabled = !contact.isSending && contact.body.isNotBlank(),
            ) {
                BusyLabel(contact.isSending, "Send")
            }
        },
        dismissButton = {
            TextButton(onClick = viewModel::closeContactForm, enabled = !contact.isSending) {
                Text("Cancel")
            }
        },
    )
}
