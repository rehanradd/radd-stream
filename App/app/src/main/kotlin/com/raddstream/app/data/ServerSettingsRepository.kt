package com.raddstream.app.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.doublePreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.floatPreferencesKey
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.raddstream.app.brand.Brand
import com.raddstream.app.network.models.AccountEntitlement
import com.raddstream.app.network.models.PanelDisclaimer
import com.raddstream.app.network.models.PanelTheme
import com.raddstream.app.player.LoginStreak
import com.raddstream.app.player.SubtitleColor
import com.raddstream.app.player.SubtitleUiSettings
import com.raddstream.app.player.loginStreakDay
import com.raddstream.app.player.nextLoginStreak
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.serverSettingsDataStore by preferencesDataStore(name = "radd_stream_settings")

@Singleton
class ServerSettingsRepository @Inject constructor(
    @ApplicationContext context: Context,
) {
    private val dataStore: DataStore<Preferences> = context.serverSettingsDataStore

    /**
     * The server this install talks to: the person's own choice if they made one,
     * otherwise the address the brand file ships. Returning the brand default here — rather
     * than special-casing "no saved value" in every caller — is what makes a fresh install
     * open on real content instead of on a setup form; an unbranded build still yields null
     * and the app still opens on Setup.
     */
    val serverUrl: Flow<String?> = dataStore.data.map { preferences ->
        preferences[SERVER_URL_KEY]?.takeIf { it.isNotBlank() }
            ?: Brand.defaultServerUrl.takeIf { it.isNotBlank() }
    }

    suspend fun saveServerUrl(url: String) {
        dataStore.edit { preferences -> preferences[SERVER_URL_KEY] = url }
    }

    /**
     * The user's audio level, 0..2 where 1.0 is untouched. Persisted because it is a
     * preference, not a gesture: a viewer who mixes their device once should not have to
     * mix it again after every episode. [DEFAULT_AUDIO_BOOST] is the anchor, so a fresh
     * install changes nothing on its own.
     */
    val audioBoostLevel: Flow<Float> = dataStore.data.map { preferences ->
        preferences[AUDIO_BOOST_LEVEL_KEY] ?: DEFAULT_AUDIO_BOOST
    }

    suspend fun saveAudioBoostLevel(level: Float) {
        val safe = if (level.isFinite()) level.coerceIn(0f, MAX_AUDIO_BOOST) else DEFAULT_AUDIO_BOOST
        dataStore.edit { preferences -> preferences[AUDIO_BOOST_LEVEL_KEY] = safe }
    }

    /**
     * Preferred audio language as the user spelled it (BCP-47 tag or an English name);
     * null means "never set" — the region's default applies (see
     * [com.raddstream.app.player.LanguageDefaults]), so a Hindi viewer is never left to
     * the player's device-locale guess. The literal "Player default" is the explicit
     * "leave it to the player" pick, stored as a word so it is never mistaken for never-set.
     */
    val preferredAudioLanguage: Flow<String?> = dataStore.data.map { preferences ->
        preferences[PREFERRED_AUDIO_LANGUAGE_KEY]
    }

    suspend fun savePreferredAudioLanguage(language: String?) {
        val clean = language?.trim()?.takeIf { it.isNotEmpty() }
        dataStore.edit { preferences ->
            if (clean == null) preferences.remove(PREFERRED_AUDIO_LANGUAGE_KEY)
            else preferences[PREFERRED_AUDIO_LANGUAGE_KEY] = clean
        }
    }

    /**
     * The viewer's regional-dub preference: [UserRegion.DESI_DUBS] (the default for this
     * catalog's audience), [UserRegion.EAST_ASIAN] or [UserRegion.INTERNATIONAL].
     *
     * It changes what the release selector leads with, not what the app will play: a
     * `desi_dubs` viewer sees Hindi/Urdu/dual-audio prints first, while every other region
     * keeps the server's quality ordering. An unreadable stored value is [UserRegion.DEFAULT].
     */
    val userRegion: Flow<String> = dataStore.data.map { preferences ->
        UserRegion.normalize(preferences[USER_REGION_KEY])
    }

    /**
     * Whether the viewer has actually been asked. [userRegion] always answers something
     * ([UserRegion.DEFAULT] for a viewer who never chose), so first-run routing cannot tell
     * "the default" from "nobody answered" without this.
     */
    val regionChoiceRecorded: Flow<Boolean> = dataStore.data.map { preferences ->
        preferences[REGION_RECORDED_KEY] == true
    }

    /**
     * The onboarding answer as ONE write: the region, the two language defaults it implies,
     * and the record that the question was asked.
     *
     * One `edit` matters here — four separate writes would let a process death between them
     * leave a viewer tagged `desi_dubs` while the player still prefers English, which is a
     * state no card on that screen described. A null language removes the preference rather
     * than storing a word for it, matching what Settings does when it picks its own default.
     */
    suspend fun saveRegionChoice(region: String, audioLanguage: String?, subtitleLanguage: String?) {
        val cleanAudio = audioLanguage?.trim()?.takeIf { it.isNotEmpty() }
        val cleanSubtitle = subtitleLanguage?.trim()?.takeIf { it.isNotEmpty() && it != SUBTITLE_OFF }
        dataStore.edit { preferences ->
            preferences[USER_REGION_KEY] = UserRegion.normalize(region)
            if (cleanAudio == null) preferences.remove(PREFERRED_AUDIO_LANGUAGE_KEY)
            else preferences[PREFERRED_AUDIO_LANGUAGE_KEY] = cleanAudio
            if (cleanSubtitle == null) preferences.remove(PREFERRED_SUBTITLE_LANGUAGE_KEY)
            else preferences[PREFERRED_SUBTITLE_LANGUAGE_KEY] = cleanSubtitle
            preferences[REGION_RECORDED_KEY] = true
        }
    }

    /**
     * The one opt-in that exposes anything: whether kept files may be read over the local network.
     * Persisted because it is a standing decision, not a session gesture — a viewer who turns it on
     * for an evening expects it still on until they turn it off, and the [com.raddstream.app.share.LanShareRunner]
     * reacts to this exact flow. Default is deliberately OFF: nothing binds a socket until the user
     * says so.
     */
    val lanShareEnabled: Flow<Boolean> = dataStore.data.map { preferences ->
        preferences[LAN_SHARE_ENABLED_KEY] ?: false
    }

    suspend fun saveLanShareEnabled(enabled: Boolean) {
        dataStore.edit { preferences -> preferences[LAN_SHARE_ENABLED_KEY] = enabled }
    }

    /**
     * The queries this install has searched, newest first, capped at
     * [SEARCH_RECENTS_MAX]. Persisted because a recents rail that empties on every restart
     * is not a history — it is a list of what this process happened to type. Stored as one
     * separator-joined string rather than a string set: recency is the whole point, and a
     * `Set` cannot preserve it.
     */
    val searchRecents: Flow<List<String>> = dataStore.data.map { preferences ->
        decodeSearchRecents(preferences[SEARCH_RECENTS_KEY])
    }

    suspend fun saveSearchRecents(recents: List<String>) {
        val normalized = normalizeSearchRecents(recents)
        dataStore.edit { preferences ->
            if (normalized.isEmpty()) preferences.remove(SEARCH_RECENTS_KEY)
            else preferences[SEARCH_RECENTS_KEY] = normalized.joinToString(SEARCH_RECENTS_SEPARATOR)
        }
    }

    /**
     * The sync account's key, or null when this install is signed out — which is the
     * default and stays the default until the viewer presses the button.
     *
     * The key lives in this app's own private DataStore file and nowhere else: not in a
     * database that gets exported, not in a share, never in a log. It is only as safe as
     * the device is, and it crosses the network as a plain header on a server that has no
     * TLS — both facts are stated to the viewer on the card that creates it, not hidden.
     */
    val syncKey: Flow<String?> = dataStore.data.map { preferences ->
        preferences[SYNC_KEY_KEY]?.takeIf { it.isNotBlank() }
    }

    suspend fun saveSyncKey(key: String?) {
        val clean = key?.trim()?.takeIf { it.isNotEmpty() }
        dataStore.edit { preferences ->
            if (clean == null) preferences.remove(SYNC_KEY_KEY)
            else preferences[SYNC_KEY_KEY] = clean
        }
    }

    // ── The anonymous three-day trial ────────────────────────────────────────────
    //
    // Two numbers, not one: the seconds the SERVER said were left, and the instant this device
    // heard it. Keeping the pair is what lets the countdown survive a wrong wall clock — see
    // [com.raddstream.app.sync.DeviceTrial.secondsRemaining]. Storing `trial_expires_at` alone
    // would make a phone whose clock is a day fast lose a day nobody took from it.

    /** The trial's remaining seconds at the moment they were read; `0` means no trial recorded. */
    val trialSecondsRemaining: Flow<Double> = dataStore.data.map { preferences ->
        preferences[TRIAL_SECONDS_REMAINING_KEY] ?: 0.0
    }

    /** When this device read that answer, in epoch milliseconds. */
    val trialRecordedAtMs: Flow<Long> = dataStore.data.map { preferences ->
        preferences[TRIAL_RECORDED_AT_MS_KEY] ?: 0L
    }

    /**
     * Record one trial answer. Both values move together, always: a countdown stored without its
     * anchor would count down from whenever the anchor happened to be written.
     */
    suspend fun saveDeviceTrial(secondsRemaining: Double, recordedAtMs: Long) {
        dataStore.edit { preferences ->
            preferences[TRIAL_SECONDS_REMAINING_KEY] = secondsRemaining
            preferences[TRIAL_RECORDED_AT_MS_KEY] = recordedAtMs
        }
    }

    /**
     * True while a key this app minted silently has never been shown to the viewer.
     *
     * The anonymous route hands the plaintext exactly once, at the launch when nobody was looking
     * at a screen. Without this flag the app would have created an account whose only credential
     * can never be read again — and the Account card's existing sentence ("the full key was shown
     * once, when it was created") would be a lie about a key that was never shown at all. Cleared
     * when the viewer presses "Done showing this key".
     */
    val trialKeyUnseen: Flow<Boolean> = dataStore.data.map { preferences ->
        preferences[TRIAL_KEY_UNSEEN_KEY] ?: false
    }

    suspend fun saveTrialKeyUnseen(unseen: Boolean) {
        dataStore.edit { preferences ->
            if (unseen) preferences[TRIAL_KEY_UNSEEN_KEY] = true
            else preferences.remove(TRIAL_KEY_UNSEEN_KEY)
        }
    }

    /**
     * The login streak (plan §5 step 19): consecutive days this device opened the app, counted
     * locally because no server route carries a per-user progress count. The last day is a local
     * epoch day (-1 means never opened); the count is how many in a row that is. The two move
     * together, always — a count stored without its anchor would survive a missed day.
     */
    val loginStreakLastDay: Flow<Long> = dataStore.data.map { preferences ->
        preferences[LOGIN_STREAK_LAST_DAY_KEY] ?: -1L
    }

    val loginStreakCount: Flow<Int> = dataStore.data.map { preferences ->
        preferences[LOGIN_STREAK_COUNT_KEY] ?: 0
    }

    /** Record that this device opened the app today. A second open the same day changes nothing. */
    suspend fun recordLoginDay(nowMs: Long = System.currentTimeMillis()) {
        val today = loginStreakDay(nowMs)
        val current = LoginStreak(
            lastDay = loginStreakLastDay.first().takeIf { it >= 0L },
            count = loginStreakCount.first(),
        )
        val next = nextLoginStreak(current, today)
        if (next == current) return
        dataStore.edit { preferences ->
            preferences[LOGIN_STREAK_LAST_DAY_KEY] = next.lastDay ?: today
            preferences[LOGIN_STREAK_COUNT_KEY] = next.count
        }
    }

    /**
     * The app major version the first-run gesture coach was last shown for, or null
     * when it has never been shown. The coach shows once per major version (plan §5
     * step 7): first open ever, and once again after a major version change — a
     * minor update must not re-teach gestures the viewer already knows. The stored
     * value is a major version ("1"), never the full version name, so 1.0.4 → 1.1.0
     * does not re-show. Written when the coach is dismissed or its 4 s timer ends.
     */
    val coachSeenVersion: Flow<String?> = dataStore.data.map { preferences ->
        preferences[COACH_SEEN_VERSION_KEY]
    }

    suspend fun saveCoachSeenVersion(majorVersion: String) {
        dataStore.edit { preferences ->
            preferences[COACH_SEEN_VERSION_KEY] = majorVersion
        }
    }

    /**
     * Player defaults (plan §5 step 10, P36): the viewer's own switches, not the
     * operator's. Autoplay-next defaults ON (plan D4, Netflix's default) — the switch
     * in Settings is the promise, and the player reads this flow before advancing.
     * Autoplay-previews defaults ON, matching the hero carousel's own default; it gates
     * the Home hero, never a video. Default quality defaults to "auto" — the same word
     * the ladder uses ([com.raddstream.app.player.LadderForScope.AUTO]) — and a fixed
     * band only applies when the viewer picked a rung themselves, never by guessing.
     */
    val autoplayNext: Flow<Boolean> = dataStore.data.map { preferences ->
        preferences[AUTOPLAY_NEXT_KEY] ?: true
    }

    suspend fun saveAutoplayNext(enabled: Boolean) {
        dataStore.edit { preferences ->
            preferences[AUTOPLAY_NEXT_KEY] = enabled
        }
    }

    val autoplayPreviews: Flow<Boolean> = dataStore.data.map { preferences ->
        preferences[AUTOPLAY_PREVIEWS_KEY] ?: true
    }

    suspend fun saveAutoplayPreviews(enabled: Boolean) {
        dataStore.edit { preferences ->
            preferences[AUTOPLAY_PREVIEWS_KEY] = enabled
        }
    }

    val defaultQuality: Flow<String> = dataStore.data.map { preferences ->
        preferences[DEFAULT_QUALITY_KEY]?.takeIf { it.isNotBlank() } ?: "auto"
    }

    suspend fun saveDefaultQuality(band: String) {
        dataStore.edit { preferences ->
            preferences[DEFAULT_QUALITY_KEY] = band
        }
    }

    /** Drop the trial state with the credential: a signed-out device has no clock to show. */
    suspend fun clearDeviceTrial() {
        dataStore.edit { preferences ->
            preferences.remove(TRIAL_SECONDS_REMAINING_KEY)
            preferences.remove(TRIAL_RECORDED_AT_MS_KEY)
            preferences.remove(TRIAL_KEY_UNSEEN_KEY)
        }
    }

    /**
     * What the viewer typed about themselves, shown on the account card and nowhere else.
     *
     * This is display data, deliberately kept beside the key it describes and kept separate from
     * it: it is never hashed, never sent, and read by nothing that decides whether a request is
     * allowed. A mobile number identifies a person to their friends; it authenticates nobody, and
     * an earlier build of this app treated it as if it did. See
     * [com.raddstream.app.sync.SyncContract.accountLabel] for the rule that turns typed text into
     * this value, and [com.raddstream.app.sync.SyncContract.quickLoginKey] for the fact that it is
     * not an input to it.
     */
    val accountLabel: Flow<String?> = dataStore.data.map { preferences ->
        preferences[ACCOUNT_LABEL_KEY]?.takeIf { it.isNotBlank() }
    }

    suspend fun saveAccountLabel(label: String?) {
        val clean = label?.trim()?.takeIf { it.isNotEmpty() }
        dataStore.edit { preferences ->
            if (clean == null) preferences.remove(ACCOUNT_LABEL_KEY)
            else preferences[ACCOUNT_LABEL_KEY] = clean
        }
    }

    // ── The operator's remote switches ──────────────────────────────────────────
    //
    // Mirrored into DataStore rather than sampled from the network in every screen: the last
    // body we actually received is what the app obeys, so a dead server on launch leaves the
    // previous answer in force instead of silently reopening a catalog under maintenance.
    // Every one defaults to the app's historical behaviour (no maintenance, feature on).

    /** True while the operator has put the whole catalog behind a maintenance notice. */
    val maintenanceMode: Flow<Boolean> = dataStore.data.map { preferences ->
        preferences[MAINTENANCE_MODE_KEY] ?: false
    }

    /** Operator switch for background downloads; on unless the server says otherwise. */
    val downloadsFeatureEnabled: Flow<Boolean> = dataStore.data.map { preferences ->
        preferences[FEATURE_DOWNLOADS_KEY] ?: true
    }

    /** Operator switch for LAN sharing; on unless the server says otherwise. */
    val sharingFeatureEnabled: Flow<Boolean> = dataStore.data.map { preferences ->
        preferences[FEATURE_SHARING_KEY] ?: true
    }

    /** Operator switch for catalog search; on unless the server says otherwise. */
    val searchFeatureEnabled: Flow<Boolean> = dataStore.data.map { preferences ->
        preferences[FEATURE_SEARCH_KEY] ?: true
    }

    /**
     * Operator switch for Ghost/cinema mode; on unless the server says otherwise. It is the
     * only one of these that hides chrome rather than a feature, and an operator who turns it
     * off is saying this build must always show its controls — so the player obeys it even for
     * a viewer whose own saved choice was cinema.
     */
    val pureCinemaFeatureEnabled: Flow<Boolean> = dataStore.data.map { preferences ->
        preferences[FEATURE_PURE_CINEMA_KEY] ?: true
    }

    /**
     * The four feature switches as one snapshot, for anything that has to hide or allow several
     * entry points at once. See [RemoteFeatures] for why the board travels as one object.
     */
    val remoteFeatures: Flow<RemoteFeatures> = combine(
        downloadsFeatureEnabled,
        sharingFeatureEnabled,
        searchFeatureEnabled,
        pureCinemaFeatureEnabled,
    ) { downloads, sharing, search, pureCinema ->
        RemoteFeatures(
            downloads = downloads,
            sharing = sharing,
            search = search,
            pureCinema = pureCinema,
        )
    }

    /**
     * Whether the operator has chosen to charge VIP for 1080p/4K. Off unless the server says
     * on — the inverse of the feature switches above, because this one takes content away rather
     * than offering a feature, and a deployment that never set it must not go dark by default.
     */
    val qualityGateEnabled: Flow<Boolean> = dataStore.data.map { preferences ->
        preferences[FEATURE_QUALITY_GATE_KEY] ?: false
    }

    /**
     * Operator switch for the three capped ad surfaces. Off unless the server says on, for the
     * same reason [qualityGateEnabled] is: an ad is not a feature a viewer already had, so a
     * deployment that never published the key must keep showing them nothing rather than
     * discovering a surface this app only knows how to cap.
     *
     * [com.raddstream.app.player.AdCadenceGovernor] reads this on every ask, which is what makes
     * flipping it off take effect inside the current window instead of after it expires.
     */
    val adsEnabled: Flow<Boolean> = dataStore.data.map { preferences ->
        preferences[FEATURE_ADS_KEY] ?: false
    }

    /**
     * Record one received remote-config body. A single write keeps the switches from a
     * torn refresh; the caller ([com.raddstream.app.data.RemoteConfigWatcher]) writes only
     * after a successful, fully decoded response.
     */
    suspend fun saveRemoteFlags(
        maintenanceMode: Boolean,
        downloadsEnabled: Boolean,
        sharingEnabled: Boolean,
        searchEnabled: Boolean,
        pureCinemaEnabled: Boolean,
        qualityGateEnabled: Boolean,
        adsEnabled: Boolean,
    ) {
        dataStore.edit { preferences ->
            preferences[MAINTENANCE_MODE_KEY] = maintenanceMode
            preferences[FEATURE_DOWNLOADS_KEY] = downloadsEnabled
            preferences[FEATURE_SHARING_KEY] = sharingEnabled
            preferences[FEATURE_SEARCH_KEY] = searchEnabled
            preferences[FEATURE_PURE_CINEMA_KEY] = pureCinemaEnabled
            preferences[FEATURE_QUALITY_GATE_KEY] = qualityGateEnabled
            preferences[FEATURE_ADS_KEY] = adsEnabled
        }
    }

    /**
     * The operator's theme, mirrored the same way as the remote switches above:
     * the last body we actually received is what the app paints, so a dead
     * server on launch leaves the previous theme in force. Every field
     * defaults to the app this build has always shipped (dark, brand accent,
     * hero on, 6 slides).
     */
    val themeSettings: Flow<PanelTheme> = dataStore.data.map { preferences ->
        PanelTheme(
            mode = preferences[THEME_MODE_KEY] ?: "dark",
            accent = preferences[THEME_ACCENT_KEY] ?: "",
            dynamicColor = preferences[THEME_DYNAMIC_COLOR_KEY] ?: false,
            heroAutoplay = preferences[THEME_HERO_AUTOPLAY_KEY] ?: true,
            heroIntervalS = preferences[THEME_HERO_INTERVAL_S_KEY] ?: 5,
            heroMax = preferences[THEME_HERO_MAX_KEY] ?: 6,
        )
    }

    /** Record one received theme block, from the same successful poll as [saveRemoteFlags]. */
    suspend fun saveTheme(theme: PanelTheme) {
        dataStore.edit { preferences ->
            preferences[THEME_MODE_KEY] = theme.mode
            preferences[THEME_ACCENT_KEY] = theme.accent
            preferences[THEME_DYNAMIC_COLOR_KEY] = theme.dynamicColor
            preferences[THEME_HERO_AUTOPLAY_KEY] = theme.heroAutoplay
            preferences[THEME_HERO_INTERVAL_S_KEY] = theme.heroIntervalS
            preferences[THEME_HERO_MAX_KEY] = theme.heroMax
        }
    }

    /**
     * The operator's tab list, mirrored the same way as the theme above: the
     * last body we actually received is what the bar shows, so a dead server
     * on launch leaves the previous order in force. Empty means "never
     * received" — the bar falls back to its own four (see
     * [com.raddstream.app.ui.navigation.PanelTabs]).
     */
    val panelTabs: Flow<List<String>> = dataStore.data.map { preferences ->
        preferences[PANEL_TABS_KEY]
            ?.split(",")
            ?.map { it.trim() }
            ?.filter { it.isNotEmpty() }
            ?: emptyList()
    }

    /** Record one received tab list, from the same successful poll as [saveTheme]. */
    suspend fun saveTabs(tabs: List<String>) {
        dataStore.edit { preferences ->
            preferences[PANEL_TABS_KEY] = tabs.joinToString(",")
        }
    }

    /**
     * The operator's disclaimer, mirrored the same way as the theme and tabs:
     * the last body actually received is what the app shows, so a dead
     * server on launch leaves the previous disclaimer in force. Empty text
     * means "nothing published" — the dialog never opens on an empty text,
     * and a retraction (the operator clearing the text) clears it here too.
     * The version is what the app compares against what it has already
     * shown; a negative version is a typo and reads as 0.
     */
    val disclaimer: Flow<PanelDisclaimer> = dataStore.data.map { preferences ->
        PanelDisclaimer(
            text = preferences[DISCLAIMER_TEXT_KEY] ?: "",
            version = (preferences[DISCLAIMER_VERSION_KEY] ?: 0).coerceAtLeast(0),
        )
    }

    /** Record one received disclaimer, from the same successful poll as [saveTabs]. */
    suspend fun saveDisclaimer(disclaimer: PanelDisclaimer) {
        dataStore.edit { preferences ->
            preferences[DISCLAIMER_TEXT_KEY] = disclaimer.text
            preferences[DISCLAIMER_VERSION_KEY] = disclaimer.version.coerceAtLeast(0)
        }
    }

    /**
     * The disclaimer version this install has already accepted. -1 means
     * "never shown one": a published version 0 still has to be shown once,
     * because 0 is a real version the operator may have published, not the
     * absence of one.
     */
    val disclaimerSeenVersion: Flow<Int> = dataStore.data.map { preferences ->
        preferences[DISCLAIMER_SEEN_VERSION_KEY] ?: -1
    }

    /** Record that the viewer read (and accepted) this disclaimer version. */
    suspend fun acceptDisclaimer(version: Int) {
        dataStore.edit { preferences ->
            preferences[DISCLAIMER_SEEN_VERSION_KEY] = version.coerceAtLeast(0)
        }
    }

    /**
     * The best picture a free viewer may play, as the operator set it:
     * "480p" or "720p". Anything else the server sent — a typo, an older
     * deployment — reads as the shipped "720p", never a stricter cap the
     * operator did not ask for.
     */
    val freeQualityCap: Flow<String> = dataStore.data.map { preferences ->
        (preferences[FREE_QUALITY_CAP_KEY] ?: "720p")
            .takeIf { it == "480p" || it == "720p" } ?: "720p"
    }

    /** Record one received free quality cap, from the same successful poll as [saveTabs]. */
    suspend fun saveFreeQualityCap(cap: String) {
        dataStore.edit { preferences ->
            preferences[FREE_QUALITY_CAP_KEY] =
                cap.takeIf { it == "480p" || it == "720p" } ?: "720p"
        }
    }

    /**
     * The last entitlement the ledger confirmed, mirrored here so a restart does not have to
     * wait for a round trip before it knows what this account may play. It is a CACHE of the
     * server's answer, never a second authority: a signed-out device clears it, and every
     * successful `GET /api/v2/account/entitlement` overwrites it.
     */
    val storedEntitlement: Flow<AccountEntitlement?> = dataStore.data.map { preferences ->
        val vip = preferences[VIP_ACTIVE_KEY] ?: return@map null
        AccountEntitlement(
            vip = vip,
            vipUntil = preferences[VIP_UNTIL_KEY] ?: 0.0,
            pending = preferences[VIP_PENDING_CLAIM_KEY] ?: false,
        )
    }

    suspend fun saveEntitlement(entitlement: AccountEntitlement) {
        dataStore.edit { preferences ->
            preferences[VIP_ACTIVE_KEY] = entitlement.vip
            preferences[VIP_UNTIL_KEY] = entitlement.vipUntil
            preferences[VIP_PENDING_CLAIM_KEY] = entitlement.pending
        }
    }

    suspend fun clearStoredEntitlement() {
        dataStore.edit { preferences ->
            preferences.remove(VIP_ACTIVE_KEY)
            preferences.remove(VIP_UNTIL_KEY)
            preferences.remove(VIP_PENDING_CLAIM_KEY)
        }
    }

    // ── The playback & display preferences ──────────────────────────────────────
    //
    // All five are stored here rather than left in a ViewModel because a preference the
    // app forgets on process death is a control that lies: the chip row shows the tap for
    // the rest of the session and then silently reverts. Each default is the value the
    // consumer would have chosen anyway, so an install that never opens this screen
    // behaves exactly as it did before these keys existed.

    /** [com.raddstream.app.viewmodel.ImageQuality] enum name; `AUTO` unless told otherwise. */
    val imageQualityChoice: Flow<String> = dataStore.data.map { preferences ->
        preferences[IMAGE_QUALITY_KEY] ?: DEFAULT_IMAGE_QUALITY
    }

    suspend fun saveImageQualityChoice(name: String) {
        dataStore.edit { preferences -> preferences[IMAGE_QUALITY_KEY] = name }
    }

    /** May images and kept items be fetched while on metered mobile data? */
    val mobileDataAllowed: Flow<Boolean> = dataStore.data.map { preferences ->
        preferences[MOBILE_DATA_KEY] ?: false
    }

    suspend fun saveMobileDataAllowed(enabled: Boolean) {
        dataStore.edit { preferences -> preferences[MOBILE_DATA_KEY] = enabled }
    }

    /**
     * Data Saver: on mobile data, titles start at 480p and the server is
     * asked for its data-saving copy. On by default — mobile data is the
     * expensive network for most viewers here, and the switch is one tap
     * away in Settings for anyone who wants full quality on the go.
     */
    val dataSaver: Flow<Boolean> = dataStore.data.map { preferences ->
        preferences[DATA_SAVER_KEY] ?: true
    }

    suspend fun saveDataSaver(enabled: Boolean) {
        dataStore.edit { preferences -> preferences[DATA_SAVER_KEY] = enabled }
    }

    /**
     * Downloads only on Wi-Fi. On by default — a kept title is hundreds of
     * megabytes, and starting one on mobile data by accident is the expensive
     * mistake this exists to prevent. The viewer can switch it off in
     * Settings; the download then starts on whatever network is up.
     */
    val wifiOnlyDownloads: Flow<Boolean> = dataStore.data.map { preferences ->
        preferences[WIFI_ONLY_DOWNLOADS_KEY] ?: true
    }

    suspend fun saveWifiOnlyDownloads(enabled: Boolean) {
        dataStore.edit { preferences -> preferences[WIFI_ONLY_DOWNLOADS_KEY] = enabled }
    }

    /**
     * Delete a finished movie's download on its own, to free the space. On
     * by default; the viewer can switch it off in Settings, and a series
     * keep is never touched — one watched episode does not mean the season
     * file is done. The notice names what was deleted.
     */
    val autoDeleteWatched: Flow<Boolean> = dataStore.data.map { preferences ->
        preferences[AUTO_DELETE_WATCHED_KEY] ?: true
    }

    suspend fun saveAutoDeleteWatched(enabled: Boolean) {
        dataStore.edit { preferences -> preferences[AUTO_DELETE_WATCHED_KEY] = enabled }
    }

    /** How long an offline keep survives before the sweeper deletes it: 3 or 6 hours. */
    val keepTtlHours: Flow<Int> = dataStore.data.map { preferences ->
        preferences[KEEP_TTL_KEY]?.takeIf { it == KEEP_TTL_HOURS_3 || it == KEEP_TTL_HOURS_6 }
            ?: DEFAULT_KEEP_TTL_HOURS
    }

    suspend fun saveKeepTtlHours(hours: Int) {
        val safe = if (hours == KEEP_TTL_HOURS_6) KEEP_TTL_HOURS_6 else KEEP_TTL_HOURS_3
        dataStore.edit { preferences -> preferences[KEEP_TTL_KEY] = safe }
    }

    /**
     * Preferred subtitle language as the user named it; null means "never set" (the region's
     * default applies — see [com.raddstream.app.player.LanguageDefaults]), and the literal
     * [SUBTITLE_OFF] means off. Off used to be stored as a removal, which made it
     * indistinguishable from never-set; an explicit Off stored as nothing would come back as
     * the region's English on the next playback.
     */
    val preferredSubtitleLanguage: Flow<String?> = dataStore.data.map { preferences ->
        preferences[PREFERRED_SUBTITLE_LANGUAGE_KEY]
    }

    suspend fun savePreferredSubtitleLanguage(language: String?) {
        val clean = language?.trim()?.takeIf { it.isNotEmpty() }
        dataStore.edit { preferences ->
            if (clean == null) preferences.remove(PREFERRED_SUBTITLE_LANGUAGE_KEY)
            else preferences[PREFERRED_SUBTITLE_LANGUAGE_KEY] = clean
        }
    }

    /**
     * How subtitles look: size, vertical seat, weight, plate, colour — one snapshot of five
     * keys. Read as one value so a style cannot land on the player half-applied, and so the
     * sheet's five controls and the two render paths always agree on what the viewer asked for.
     *
     * [com.raddstream.app.player.SubtitleUiSettings.delayMs] is deliberately NOT stored. The
     * sync sheet promises to hold the offset "for the rest of this viewing", and a delay is a
     * correction to one file's muxing, not a taste: carrying yesterday's +4.2s onto the next
     * title would make subtitles wrong on a file that never needed it. The player re-applies
     * its live offset through `withDelay` whenever this flow answers.
     */
    val subtitleStyle: Flow<SubtitleUiSettings> = dataStore.data.map { preferences ->
        subtitleStyleOf(
            sizePercent = preferences[SUBTITLE_SIZE_KEY],
            bottomFraction = preferences[SUBTITLE_BOTTOM_FRACTION_KEY],
            bold = preferences[SUBTITLE_BOLD_KEY],
            textBackground = preferences[SUBTITLE_BACKGROUND_KEY],
            colour = preferences[SUBTITLE_COLOUR_KEY],
        )
    }

    /** Remember the look. Clamped on the way in, so the store never holds an unusable style. */
    suspend fun saveSubtitleStyle(style: SubtitleUiSettings) {
        val safe = style.clamped()
        dataStore.edit { preferences ->
            preferences[SUBTITLE_SIZE_KEY] = safe.sizePercent
            preferences[SUBTITLE_BOTTOM_FRACTION_KEY] = safe.bottomFraction
            preferences[SUBTITLE_BOLD_KEY] = safe.bold
            preferences[SUBTITLE_BACKGROUND_KEY] = safe.textBackground
            preferences[SUBTITLE_COLOUR_KEY] = safe.colour.wireName
        }
    }

    /** Dynamic colour from the wallpaper: OFF, because the brand scheme is the design. */
    val dynamicColorEnabled: Flow<Boolean> = dataStore.data.map { preferences ->
        preferences[DYNAMIC_COLOR_KEY] ?: false
    }

    suspend fun saveDynamicColorEnabled(enabled: Boolean) {
        dataStore.edit { preferences -> preferences[DYNAMIC_COLOR_KEY] = enabled }
    }

    /**
     * The player's chrome mode: [com.raddstream.app.player.ViewMode] enum name, `STANDARD`
     * unless the viewer opted into Ghost. Persisted for the same reason as the other rows
     * above — a viewer who watches in a chrome-less frame every night should not have to
     * re-enter it for every episode, and a player that forgets it is a control that lies.
     * An unreadable stored name is [DEFAULT_VIEW_MODE], never a guess.
     */
    val viewModeChoice: Flow<String> = dataStore.data.map { preferences ->
        preferences[VIEW_MODE_KEY]?.takeIf { it == VIEW_MODE_STANDARD || it == VIEW_MODE_PURE_CINEMA }
            ?: DEFAULT_VIEW_MODE
    }

    suspend fun saveViewModeChoice(name: String) {
        val safe = if (name == VIEW_MODE_PURE_CINEMA) VIEW_MODE_PURE_CINEMA else VIEW_MODE_STANDARD
        dataStore.edit { preferences -> preferences[VIEW_MODE_KEY] = safe }
    }

    /**
     * The VIP payment reference the viewer entered, or null when nothing is awaiting
     * verification. This deployment has no endpoint that receives a transaction id, so
     * the reference is kept HERE — on the device that typed it — and the screen says
     * exactly that. Storing it is not activation: nothing in this app treats a pending
     * reference as a paid account.
     */
    val vipPendingSubmission: Flow<VipPendingSubmission?> = dataStore.data.map { preferences ->
        val transactionId = preferences[VIP_PENDING_TID_KEY]?.takeIf { it.isNotBlank() }
            ?: return@map null
        VipPendingSubmission(
            transactionId = transactionId,
            plan = preferences[VIP_PENDING_PLAN_KEY].orEmpty(),
            method = preferences[VIP_PENDING_METHOD_KEY].orEmpty(),
            amountPkr = preferences[VIP_PENDING_AMOUNT_KEY] ?: 0,
            submittedAt = preferences[VIP_PENDING_SUBMITTED_AT_KEY] ?: 0L,
        )
    }

    suspend fun saveVipPendingSubmission(submission: VipPendingSubmission) {
        val tid = submission.transactionId.trim()
        if (tid.isEmpty()) return
        dataStore.edit { preferences ->
            preferences[VIP_PENDING_TID_KEY] = tid
            preferences[VIP_PENDING_PLAN_KEY] = submission.plan
            preferences[VIP_PENDING_METHOD_KEY] = submission.method
            preferences[VIP_PENDING_AMOUNT_KEY] = submission.amountPkr
            preferences[VIP_PENDING_SUBMITTED_AT_KEY] = submission.submittedAt
        }
    }

    suspend fun clearVipPendingSubmission() {
        dataStore.edit { preferences ->
            preferences.remove(VIP_PENDING_TID_KEY)
            preferences.remove(VIP_PENDING_PLAN_KEY)
            preferences.remove(VIP_PENDING_METHOD_KEY)
            preferences.remove(VIP_PENDING_AMOUNT_KEY)
            preferences.remove(VIP_PENDING_SUBMITTED_AT_KEY)
        }
    }

    /**
     * When the current rewarded-ad VIP pass lapses, in epoch milliseconds; `0` means
     * no pass has ever been granted. Stored here rather than in a ViewModel because a
     * reward the app forgets on process death would be a reward the viewer did not get.
     */
    val rewardedVipExpiresAt: Flow<Long> = dataStore.data.map { preferences ->
        preferences[REWARDED_VIP_EXPIRES_AT_KEY] ?: 0L
    }

    /**
     * Grant [hours] of VIP for watching a rewarded ad.
     *
     * A second grant while a pass is still live extends it from its current expiry
     * instead of truncating the remaining time. The value is a wall-clock instant so
     * it survives a reboot; it is private app state, not a server entitlement, and the
     * screen says so rather than implying a paid membership.
     */
    suspend fun grantRewardedVip(hours: Int = DEFAULT_REWARDED_VIP_HOURS) {
        val safeHours = hours.coerceIn(1, MAX_REWARDED_VIP_HOURS)
        val addedMs = safeHours * 60L * 60_000L
        dataStore.edit { preferences ->
            val now = System.currentTimeMillis()
            val current = preferences[REWARDED_VIP_EXPIRES_AT_KEY] ?: 0L
            preferences[REWARDED_VIP_EXPIRES_AT_KEY] = maxOf(now, current) + addedMs
        }
    }

    /** Whether a rewarded-ad pass is live right now. Suspends while DataStore loads. */
    suspend fun isRewardedVipActive(): Boolean =
        rewardedVipExpiresAt.first() > System.currentTimeMillis()

    companion object {
        private val SERVER_URL_KEY = stringPreferencesKey("server_url")
        private val AUDIO_BOOST_LEVEL_KEY = floatPreferencesKey("audio_boost_level")
        private val PREFERRED_AUDIO_LANGUAGE_KEY = stringPreferencesKey("preferred_audio_language")
        private val USER_REGION_KEY = stringPreferencesKey("user_region")
        private val REGION_RECORDED_KEY = booleanPreferencesKey("region_choice_recorded")
        private val LAN_SHARE_ENABLED_KEY = booleanPreferencesKey("lan_share_enabled")
        private val MAINTENANCE_MODE_KEY = booleanPreferencesKey("maintenance_mode")
        private val FEATURE_DOWNLOADS_KEY = booleanPreferencesKey("feature_downloads")
        private val FEATURE_SHARING_KEY = booleanPreferencesKey("feature_sharing")
        private val FEATURE_SEARCH_KEY = booleanPreferencesKey("feature_search")
        private val FEATURE_PURE_CINEMA_KEY = booleanPreferencesKey("feature_pure_cinema")
        private val FEATURE_QUALITY_GATE_KEY = booleanPreferencesKey("feature_quality_gate")
        private val FEATURE_ADS_KEY = booleanPreferencesKey("feature_ads")
        private val THEME_MODE_KEY = stringPreferencesKey("theme_mode")
        private val PANEL_TABS_KEY = stringPreferencesKey("panel_tabs")
        private val DISCLAIMER_TEXT_KEY = stringPreferencesKey("disclaimer_text")
        private val DISCLAIMER_VERSION_KEY = intPreferencesKey("disclaimer_version")
        private val DISCLAIMER_SEEN_VERSION_KEY = intPreferencesKey("disclaimer_seen_version")
        private val FREE_QUALITY_CAP_KEY = stringPreferencesKey("free_quality_cap")
        private val THEME_ACCENT_KEY = stringPreferencesKey("theme_accent")
        private val THEME_DYNAMIC_COLOR_KEY = booleanPreferencesKey("theme_dynamic_color")
        private val THEME_HERO_AUTOPLAY_KEY = booleanPreferencesKey("theme_hero_autoplay")
        private val THEME_HERO_INTERVAL_S_KEY = intPreferencesKey("theme_hero_interval_s")
        private val THEME_HERO_MAX_KEY = intPreferencesKey("theme_hero_max")
        private val VIP_ACTIVE_KEY = booleanPreferencesKey("vip_active")
        private val VIP_UNTIL_KEY = doublePreferencesKey("vip_until")
        private val VIP_PENDING_CLAIM_KEY = booleanPreferencesKey("vip_pending_claim")
        private val SYNC_KEY_KEY = stringPreferencesKey("sync_key")
        private val TRIAL_SECONDS_REMAINING_KEY = doublePreferencesKey("trial_seconds_remaining")
        private val TRIAL_RECORDED_AT_MS_KEY = longPreferencesKey("trial_recorded_at_ms")
        private val TRIAL_KEY_UNSEEN_KEY = booleanPreferencesKey("trial_key_unseen")
        private val LOGIN_STREAK_LAST_DAY_KEY = longPreferencesKey("login_streak_last_day")
        private val LOGIN_STREAK_COUNT_KEY = intPreferencesKey("login_streak_count")
        private val COACH_SEEN_VERSION_KEY = stringPreferencesKey("player_coach_seen_version")
        private val AUTOPLAY_NEXT_KEY = booleanPreferencesKey("player_autoplay_next")
        private val AUTOPLAY_PREVIEWS_KEY = booleanPreferencesKey("player_autoplay_previews")
        private val DEFAULT_QUALITY_KEY = stringPreferencesKey("player_default_quality")
        private val ACCOUNT_LABEL_KEY = stringPreferencesKey("account_label")
        private val SEARCH_RECENTS_KEY = stringPreferencesKey("search_recents")
        private val IMAGE_QUALITY_KEY = stringPreferencesKey("image_quality")
        private val MOBILE_DATA_KEY = booleanPreferencesKey("mobile_data_allowed")
        private val DATA_SAVER_KEY = booleanPreferencesKey("data_saver")
        private val WIFI_ONLY_DOWNLOADS_KEY = booleanPreferencesKey("wifi_only_downloads")
        private val AUTO_DELETE_WATCHED_KEY = booleanPreferencesKey("auto_delete_watched")
        private val KEEP_TTL_KEY = intPreferencesKey("keep_ttl_hours")
        private val PREFERRED_SUBTITLE_LANGUAGE_KEY = stringPreferencesKey("preferred_subtitle_language")
        private val SUBTITLE_SIZE_KEY = intPreferencesKey("subtitle_size_percent")
        private val SUBTITLE_BOTTOM_FRACTION_KEY = floatPreferencesKey("subtitle_bottom_fraction")
        private val SUBTITLE_BOLD_KEY = booleanPreferencesKey("subtitle_bold")
        private val SUBTITLE_BACKGROUND_KEY = booleanPreferencesKey("subtitle_text_background")
        private val SUBTITLE_COLOUR_KEY = stringPreferencesKey("subtitle_colour")
        private val DYNAMIC_COLOR_KEY = booleanPreferencesKey("dynamic_color")
        private val VIEW_MODE_KEY = stringPreferencesKey("view_mode")
        private val VIP_PENDING_TID_KEY = stringPreferencesKey("vip_pending_tid")
        private val VIP_PENDING_PLAN_KEY = stringPreferencesKey("vip_pending_plan")
        private val VIP_PENDING_METHOD_KEY = stringPreferencesKey("vip_pending_method")
        private val VIP_PENDING_AMOUNT_KEY = intPreferencesKey("vip_pending_amount")
        private val VIP_PENDING_SUBMITTED_AT_KEY = longPreferencesKey("vip_pending_submitted_at")
        private val REWARDED_VIP_EXPIRES_AT_KEY = longPreferencesKey("rewarded_vip_expires_at")

        /** AudioBoost's own anchor and ceiling, restated here as the storage contract. */
        const val DEFAULT_AUDIO_BOOST = 1f
        const val MAX_AUDIO_BOOST = 2f

        /** The storage contract for the rows above; the UI types map onto these. */
        const val DEFAULT_IMAGE_QUALITY = "AUTO"
        const val KEEP_TTL_HOURS_3 = 3
        const val KEEP_TTL_HOURS_6 = 6
        const val DEFAULT_KEEP_TTL_HOURS = KEEP_TTL_HOURS_3
        const val SUBTITLE_OFF = "Off"

        /** The rewarded pass the screen offers: four hours, and no single grant over a day. */
        const val DEFAULT_REWARDED_VIP_HOURS = 4
        const val MAX_REWARDED_VIP_HOURS = 24

        /** [com.raddstream.app.player.ViewMode] enum names — the storage contract for the row above. */
        const val VIEW_MODE_STANDARD = "STANDARD"
        const val VIEW_MODE_PURE_CINEMA = "PURE_CINEMA"
        const val DEFAULT_VIEW_MODE = VIEW_MODE_STANDARD
    }
}

/**
 * One transaction reference awaiting the operator's confirmation, as it is stored on the
 * device. [plan] is the storage name of the chosen VIP plan and [amountPkr] is what the
 * screen quoted when the reference was entered — kept together so a later price change
 * cannot silently restate what the viewer says they paid. [method] is what makes the draft
 * resubmittable: each payment method has its own reference shape on the server, so a draft
 * that forgot which one it was filed under could only ever be refused.
 */
data class VipPendingSubmission(
    val transactionId: String,
    val plan: String,
    val method: String,
    val amountPkr: Int,
    val submittedAt: Long,
)

/** How many searches the rail remembers; also the cap enforced on every write. */
internal const val SEARCH_RECENTS_MAX = 20

/**
 * The field separator for the stored recents string. U+001F (unit separator) is not
 * typeable on any keyboard and is stripped from every query before writing, so a stored
 * list always round-trips to exactly the queries that produced it.
 */
private const val SEARCH_RECENTS_SEPARATOR = "\u001F"

/** Trim, drop blanks, strip the separator, dedupe (newest wins), and cap the list. */
internal fun normalizeSearchRecents(values: List<String>): List<String> =
    values.asSequence()
        .map { raw -> raw.filterNot { it == SEARCH_RECENTS_SEPARATOR[0] }.trim() }
        .filter { it.isNotEmpty() }
        .distinct()
        .take(SEARCH_RECENTS_MAX)
        .toList()

internal fun decodeSearchRecents(raw: String?): List<String> {
    if (raw.isNullOrEmpty()) return emptyList()
    return normalizeSearchRecents(raw.split(SEARCH_RECENTS_SEPARATOR))
}

/** The look a first install ships, and the answer for every key this build never wrote. */
internal val DEFAULT_SUBTITLE_STYLE = SubtitleUiSettings()

/**
 * The stored subtitle keys as one style. Every absent, unreadable, or out-of-range value falls
 * back to [DEFAULT_SUBTITLE_STYLE] rather than to a guess, and the result is clamped, so a
 * number an older build could have written still arrives as something both render paths accept.
 */
internal fun subtitleStyleOf(
    sizePercent: Int?,
    bottomFraction: Float?,
    bold: Boolean?,
    textBackground: Boolean?,
    colour: String?,
): SubtitleUiSettings = SubtitleUiSettings(
    sizePercent = sizePercent ?: DEFAULT_SUBTITLE_STYLE.sizePercent,
    bottomFraction = bottomFraction?.takeIf { it.isFinite() } ?: DEFAULT_SUBTITLE_STYLE.bottomFraction,
    bold = bold ?: DEFAULT_SUBTITLE_STYLE.bold,
    textBackground = textBackground ?: DEFAULT_SUBTITLE_STYLE.textBackground,
    colour = SubtitleColor.fromWire(colour),
).clamped()
