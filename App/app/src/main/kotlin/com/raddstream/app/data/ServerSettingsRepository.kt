package com.raddstream.app.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.floatPreferencesKey
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

    companion object {
        private val SERVER_URL_KEY = stringPreferencesKey("server_url")
        private val AUDIO_BOOST_LEVEL_KEY = floatPreferencesKey("audio_boost_level")
        private val PREFERRED_AUDIO_LANGUAGE_KEY = stringPreferencesKey("preferred_audio_language")
        private val LAN_SHARE_ENABLED_KEY = booleanPreferencesKey("lan_share_enabled")

        /** AudioBoost's own anchor and ceiling, restated here as the storage contract. */
        const val DEFAULT_AUDIO_BOOST = 1f
        const val MAX_AUDIO_BOOST = 2f
    }
}
