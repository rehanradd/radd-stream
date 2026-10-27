package com.raddstream.app.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.floatPreferencesKey
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.raddstream.app.brand.Brand
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.Flow
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
     * null means "the player's own choice", which is the honest default — this catalog is
     * dual audio and guessing a language for someone who never picked one is how a Hindi
     * viewer ends up with an English dub.
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

    /** How long an offline keep survives before the sweeper deletes it: 3 or 6 hours. */
    val keepTtlHours: Flow<Int> = dataStore.data.map { preferences ->
        preferences[KEEP_TTL_KEY]?.takeIf { it == KEEP_TTL_HOURS_3 || it == KEEP_TTL_HOURS_6 }
            ?: DEFAULT_KEEP_TTL_HOURS
    }

    suspend fun saveKeepTtlHours(hours: Int) {
        val safe = if (hours == KEEP_TTL_HOURS_6) KEEP_TTL_HOURS_6 else KEEP_TTL_HOURS_3
        dataStore.edit { preferences -> preferences[KEEP_TTL_KEY] = safe }
    }

    /** Preferred subtitle language as the user named it; null means "leave it off". */
    val preferredSubtitleLanguage: Flow<String?> = dataStore.data.map { preferences ->
        preferences[PREFERRED_SUBTITLE_LANGUAGE_KEY]
    }

    suspend fun savePreferredSubtitleLanguage(language: String?) {
        val clean = language?.trim()?.takeIf { it.isNotEmpty() && it != SUBTITLE_OFF }
        dataStore.edit { preferences ->
            if (clean == null) preferences.remove(PREFERRED_SUBTITLE_LANGUAGE_KEY)
            else preferences[PREFERRED_SUBTITLE_LANGUAGE_KEY] = clean
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
            preferences[VIP_PENDING_AMOUNT_KEY] = submission.amountPkr
            preferences[VIP_PENDING_SUBMITTED_AT_KEY] = submission.submittedAt
        }
    }

    suspend fun clearVipPendingSubmission() {
        dataStore.edit { preferences ->
            preferences.remove(VIP_PENDING_TID_KEY)
            preferences.remove(VIP_PENDING_PLAN_KEY)
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
        private val LAN_SHARE_ENABLED_KEY = booleanPreferencesKey("lan_share_enabled")
        private val SYNC_KEY_KEY = stringPreferencesKey("sync_key")
        private val IMAGE_QUALITY_KEY = stringPreferencesKey("image_quality")
        private val MOBILE_DATA_KEY = booleanPreferencesKey("mobile_data_allowed")
        private val KEEP_TTL_KEY = intPreferencesKey("keep_ttl_hours")
        private val PREFERRED_SUBTITLE_LANGUAGE_KEY = stringPreferencesKey("preferred_subtitle_language")
        private val DYNAMIC_COLOR_KEY = booleanPreferencesKey("dynamic_color")
        private val VIEW_MODE_KEY = stringPreferencesKey("view_mode")
        private val VIP_PENDING_TID_KEY = stringPreferencesKey("vip_pending_tid")
        private val VIP_PENDING_PLAN_KEY = stringPreferencesKey("vip_pending_plan")
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
 * cannot silently restate what the viewer says they paid.
 */
data class VipPendingSubmission(
    val transactionId: String,
    val plan: String,
    val amountPkr: Int,
    val submittedAt: Long,
)
