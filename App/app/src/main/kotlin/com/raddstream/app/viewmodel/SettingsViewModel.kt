package com.raddstream.app.viewmodel

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import coil.Coil
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.data.Telemetry
import com.raddstream.app.data.UserRegion
import com.raddstream.app.network.friendlyNetworkError
import com.raddstream.app.network.models.PanelDisclaimer
import com.raddstream.app.network.models.StatsResponse
import com.raddstream.app.player.AudioBoost
import com.raddstream.app.player.AudioBoostUi
import com.raddstream.app.player.LanguageDefaults
import com.raddstream.app.repository.CatalogRepository
import com.raddstream.app.share.LanShareRunner
import com.raddstream.app.share.LanShareStatus
import com.raddstream.app.sync.AccountMutation
import com.raddstream.app.sync.DeviceTrial
import com.raddstream.app.sync.LinkRefusal
import com.raddstream.app.sync.Refusal
import com.raddstream.app.sync.SyncAccountRepository
import com.raddstream.app.sync.ProfileLinkFiled
import com.raddstream.app.sync.SyncContract
import com.raddstream.app.sync.SyncReport
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

enum class ImageQuality(val label: String) {
    AUTO("Auto"), HIGH("High"), MEDIUM("Medium"), LOW("Battery saver");

    companion object {
        /** A stored name we do not recognise is the default, not a crash on cold start. */
        fun valueOfOrDefault(name: String): ImageQuality =
            entries.firstOrNull { it.name == name } ?: AUTO
    }
}

enum class KeepTtl(val label: String, val hours: Int) {
    H3("3 hours", 3), H6("6 hours", 6);

    companion object {
        fun fromHours(hours: Int): KeepTtl = entries.firstOrNull { it.hours == hours } ?: H3
    }
}

/**
 * Playback/display preferences. Every row here is persisted through the app's own DataStore
 * ([ServerSettingsRepository]) and every row has a consumer: the player applies the audio
 * level and language, the theme applies dynamic colour, the image loader applies image
 * quality and the mobile-data switch, and the offline sweeper applies the keep duration.
 * That is the whole point of this type — a control whose value is forgotten on process
 * death, or whose value nothing ever reads, is a decoration, and the screen says so out
 * loud rather than shipping one.
 */
data class UserPreferences(
    val imageQuality: ImageQuality = ImageQuality.AUTO,
    val downloadOnMobileData: Boolean = false,
    /** Data Saver: on mobile data, titles start at 480p. On by default. */
    val dataSaver: Boolean = true,
    /** Downloads start on Wi-Fi only. On by default. */
    val wifiOnlyDownloads: Boolean = true,
    /** A finished movie's download deletes itself. On by default. */
    val autoDeleteWatched: Boolean = true,
    val keepTtl: KeepTtl = KeepTtl.H3,
    val subtitleLang: String = SUBTITLE_DEFAULT,
    val dynamicColor: Boolean = false,
    /** The audio level in [AudioBoost]'s unit, already reduced to what this build can apply. */
    val audioBoost: Float = AudioBoost.BASELINE,
    /** The audio language in force — the stored pick, or the region's default when never set. */
    val audioLanguage: String = AUDIO_LANGUAGE_DEFAULT,
    /** F5a (Batch A): where [audioLanguage] came from — "your choice" or "<Region> default". */
    val audioProvenance: String = "Desi default",
    /** F5a (Batch A): where [subtitleLang] came from — "your choice" or "<Region> default". */
    val subtitleProvenance: String = "Desi default",
    /** Play the next episode on its own when this one ends (plan §5 step 10, D4: on). */
    val autoplayNext: Boolean = true,
    /** Let the Home hero move on its own (plan §5 step 10); off stops the carousel. */
    val autoplayPreviews: Boolean = true,
    /** PL-10: keep playing in a small window when the viewer leaves the player. Off by default. */
    val autoPip: Boolean = false,
    /** The rung a new title starts on when Play was Auto; "auto" = no default. */
    val defaultQuality: String = "auto",
    /** Subtitle text size, 50..200 % — the same number the player sheet's slider writes. */
    val subtitleSizePercent: Int = 100,
) {
    /**
     * The widest poster this install asks the image loader for, in pixels. This is the ONE
     * consumer of [imageQuality] and [downloadOnMobileData]: a smaller request is a
     * smaller download, which is what "Battery saver" and the mobile-data switch mean.
     */
    val posterMaxWidthPx: Int
        get() = when (imageQuality) {
            ImageQuality.HIGH -> 640
            ImageQuality.MEDIUM -> 400
            ImageQuality.LOW -> 240
            ImageQuality.AUTO -> if (downloadOnMobileData) 400 else 640
        }

    companion object {
        /** The chip label for the explicit "leave it to the player" pick, stored as the word itself. */
        const val AUDIO_LANGUAGE_DEFAULT = "Player default"
        val AUDIO_LANGUAGE_OPTIONS = listOf(
            // F23 (Batch B): Kannada joins the list — the catalog carries
            // Kannada titles, and the list had every other South Indian
            // language but this one.
            AUDIO_LANGUAGE_DEFAULT, "English", "Hindi", "Urdu", "Tamil", "Telugu", "Malayalam", "Kannada", "Japanese",
        )

        /** Subtitles start off — a catalog this mixed has no language worth guessing. */
        const val SUBTITLE_DEFAULT = "Off"
    }
}

data class SettingsUiState(
    val serverUrl: String = "",
    /**
     * The address field stays hidden until the viewer asks to change it:
     * the saved address is a value this screen holds, never a line it
     * prints on sight. The status line below is the only thing shown.
     */
    val showServerField: Boolean = false,
    val isTesting: Boolean = false,
    val testMessage: String? = null,
    val testIsError: Boolean = false,
    val stats: StatsResponse? = null,
    val isLoadingStats: Boolean = false,
    val prefs: UserPreferences = UserPreferences(),
    val statusMessage: String? = null,
    /** The persisted LAN-share opt-in — the same value [com.raddstream.app.share.LanShareRunner] obeys. */
    val lanShareEnabled: Boolean = false,
    /** The socket's real state, read from the runner so the row never claims more than is true. */
    val lanShareStatus: LanShareStatus = LanShareStatus.Off,
    /** The OPTIONAL sync account. Signed out, this card is one line and one button. */
    val account: AccountUiState = AccountUiState(),
    /**
     * The membership summary the VIP card paints — collected from the sync
     * account's entitlement, never invented: null entitlement means "not
     * loaded yet", so the card shows the free line until the server answers.
     * vipUntilMillis is 0 when there is no VIP grant to date.
     */
    val planIsVip: Boolean = false,
    val planVipUntilMillis: Long = 0L,
    val planPaymentPending: Boolean = false,
    /**
     * The operator's published prices, in PKR, from the remote config — 0
     * means "not published", and the card hides the price line rather than
     * printing a zero. Fetched once when Settings opens; a failed fetch
     * leaves the last known values (0 on a fresh install).
     */
    val planMonthlyPkr: Int = 0,
    val planYearlyPkr: Int = 0,
    /**
     * The poster-image disk cache, measured from Coil's own disk cache —
     * null until the first measurement lands. max is the loader's own cap,
     * so the bar is size-of-cap, never a guess at the device's free space.
     */
    val posterCacheBytes: Long? = null,
    val posterCacheMaxBytes: Long? = null,
    /** The contact form's whole state. The message lives only until it is sent. */
    val contact: ContactUiState = ContactUiState(),
    /**
     * The regional-dub choice the onboarding screen wrote, normalized. Seeded with
     * [UserRegion.DEFAULT] because the store always answers a value — the card label below
     * shows which one, and tapping it opens the same screen the first install showed.
     */
    val userRegion: String = UserRegion.DEFAULT,
    /**
     * The operator's disclaimer, as last received. Empty text means "nothing
     * published" — the card says so instead of showing an empty dialog.
     */
    val disclaimer: PanelDisclaimer = PanelDisclaimer(),
    /** The disclaimer dialog the Settings card opens, if any. */
    val showDisclaimer: Boolean = false,
    /**
     * Tracking A: whether this install shares anonymous usage totals.
     * Null means the first-run dialog was never answered — the switch reads
     * off until it is, because "never asked" must not paint as a choice the
     * viewer made.
     */
    val analyticsConsent: Boolean? = null,
)

/**
 * The account card's whole state, and the reason the card can stay honest.
 *
 * [revealedKey] is the only place a full key exists in UI state. It is filled by exactly two code
 * paths — a key this screen's own button just minted, and a key the launch trial minted that this
 * card has not shown yet — and both clear it on the same tap, so a credential is never kept on
 * screen after the viewer said they had written it down. The second path is the one exception to
 * "never read back out of storage", and it exists because the trial mints while no screen is open:
 * without it the app would have created an account whose key nobody could ever see.
 * [keyHint] is what the card falls back to: a partial preview, which is enough to tell two
 * accounts apart and is not a usable key.
 * [keyHint] is what the card falls back to: a partial preview, which is enough to tell two
 * accounts apart and is not a usable key.
 *
 * [accountLabel] is the only other account text this card paints, and it is the opposite of a
 * key in every respect: the viewer typed it about themselves, it is sent nowhere, and nothing
 * that authorizes a request reads it. [labelInput] is the unfinished edit of the same value.
 */
data class AccountUiState(
    val signedIn: Boolean = false,
    val revealedKey: String? = null,
    val keyHint: String = "",
    val quickInput: String = "",
    val accountLabel: String = "",
    val labelInput: String = "",
    val isBusy: Boolean = false,
    val message: String? = null,
    val messageIsError: Boolean = false,
    val lastReport: SyncReport? = null,
    /**
     * Seconds left on the server's trial answer, or null when this install has never been granted
     * one. Null and 0.0 are different statements — "nothing was ever given" versus "it ran out" —
     * and the card must not confuse them, because the second one is a claim about a grant.
     */
    val trialSecondsLeft: Double? = null,
    val showLinkForm: Boolean = false,
    val linkName: String = "",
    val linkPhone: String = "",
    /** Lives only while the form is open, and is cleared the moment the call is made. */
    val linkPin: String = "",
    val isLinking: Boolean = false,
    val linkMessage: String? = null,
    val linkMessageIsError: Boolean = false,
) {
    /** Whole days to show, or null when there is no trial to count. */
    val trialDays: Int? get() = trialSecondsLeft?.let { DeviceTrial.daysRemaining(it) }

    /** True when a trial was granted here and has run out. */
    val trialExpired: Boolean get() = trialSecondsLeft != null && trialSecondsLeft <= 0.0
}

/**
 * The contact form's whole state. The category ids are the panel's own five
 * (`contact_messages.category`); the labels are what the chips show. The
 * email is optional — it is only how the operator replies — and the server
 * stores it masked, so this screen never shows a full address back.
 */
data class ContactUiState(
    val showForm: Boolean = false,
    val category: String = "other",
    val subject: String = "",
    val body: String = "",
    val email: String = "",
    val isSending: Boolean = false,
    val message: String? = null,
    val messageIsError: Boolean = false,
) {
    companion object {
        val CATEGORY_IDS: List<String> = listOf("bug", "payment", "content", "takedown", "other")
        val CATEGORY_LABELS: List<String> = listOf("Bug", "Payment", "Content", "Takedown", "Other")
    }
}

@HiltViewModel
class SettingsViewModel @Inject constructor(
    @ApplicationContext private val context: Context,
    private val settingsRepository: ServerSettingsRepository,
    private val catalogRepository: CatalogRepository,
    private val lanShareRunner: LanShareRunner,
    private val syncAccountRepository: SyncAccountRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(SettingsUiState())
    val uiState = _uiState.asStateFlow()

    init {
        loadServerUrlAndStats()
        loadPersistedPrefs()
        observeLanShare()
        observeAccount()
        observeTrial()
        observePlan()
        measurePosterCache()
    }

    /**
     * The account card reads the stored key rather than a copy of it, so a sign-in made on
     * another screen (or a sign-out forced by the server refusing a key mid-sync) is reflected
     * here the moment it happens. Only [AccountUiState.signedIn] and the preview are derived from
     * storage. The full key reaches this screen by exactly two routes: the one this screen's own
     * button just minted, and — see the flag below — the one the launch trial minted while no
     * screen was open, which is the last moment that plaintext will ever exist.
     */
    private fun observeAccount() {
        viewModelScope.launch {
            syncAccountRepository.syncKey.collect { key ->
                val usable = key?.takeIf { it.isNotBlank() }
                // One-shot: a key the launch trial minted while no screen was open. Cleared by
                // hideRevealedKey, so this branch can only ever fire the first time the card is
                // opened after that mint — which is the point, and the reason it is a flag in
                // storage rather than a field in this state.
                val unseenMint = usable != null && syncAccountRepository.trialKeyUnseen.first()
                _uiState.update {
                    it.copy(
                        account = it.account.copy(
                            signedIn = usable != null,
                            keyHint = SyncContract.keyPreview(usable),
                            revealedKey = if (unseenMint) usable else it.account.revealedKey,
                        ),
                    )
                }
            }
        }
        viewModelScope.launch {
            settingsRepository.accountLabel.collect { label ->
                _uiState.update {
                    it.copy(account = it.account.copy(accountLabel = label.orEmpty()))
                }
            }
        }
    }

    /**
     * The trial countdown, read the way every other stored value here is read: collected, not
     * sampled, so a grant that landed while this screen was closed shows up on the next open.
     * [DeviceTrial.secondsRemaining] does the arithmetic against the instant the server's answer
     * was read, which is what makes a wrong wall clock change nothing.
     */
    private fun observeTrial() {
        viewModelScope.launch {
            settingsRepository.trialRecordedAtMs.collect { recordedAtMs ->
                val seconds = if (recordedAtMs <= 0L) {
                    null
                } else {
                    DeviceTrial.secondsRemaining(
                        storedSecondsRemaining = settingsRepository.trialSecondsRemaining.first(),
                        storedAtMs = recordedAtMs,
                        nowMs = System.currentTimeMillis(),
                    )
                }
                _uiState.update { it.copy(account = it.account.copy(trialSecondsLeft = seconds)) }
            }
        }
    }

    /**
     * The membership summary for the VIP card: the entitlement the sync
     * account already collects (a VIP grant is server truth, never a local
     * guess) plus the operator's published prices from the remote config.
     * Both are best-effort — a null entitlement means "not loaded yet" and
     * a failed price fetch leaves 0, which the card reads as "not published".
     */
    private fun observePlan() {
        viewModelScope.launch {
            syncAccountRepository.entitlement.collect { entitlement ->
                _uiState.update {
                    it.copy(
                        planIsVip = entitlement?.vip == true,
                        planVipUntilMillis = ((entitlement?.vipUntil ?: 0.0) * 1000).toLong(),
                        planPaymentPending = entitlement?.pending == true,
                    )
                }
            }
        }
        viewModelScope.launch {
            runCatching { catalogRepository.getRemoteConfig() }.onSuccess { config ->
                _uiState.update {
                    it.copy(
                        planMonthlyPkr = config.vip.monthlyPkr.takeIf { price -> price > 0 } ?: 0,
                        planYearlyPkr = config.vip.yearlyPkr.takeIf { price -> price > 0 } ?: 0,
                    )
                }
            }
        }
    }

    /** Reads Coil's own disk cache size and cap, on IO because both are file I/O. */
    private fun measurePosterCache() {
        viewModelScope.launch {
            val (bytes, max) = withContext(Dispatchers.IO) {
                val disk = Coil.imageLoader(context).diskCache
                (disk?.size to disk?.maxSize)
            }
            _uiState.update { it.copy(posterCacheBytes = bytes, posterCacheMaxBytes = max) }
        }
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
     * Every row in the Playback & Display card, collected rather than sampled so a value
     * written anywhere shows up here immediately, and so a tap survives process death.
     * These twelve flows are the whole preference layer: the player, the theme, the image
     * loader, the offline sweeper and the release selector each read the same stored values,
     * which is what makes a chip here a setting rather than a decoration.
     */
    private fun loadPersistedPrefs() {
        viewModelScope.launch {
            settingsRepository.audioBoostLevel.collect { level ->
                _uiState.update { it.copy(prefs = it.prefs.copy(audioBoost = AudioBoostUi.offeredLevel(level))) }
            }
        }
        viewModelScope.launch {
            // The chips show the language in force, not the stored word: a viewer who never
            // chose still sees their region's default (Desi: Hindi audio, English subtitles),
            // because that is what the player will actually play. One combine, not three
            // collectors, so a region change and a language change can never show a half-old
            // pair — the audio row and the subtitle row always answer the same region.
            combine(
                settingsRepository.userRegion,
                settingsRepository.preferredAudioLanguage,
                settingsRepository.preferredSubtitleLanguage,
            ) { region, audio, subtitle ->
                // F5a: the provenance rides with the effective value, decided by the
                // same stored-vs-blank rule — a stored word is the viewer's pick,
                // a blank means the region's default is speaking.
                Triple(
                    LanguageDefaults.effectiveAudioLanguage(audio, region)
                        ?: UserPreferences.AUDIO_LANGUAGE_DEFAULT,
                    LanguageDefaults.effectiveSubtitleLanguage(subtitle, region)
                        ?: UserPreferences.SUBTITLE_DEFAULT,
                    Pair(provenanceOf(audio, region), provenanceOf(subtitle, region)),
                )
            }.collect { (audio, subtitle, provenances) ->
                _uiState.update {
                    it.copy(
                        prefs = it.prefs.copy(
                            audioLanguage = audio,
                            subtitleLang = subtitle,
                            audioProvenance = provenances.first,
                            subtitleProvenance = provenances.second,
                        ),
                    )
                }
            }
        }
        viewModelScope.launch {
            settingsRepository.imageQualityChoice.collect { choice ->
                _uiState.update { it.copy(prefs = it.prefs.copy(imageQuality = ImageQuality.valueOfOrDefault(choice))) }
            }
        }
        viewModelScope.launch {
            settingsRepository.mobileDataAllowed.collect { allowed ->
                _uiState.update { it.copy(prefs = it.prefs.copy(downloadOnMobileData = allowed)) }
            }
        }
        viewModelScope.launch {
            settingsRepository.dataSaver.collect { enabled ->
                _uiState.update { it.copy(prefs = it.prefs.copy(dataSaver = enabled)) }
            }
        }
        viewModelScope.launch {
            settingsRepository.wifiOnlyDownloads.collect { enabled ->
                _uiState.update { it.copy(prefs = it.prefs.copy(wifiOnlyDownloads = enabled)) }
            }
        }
        viewModelScope.launch {
            settingsRepository.autoDeleteWatched.collect { enabled ->
                _uiState.update { it.copy(prefs = it.prefs.copy(autoDeleteWatched = enabled)) }
            }
        }
        viewModelScope.launch {
            settingsRepository.keepTtlHours.collect { hours ->
                _uiState.update { it.copy(prefs = it.prefs.copy(keepTtl = KeepTtl.fromHours(hours))) }
            }
        }
        viewModelScope.launch {
            settingsRepository.dynamicColorEnabled.collect { enabled ->
                _uiState.update { it.copy(prefs = it.prefs.copy(dynamicColor = enabled)) }
            }
        }
        // Player defaults (plan §5 step 10): the autoplay switches, the standing
        // default quality, and the subtitle size the player sheet's slider also writes.
        viewModelScope.launch {
            settingsRepository.autoplayNext.collect { enabled ->
                _uiState.update { it.copy(prefs = it.prefs.copy(autoplayNext = enabled)) }
            }
        }
        viewModelScope.launch {
            settingsRepository.autoplayPreviews.collect { enabled ->
                _uiState.update { it.copy(prefs = it.prefs.copy(autoplayPreviews = enabled)) }
            }
        }
        // PL-10: the auto-PiP switch the player obeys when the viewer leaves mid-title.
        viewModelScope.launch {
            settingsRepository.autoPip.collect { enabled ->
                _uiState.update { it.copy(prefs = it.prefs.copy(autoPip = enabled)) }
            }
        }
        viewModelScope.launch {
            settingsRepository.defaultQuality.collect { band ->
                _uiState.update { it.copy(prefs = it.prefs.copy(defaultQuality = band)) }
            }
        }
        viewModelScope.launch {
            settingsRepository.subtitleStyle.collect { style ->
                _uiState.update { it.copy(prefs = it.prefs.copy(subtitleSizePercent = style.sizePercent)) }
            }
        }
        // Collected, not sampled: the region screen this row opens writes the same key, so the
        // label a viewer comes back to must already be the one they just chose.
        viewModelScope.launch {
            settingsRepository.userRegion.collect { region ->
                _uiState.update { it.copy(userRegion = region) }
            }
        }
        // The disclaimer card shows what the last poll brought in, the same
        // way the region row does: a new version the operator publishes
        // appears here without the viewer having to reopen the app.
        viewModelScope.launch {
            settingsRepository.disclaimer.collect { disclaimer ->
                _uiState.update { it.copy(disclaimer = disclaimer) }
            }
        }
        // Tracking A: the totals switch shows the viewer's own answer, and
        // follows it when the first-run dialog is answered while Settings is
        // open behind it.
        viewModelScope.launch {
            settingsRepository.analyticsConsent.collect { consent ->
                _uiState.update { it.copy(analyticsConsent = consent) }
            }
        }
    }

    /** Open the disclaimer text this install has on file. */
    fun openDisclaimer() {
        _uiState.update { it.copy(showDisclaimer = true) }
    }

    /** Close the disclaimer dialog. Reading it here does not accept it: acceptance happens only on the first-run dialog, once per version. */
    fun closeDisclaimer() {
        _uiState.update { it.copy(showDisclaimer = false) }
    }

    /**
     * Tracking A: change the totals answer from Settings. The snapshot is
     * refreshed at once, so turning totals off stops the next request's
     * headers without a restart, and turning them on mints the install id
     * and starts counting from that moment — never retroactively.
     */
    fun setAnalyticsConsent(accepted: Boolean) {
        viewModelScope.launch {
            settingsRepository.saveAnalyticsConsent(accepted)
            Telemetry.refresh(settingsRepository)
        }
    }

    /**
     * LAN share: the switch reads the persisted preference (the single source the runner also obeys),
     * and the status line reads the socket's real state from the runner. Both are collected, never
     * sampled, so the row reflects what is actually bound the moment it changes — including on another
     * screen or after a restart — rather than what was last tapped here.
     */
    private fun observeLanShare() {
        viewModelScope.launch {
            settingsRepository.lanShareEnabled.collect { enabled ->
                _uiState.update { it.copy(lanShareEnabled = enabled) }
            }
        }
        viewModelScope.launch {
            lanShareRunner.status.collect { status ->
                _uiState.update { it.copy(lanShareStatus = status) }
            }
        }
    }

    /**
     * Turn LAN sharing on or off. The ViewModel is the only writer of this preference — the socket
     * itself is owned by the Application's [com.raddstream.app.share.LanShareRunner], which reacts to
     * this exact stored value, so the UI never reaches a network stack directly.
     */
    fun setLanShareEnabled(value: Boolean) {
        _uiState.update { it.copy(lanShareEnabled = value) }
        viewModelScope.launch { settingsRepository.saveLanShareEnabled(value) }
    }

    fun onServerUrlChanged(newUrl: String) {
        _uiState.update { it.copy(serverUrl = newUrl, testMessage = null) }
    }

    /** Open the address field: the viewer's explicit choice to see and change it. */
    fun revealServerField() {
        _uiState.update { it.copy(showServerField = true) }
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
                        testMessage = CatalogScale.connectionNotice(stats.posts),
                        testIsError = false,
                        stats = stats,
                    )
                }
            } catch (ex: Exception) {
                _uiState.update {
                    it.copy(isTesting = false, testMessage = friendlyNetworkError(ex, "Connection failed."), testIsError = true)
                }
            }
        }
    }

    fun setImageQuality(value: ImageQuality) {
        updatePrefs { it.copy(imageQuality = value) }
        viewModelScope.launch { settingsRepository.saveImageQualityChoice(value.name) }
    }

    fun setDownloadOnMobileData(value: Boolean) {
        updatePrefs { it.copy(downloadOnMobileData = value) }
        viewModelScope.launch { settingsRepository.saveMobileDataAllowed(value) }
    }

    fun setDataSaver(value: Boolean) {
        updatePrefs { it.copy(dataSaver = value) }
        viewModelScope.launch { settingsRepository.saveDataSaver(value) }
    }

    fun setWifiOnlyDownloads(value: Boolean) {
        updatePrefs { it.copy(wifiOnlyDownloads = value) }
        viewModelScope.launch { settingsRepository.saveWifiOnlyDownloads(value) }
    }

    fun setAutoDeleteWatched(value: Boolean) {
        updatePrefs { it.copy(autoDeleteWatched = value) }
        viewModelScope.launch { settingsRepository.saveAutoDeleteWatched(value) }
    }

    fun setKeepTtl(value: KeepTtl) {
        updatePrefs { it.copy(keepTtl = value) }
        viewModelScope.launch { settingsRepository.saveKeepTtlHours(value.hours) }
    }

    /** [UserPreferences.SUBTITLE_DEFAULT] is stored as the word itself, like the audio row. */
    fun setSubtitleLang(value: String) {
        // F5a: a tap IS a stored pick, so the provenance flips at once.
        updatePrefs { it.copy(subtitleLang = value, subtitleProvenance = "your choice") }
        viewModelScope.launch { settingsRepository.savePreferredSubtitleLanguage(value) }
    }

    fun setDynamicColor(value: Boolean) {
        updatePrefs { it.copy(dynamicColor = value) }
        viewModelScope.launch { settingsRepository.saveDynamicColorEnabled(value) }
    }

    /**
     * The persisted audio level. Written straight through to the same store the player
     * reads, so a mix made here is the mix the next playback starts with — and the caption
     * the screen shows comes from [AudioBoostUi.honestSummary], which states the applied
     * value rather than the requested one, because above the player's 100% ceiling the two
     * genuinely differ on this build.
     */
    fun setAudioBoost(level: Float) {
        val safe = AudioBoostUi.offeredLevel(level)
        updatePrefs { it.copy(audioBoost = safe) }
        viewModelScope.launch { settingsRepository.saveAudioBoostLevel(safe) }
    }

    /**
     * The persisted audio language, stored as the word itself — including
     * [UserPreferences.AUDIO_LANGUAGE_DEFAULT], so an explicit "leave it to the player" is
     * never mistaken for a viewer who never chose (only a stored null falls back to the
     * region's default).
     */
    fun setAudioLanguage(value: String) {
        // F5a: a tap IS a stored pick, so the provenance flips at once.
        updatePrefs { it.copy(audioLanguage = value, audioProvenance = "your choice") }
        viewModelScope.launch { settingsRepository.savePreferredAudioLanguage(value) }
    }

    /**
     * Player defaults (plan §5 step 10, P36). Each one writes straight through to the
     * same store its consumer reads — the player for autoplay-next and default quality,
     * the Home hero for autoplay-previews, the subtitle renderer for size — so a switch
     * here is a setting, not a decoration.
     */
    fun setAutoplayNext(enabled: Boolean) {
        updatePrefs { it.copy(autoplayNext = enabled) }
        viewModelScope.launch { settingsRepository.saveAutoplayNext(enabled) }
    }

    fun setAutoplayPreviews(enabled: Boolean) {
        updatePrefs { it.copy(autoplayPreviews = enabled) }
        viewModelScope.launch { settingsRepository.saveAutoplayPreviews(enabled) }
    }

    /** PL-10: the auto-PiP switch — off by default, a window the viewer did not open is one they did not ask for. */
    fun setAutoPip(enabled: Boolean) {
        updatePrefs { it.copy(autoPip = enabled) }
        viewModelScope.launch { settingsRepository.saveAutoPip(enabled) }
    }

    fun setDefaultQuality(band: String) {
        updatePrefs { it.copy(defaultQuality = band) }
        viewModelScope.launch { settingsRepository.saveDefaultQuality(band) }
    }

    /** The subtitle size, 50..200 % — the same number the player sheet's slider writes. */
    fun setSubtitleSize(percent: Int) {
        val safe = percent.coerceIn(50, 200)
        updatePrefs { it.copy(subtitleSizePercent = safe) }
        viewModelScope.launch {
            val current = settingsRepository.subtitleStyle.first()
            settingsRepository.saveSubtitleStyle(current.copy(sizePercent = safe))
        }
    }

    /**
     * Drop the app's fetched images: [Coil.imageLoader] is the same singleton every
     * [com.raddstream.app.ui.components.CatalogImage] paints from — the app installs no custom
     * loader — so this empties what the app actually downloaded, not a copy of it. Memory is
     * cleared inline because `clear()` is free; the disk cache is walked and deleted on an IO
     * thread because `size` and `clear()` are file I/O. Offline keeps are a different store and
     * are deliberately untouched: they are listed and removed on the Downloads screen.
     */
    fun clearImageCache() {
        val loader = Coil.imageLoader(context)
        loader.memoryCache?.clear()
        _uiState.update { it.copy(statusMessage = "Clearing cached poster images…") }
        viewModelScope.launch {
            val freedBytes = withContext(Dispatchers.IO) {
                val disk = loader.diskCache
                if (disk == null) 0L else disk.size.also { disk.clear() }
            }
            _uiState.update {
                it.copy(
                    statusMessage = if (freedBytes <= 0L) {
                        "No cached poster images to clear."
                    } else {
                        "Cleared ${formatCacheSize(freedBytes)} of cached poster images."
                    },
                )
            }
            // The bar must show the empty cache, not the size it measured before the clear.
            measurePosterCache()
        }
    }

    /** Shared with the screen: the same MB/KB/B rule paints the cache bar and the cleared notice. */
    internal fun formatCacheSize(bytes: Long): String = when {
        bytes >= 1024 * 1024 -> "${bytes / (1024 * 1024)} MB"
        bytes >= 1024 -> "${bytes / 1024} KB"
        else -> "$bytes B"
    }

    private fun updatePrefs(transform: (UserPreferences) -> UserPreferences) {
        _uiState.update { it.copy(prefs = transform(it.prefs)) }
    }

    fun clearStatus() {
        _uiState.update { it.copy(statusMessage = null) }
    }

    // ── The optional sync account ────────────────────────────────────────────────

    /**
     * Create an account on the connected server. The answer's key is put into UI state exactly
     * once, by this call and by no other path, because the server only ever sends it here.
     */
    fun createAccount() {
        if (noServerYet()) return
        accountAction { syncAccountRepository.createAccount() }
    }

    /**
     * One tap: sign in with a 16-character sync key the viewer already holds, then pull the
     * library down immediately. The sign-in answer alone would leave a second device
     * signed in but empty until the viewer found "Sync now", which is exactly the extra tap
     * this flow exists to remove. A failed first sync does not undo the sign-in.
     *
     * The optional label is written whether or not the key opened anything: it is a note the
     * viewer typed about themselves, not part of the credential, so a refused sign-in keeps it.
     */
    fun quickSignIn() {
        if (noServerYet()) return
        val candidate = _uiState.value.account.quickInput
        if (candidate.isBlank() || _uiState.value.account.isBusy) return
        _uiState.update { it.copy(account = it.account.copy(isBusy = true, message = null)) }
        viewModelScope.launch {
            // The label is written before the key is asked about, and stays whatever it is on a
            // refusal: it is a note the viewer typed about themselves, not part of the credential.
            persistAccountLabel(_uiState.value.account.labelInput)
            when (val outcome = syncAccountRepository.quickSignIn(candidate)) {
                is AccountMutation.SignedIn -> {
                    val report = syncAccountRepository.syncNow()
                    // A sync that hit a 401/404 drops the key; do not leave the card claiming
                    // a sign-in the storage no longer backs.
                    val stillSignedIn = syncAccountRepository.signedIn.first()
                    _uiState.update {
                        it.copy(
                            account = it.account.copy(
                                isBusy = false,
                                signedIn = stillSignedIn,
                                revealedKey = null,
                                quickInput = "",
                                lastReport = report,
                                message = if (stillSignedIn) {
                                    syncSentence(
                                        report,
                                        paused = syncAccountRepository.isPaused,
                                        signedIn = true,
                                    )
                                } else {
                                    refusalSentence(Refusal.SIGNED_OUT)
                                },
                                messageIsError = !stillSignedIn || !report.completed,
                            ),
                        )
                    }
                }
                is AccountMutation.Refused -> _uiState.update {
                    it.copy(
                        account = it.account.copy(
                            isBusy = false,
                            message = refusalSentence(outcome.reason),
                            messageIsError = true,
                        ),
                    )
                }
            }
        }
    }

    /**
     * The card's own precondition: an account is a row on the connected server, so without a
     * server there is nothing to ask. Checked here rather than deep in the sync layer, because
     * this screen is the one place that knows whether the URL field has anything in it.
     */
    private fun noServerYet(): Boolean {
        if (_uiState.value.serverUrl.isNotBlank()) return false
        _uiState.update {
            it.copy(
                account = it.account.copy(
                    message = refusalSentence(Refusal.NO_SERVER),
                    messageIsError = true,
                ),
            )
        }
        return true
    }

    fun onQuickInputChanged(value: String) {
        _uiState.update { it.copy(account = it.account.copy(quickInput = value, message = null)) }
    }

    fun onAccountLabelChanged(value: String) {
        _uiState.update { it.copy(account = it.account.copy(labelInput = value)) }
    }

    /**
     * "Save what I am called": the optional label, on its own, without touching the key.
     *
     * A label is display data — it is never sent and no decision reads it — so a failed write
     * costs a name on a card and must not be reported as a sign-in problem. The canonical form
     * is echoed back into the field so what is stored is what the viewer sees.
     */
    fun saveAccountLabel() {
        viewModelScope.launch { persistAccountLabel(_uiState.value.account.labelInput) }
    }

    /** The one writer of the label. Returns the value that ended up stored, null for "none". */
    private suspend fun persistAccountLabel(raw: String?): String? {
        val label = SyncContract.accountLabel(raw)
        runCatching { settingsRepository.saveAccountLabel(label) }
        _uiState.update {
            it.copy(
                account = it.account.copy(
                    accountLabel = label.orEmpty(),
                    labelInput = label.orEmpty(),
                ),
            )
        }
        return label
    }

    /**
     * Drop the full key on this screen; the preview stays, the credential does not linger. This is
     * also what retires a trial-minted key's one-shot: the flag is cleared here and nowhere else,
     * so a key the launch minted can be shown exactly once from storage.
     */
    fun hideRevealedKey() {
        _uiState.update { it.copy(account = it.account.copy(revealedKey = null)) }
        viewModelScope.launch { syncAccountRepository.acknowledgeTrialKeyShown() }
    }

    // ── the phone + PIN profile link ─────────────────────────────────────────────

    fun openLinkForm() {
        _uiState.update {
            it.copy(
                account = it.account.copy(
                    showLinkForm = true,
                    linkMessage = null,
                    linkMessageIsError = false,
                ),
            )
        }
    }

    /** Closing wipes the PIN and the phone: nothing the viewer typed for one attempt lingers. */
    fun closeLinkForm() {
        _uiState.update {
            it.copy(
                account = it.account.copy(
                    showLinkForm = false,
                    linkName = "",
                    linkPhone = "",
                    linkPin = "",
                    linkMessage = null,
                ),
            )
        }
    }

    fun onLinkNameChanged(value: String) {
        _uiState.update { it.copy(account = it.account.copy(linkName = value, linkMessage = null)) }
    }

    fun onLinkPhoneChanged(value: String) {
        _uiState.update { it.copy(account = it.account.copy(linkPhone = value, linkMessage = null)) }
    }

    fun onLinkPinChanged(value: String) {
        _uiState.update { it.copy(account = it.account.copy(linkPin = value, linkMessage = null)) }
    }

    /**
     * Send the three fields to `profile-link`. The value of a PIN never appears in any sentence
     * this produces — including the validation ones, which name the field and its shape and stop
     * there — and the field is cleared before the request goes out, so the state this screen holds
     * while it waits contains no credential.
     */
    fun linkProfile() {
        val account = _uiState.value.account
        if (account.isLinking) return
        // The card's own precondition, said in the dialog rather than in the card's message slot:
        // a profile is a row on a server, and with no address there is no server to write to.
        if (_uiState.value.serverUrl.isBlank()) {
            _uiState.update {
                it.copy(
                    account = it.account.copy(
                        linkMessage = refusalSentence(Refusal.NO_SERVER),
                        linkMessageIsError = true,
                    ),
                )
            }
            return
        }
        val error = DeviceTrial.nameError(account.linkName)
            ?: DeviceTrial.phoneError(account.linkPhone)
            ?: DeviceTrial.pinError(account.linkPin)
        if (error != null) {
            _uiState.update {
                it.copy(
                    account = it.account.copy(linkMessage = error, linkMessageIsError = true),
                )
            }
            return
        }
        val name = account.linkName.trim()
        val phone = account.linkPhone.trim()
        val pin = account.linkPin
        _uiState.update {
            it.copy(
                account = it.account.copy(
                    isLinking = true,
                    linkPin = "",
                    linkMessage = null,
                    linkMessageIsError = false,
                ),
            )
        }
        viewModelScope.launch {
            when (val outcome = syncAccountRepository.linkProfile(name, phone, pin)) {
                is ProfileLinkFiled.Linked -> _uiState.update {
                    it.copy(
                        account = it.account.copy(
                            isLinking = false,
                            showLinkForm = false,
                            linkName = "",
                            linkPhone = "",
                            linkPin = "",
                            linkMessage = AccountCardCopy.linkSentence(outcome.bonusDayGranted),
                            linkMessageIsError = false,
                        ),
                    )
                }
                is ProfileLinkFiled.Refused -> _uiState.update {
                    it.copy(
                        account = it.account.copy(
                            isLinking = false,
                            linkMessage = AccountCardCopy.linkRefusalSentence(outcome.reason),
                            linkMessageIsError = true,
                        ),
                    )
                }
            }
        }
    }

    // ── Contact us ───────────────────────────────────────────────────────

    fun openContactForm() {
        _uiState.update {
            it.copy(contact = it.contact.copy(showForm = true, message = null, messageIsError = false))
        }
    }

    fun closeContactForm() {
        _uiState.update { it.copy(contact = it.contact.copy(showForm = false)) }
    }

    fun onContactCategoryChanged(value: String) {
        _uiState.update { it.copy(contact = it.contact.copy(category = value)) }
    }

    fun onContactSubjectChanged(value: String) {
        _uiState.update { it.copy(contact = it.contact.copy(subject = value)) }
    }

    fun onContactBodyChanged(value: String) {
        _uiState.update { it.copy(contact = it.contact.copy(body = value)) }
    }

    fun onContactEmailChanged(value: String) {
        _uiState.update { it.copy(contact = it.contact.copy(email = value)) }
    }

    /**
     * Send the form to the operator's inbox. The body is the only required
     * field — a message with nothing in it is not a message. On success the
     * form closes and its fields clear, and the card keeps the one-line
     * answer; on failure the text stays exactly as typed, so a dropped
     * connection costs a retry, not a rewrite.
     */
    fun submitContact() {
        val contact = _uiState.value.contact
        if (contact.isSending) return
        if (contact.body.isBlank()) {
            _uiState.update {
                it.copy(contact = it.contact.copy(message = "Write your message first.", messageIsError = true))
            }
            return
        }
        // The card's own precondition, said in the dialog rather than in the
        // card's message slot: a message is a row on a server, and with no
        // address there is no server to write to.
        if (_uiState.value.serverUrl.isBlank()) {
            _uiState.update {
                it.copy(
                    contact = it.contact.copy(
                        message = refusalSentence(Refusal.NO_SERVER),
                        messageIsError = true,
                    ),
                )
            }
            return
        }
        _uiState.update {
            it.copy(contact = it.contact.copy(isSending = true, message = null, messageIsError = false))
        }
        viewModelScope.launch {
            val sent = catalogRepository.submitContact(
                category = contact.category,
                subject = contact.subject.trim(),
                body = contact.body.trim(),
                accountHint = contact.email.trim().takeIf { it.isNotEmpty() },
            )
            _uiState.update {
                if (sent) {
                    it.copy(
                        contact = ContactUiState(
                            message = "Sent. If you left an email, we can reply to it.",
                            messageIsError = false,
                        ),
                    )
                } else {
                    it.copy(
                        contact = it.contact.copy(
                            isSending = false,
                            message = "Could not send. Check your connection and try again.",
                            messageIsError = true,
                        ),
                    )
                }
            }
        }
    }

    /**
     * "Sync now": both lists read, the library's missing favorites written, the pulled resume
     * points folded into the local mirror. The counts are the only thing reported, because the
     * app cannot name a server row — it has no title for one, and inventing a label from a
     * handle would be exactly the provenance leak this project forbids.
     */
    fun syncNow() {
        if (_uiState.value.account.isBusy) return
        _uiState.update { it.copy(account = it.account.copy(isBusy = true, message = null)) }
        viewModelScope.launch {
            val report = syncAccountRepository.syncNow()
            _uiState.update {
                it.copy(
                    account = it.account.copy(
                        isBusy = false,
                        lastReport = report,
                        message = syncSentence(report, paused = syncAccountRepository.isPaused),
                        messageIsError = !report.completed,
                    ),
                )
            }
        }
    }

    /** Sign out, revoking the key on the server too. Local rows and keeps are untouched. */
    fun signOut() {
        if (_uiState.value.account.isBusy) return
        _uiState.update { it.copy(account = it.account.copy(isBusy = true, message = null)) }
        viewModelScope.launch {
            syncAccountRepository.signOut()
            // A label goes with the account it described: sign-out is this device saying "not
            // yours any more", and the next person to open this card must not inherit a number.
            persistAccountLabel(null)
            _uiState.update {
                it.copy(
                    account = it.account.copy(
                        isBusy = false,
                        revealedKey = null,
                        quickInput = "",
                        message = "Signed out. The saved list and every kept file stayed on this device.",
                        messageIsError = false,
                    ),
                )
            }
        }
    }

    /** Shared shape of the two key-minting calls: busy, then one honest sentence either way. */
    private fun accountAction(block: suspend () -> AccountMutation) {
        if (_uiState.value.account.isBusy) return
        _uiState.update { it.copy(account = it.account.copy(isBusy = true, message = null)) }
        viewModelScope.launch {
            when (val outcome = block()) {
                is AccountMutation.SignedIn -> _uiState.update {
                    it.copy(
                        account = it.account.copy(
                            isBusy = false,
                            signedIn = true,
                            revealedKey = outcome.revealedKey,
                            quickInput = "",
                            message = if (outcome.revealedKey != null) {
                                revealWarning(_uiState.value.serverUrl)
                            } else {
                                "Signed in on this device."
                            },
                            messageIsError = false,
                        ),
                    )
                }
                is AccountMutation.Refused -> _uiState.update {
                    it.copy(
                        account = it.account.copy(
                            isBusy = false,
                            message = refusalSentence(outcome.reason),
                            messageIsError = true,
                        ),
                    )
                }
            }
        }
    }

    companion object {
        /**
         * The one sentence the app says about a key it just minted. Honest about the two things
         * a viewer can actually be harmed by: it is shown once, and the transport is whatever
         * the server they chose speaks — the shipped default is HTTPS, a server the viewer
         * points at over plain HTTP still sends the key in the clear — so the copy never
         * claims a protection the transport does not provide. [revealWarning] picks the
         * sentence for the server in use; [REVEAL_WARNING] is the plain-HTTP variant.
         */
        const val REVEAL_WARNING =
            "This is the only time the key is shown. Write it down now: this server speaks plain " +
                "HTTP, so the key travels in the clear, and anyone who reads it can open your " +
                "list. Losing it means starting a new list."

        const val REVEAL_WARNING_SECURED =
            "This is the only time the key is shown. Write it down now: anyone who reads it can " +
                "open your list. Losing it means starting a new list."

        /** The reveal warning for the server in use: the plain-HTTP sentence only when the
         * server actually speaks plain HTTP. */
        fun revealWarning(serverUrl: String): String =
            if (serverUrl.trim().startsWith("https", ignoreCase = true)) REVEAL_WARNING_SECURED
            else REVEAL_WARNING
    }
}

/** Our own sentence for a refusal. The server's `detail` text is never shown, by design. */
private fun refusalSentence(reason: Refusal): String = when (reason) {
    Refusal.NO_SERVER -> "No server is connected yet, so there is nothing to sign in to."
    Refusal.WEAK_KEY -> "Enter the 16-character sync key from the other device. A mobile number is not a key."
    Refusal.REJECTED -> "The server refused that key. Nothing was changed on this device."
    Refusal.THROTTLED -> "The server is asking this device to slow down. Syncing is paused until the app is restarted."
    Refusal.OFFLINE -> "The server could not be reached. Nothing was changed on this device."
    Refusal.SIGNED_OUT -> "That key is no longer valid here, so this device is signed out."
}

/**
 * Every sentence the trial and profile-link surfaces show, in one file, because these are the
 * words a viewer acts on and the words this repository can be audited against.
 *
 * Four rules they all obey, and the reason each one is a rule rather than a style:
 *  - **no security claim.** A server the viewer points at over plain HTTP has no TLS, so the
 *    PIN and the phone cross the wire in the clear — the shipped default is HTTPS, and the
 *    transport warning says which one is in use. Nothing here may say secure, encrypted,
 *    private, or "only you" about a plain-HTTP server;
 *  - **no lock claim.** The trial is opened by a device id this app makes up about itself
 *    (`accounts.py:240`: "client-reported … spoofable on a rooted phone"), so it is a gate, and no
 *    copy may call it verified, locked to a device, or proof of who somebody is;
 *  - **no invented entitlement.** The days come from the server's answer and the +1 comes from its
 *    `bonus_granted`, never from arithmetic this app did to a local clock;
 *  - **the escape hatch stays.** A wrongly-flagged deployment must remain escapable, so the form
 *    names the server it writes to and points at the row that changes it — the same precedent the
 *    maintenance notice set with "Use a different server".
 */
object AccountCardCopy {

    /** The line under the account heading while a trial has days left. */
    internal fun trialActive(daysLeft: Int): String =
        "Free VIP days are running on this install — " +
            if (daysLeft == 1) "1 day left." else "$daysLeft days left."

    /** The same line once the ledger says the trial is over. Names nothing that stops working. */
    internal const val TRIAL_ENDED = "The free days on this install have run out."

    /** What the trial actually is, said before a viewer could mistake it for protection. */
    internal const val TRIAL_HONESTY =
        "The server counts these days per install, not per person. It cannot tell one phone from " +
            "another and does not try to: the count is a gate on repeat free trials, not a lock on " +
            "your device and not proof of who you are."

    internal const val LINK_TITLE = "Link a phone number and a 4-digit PIN"
    internal const val LINK_BONUS = "+1 free VIP day, once per account"

    internal const val LINK_BUTTON = "Link and claim the day"

    /**
     * The transport warning. It is the sentence the whole modal exists to earn the right to show,
     * and it states what is true about the server in use rather than what a TLS deployment would
     * be: the plain-HTTP sentence only when the server actually speaks plain HTTP.
     * [linkTransportWarning] picks the sentence for the server in use;
     * [LINK_TRANSPORT_WARNING] is the plain-HTTP variant.
     */
    internal const val LINK_TRANSPORT_WARNING =
        "This server speaks plain HTTP, so the name, the number and the PIN you are about to type " +
            "travel across the network in the clear. Anyone able to read this traffic can read them. " +
            "Do not enter a PIN you also use somewhere else."

    internal const val LINK_TRANSPORT_WARNING_SECURED =
        "This server speaks HTTPS, so the name, the number and the PIN you are about to type " +
            "travel across the network under TLS. Do not enter a PIN you also use somewhere else."

    /** The transport warning for the server in use. */
    internal fun linkTransportWarning(serverUrl: String): String =
        if (serverUrl.trim().startsWith("https", ignoreCase = true)) LINK_TRANSPORT_WARNING_SECURED
        else LINK_TRANSPORT_WARNING

    /**
     * What the number is worth, in the same words the card above uses. This sentence used to say a
     * number was worth a key, because at the time it was: `q1-identity-fix` deleted that
     * derivation, and a card that still advertised it would send a reader hunting for a feature this
     * build does not have. See `tooling/PhoneCredentialGuardTest`.
     */
    internal const val LINK_PIN_MEANING =
        "The phone number is not a password and the PIN is not a second one. This app cannot turn a " +
            "number into a key, so linking adds nothing to how well your list is protected: the key " +
            "the server minted is the whole account. The PIN only lets you edit this profile later."

    internal const val LINK_ONCE_PER_ACCOUNT =
        "The extra day is granted once per account. Linking again, or fixing a typo, changes the " +
            "profile and adds nothing — so a second tap is safe and gets you nothing."

    /** The escape hatch, in the maintenance notice's own shape. */
    internal const val LINK_WHICH_SERVER =
        "This is written to the server whose address is in the Server card above. If that is not " +
            "the server you meant, change it there first — this form cannot move the profile for you."

    internal const val LINK_NAME_LABEL = "A name for this account"
    internal const val LINK_PHONE_LABEL = "Phone number"
    internal const val LINK_PIN_LABEL = "4 to 8 digit PIN"

    /** After a send. The two answers are different claims and are never merged into one. */
    internal fun linkSentence(bonusGranted: Boolean): String = if (bonusGranted) {
        "Linked. One free day was added to this account."
    } else {
        "Saved. No free day was added — this account already used its one."
    }

    internal fun linkRefusalSentence(reason: LinkRefusal): String = when (reason) {
        LinkRefusal.NOT_SIGNED_IN ->
            "This device is not signed in, so there is no account to link a profile to."
        LinkRefusal.WRONG_PIN ->
            "That PIN does not match the one on file, so the profile was not changed. Your sync " +
                "key still works and you are still signed in."
        LinkRefusal.DEAD_KEY ->
            "This server no longer recognises the key on this device, so it is signed out here. " +
                "Nothing was linked."
        LinkRefusal.THROTTLED ->
            "The server is asking this device to slow down, so the profile was not saved. Try again " +
                "after restarting the app."
        LinkRefusal.BAD_INPUT ->
            "That name, number or PIN is not something this server will store. Nothing was changed."
        LinkRefusal.OFFLINE ->
            "The server could not be reached, so nothing was linked. A number and PIN that were " +
                "already saved stay saved."
    }
}

/**
 * What one sync pass says about itself. Every branch is a count of rows, never a title: the
 * account payload carries no displayable metadata, so any sentence naming what was synced would
 * have to invent one.
 */
private fun syncSentence(report: SyncReport, paused: Boolean, signedIn: Boolean = false): String = when {
    paused -> if (signedIn) {
        "Signed in, but the server asked this device to slow down, so the first sync is paused until the app is restarted."
    } else {
        "The server asked this device to slow down, so syncing is paused until the app is restarted."
    }
    !report.completed -> if (signedIn) {
        "Signed in on this device, but the first sync did not finish. Nothing was lost: tap Sync now to try again."
    } else {
        "Sync did not finish. Nothing was lost: your saved list is still on this device."
    }
    else -> buildString {
        append(if (signedIn) "Signed in and synced. " else "Synced. ")
        append("${report.favoritesPushed} ${if (report.favoritesPushed == 1) "save" else "s"} sent up, ")
        append("${report.progressRowsPulled} resume ${if (report.progressRowsPulled == 1) "point" else "points"} pulled down.")
        if (report.favoritesPulled > 0) {
            append(" ${report.favoritesPulled} saved ${if (report.favoritesPulled == 1) "title" else "titles"} from your other device ${if (report.favoritesPulled == 1) "is" else "are"} now on this device too.")
        }
        if (report.favoritesUnknownHere > 0) {
            append(" ${report.favoritesUnknownHere} saved ${if (report.favoritesUnknownHere == 1) "title is" else "titles are"} on the server but not on this device — open them once and they will be yours here too.")
        }
        if (report.favoritesUnnamable > 0) {
            append(" ${report.favoritesUnnamable} local ${if (report.favoritesUnnamable == 1) "save has" else "saves have"} no server reference yet and stayed on this device.")
        }
    }
}

/**
 * The VIP Membership card's one-line summary, as a pure function so a test
 * can pin it. Session 114: the card used to say "Free plan" while the Account
 * card on the same screen said free VIP days were running — the two read two
 * different facts (a one-shot entitlement read vs the live trial countdown),
 * and the Membership line was the wrong one: a trial account IS a VIP account
 * on the server (vip_until = now + 3 days), so during the trial the viewer
 * is not on the free plan. The trial branch here is the backstop for the
 * window before the entitlement re-read lands; once it does, the VIP branch
 * says the same thing in its own words, and the two cards can never disagree.
 */
internal object MembershipCardCopy {

    /** One line: VIP, trial, payment pending, or the free plan — in that order. */
    fun summary(
        planIsVip: Boolean,
        planVipUntilMillis: Long?,
        planPaymentPending: Boolean,
        trialDays: Int?,
    ): String = when {
        planIsVip && (planVipUntilMillis ?: 0L) > 0L ->
            "VIP — confirmed through ${formatDate(planVipUntilMillis!!)}."
        planIsVip -> "VIP — active."
        planPaymentPending -> "Payment submitted — waiting for confirmation."
        (trialDays ?: 0) > 0 -> AccountCardCopy.trialActive(trialDays!!) +
            " 1080p and 4K play until the days end."
        else -> "Free plan — playback stays at 720p."
    }

    private fun formatDate(epochMs: Long): String {
        val date = java.util.Date(epochMs)
        return java.text.SimpleDateFormat("d MMM yyyy", java.util.Locale.getDefault()).format(date)
    }
}
