package com.raddstream.app.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.floatPreferencesKey
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.raddstream.app.brand.Brand
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.Flow
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

        /** AudioBoost's own anchor and ceiling, restated here as the storage contract. */
        const val DEFAULT_AUDIO_BOOST = 1f
        const val MAX_AUDIO_BOOST = 2f

        /** The storage contract for the rows above; the UI types map onto these. */
        const val DEFAULT_IMAGE_QUALITY = "AUTO"
        const val KEEP_TTL_HOURS_3 = 3
        const val KEEP_TTL_HOURS_6 = 6
        const val DEFAULT_KEEP_TTL_HOURS = KEEP_TTL_HOURS_3
        const val SUBTITLE_OFF = "Off"
    }
}
