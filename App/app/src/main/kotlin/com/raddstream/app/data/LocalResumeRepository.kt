package com.raddstream.app.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import dagger.hilt.android.qualifiers.ApplicationContext
import java.security.MessageDigest
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.first

private val Context.localResumeDataStore by preferencesDataStore(name = "local_resume_positions")

/** How many local files keep a resume position before the oldest ones are pruned. */
const val MAX_LOCAL_RESUMES = 100

/** A local file's resume is keyed by the URI's hash, never by the URI itself. */
fun localResumeKey(uri: String): String = "local_resume_" + sha256Hex(uri)

/** Lowercase hex SHA-256, the same digest shape the rest of the app hashes with. */
fun sha256Hex(value: String): String {
    val digest = MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8))
    // A byte is signed: mask before formatting, or 0xAB prints as "ffffffab".
    return digest.joinToString("") { "%02x".format(it.toInt() and 0xFF) }
}

/** A stored resume position: `"<positionMs>|<updatedAtMs>"`. */
fun formatLocalResume(positionMs: Long, updatedAtMs: Long): String = "$positionMs|$updatedAtMs"

/** The stored position, or null when the value is missing or malformed. */
fun parseLocalResume(value: String?): Long? {
    val position = value?.substringBefore('|')?.toLongOrNull() ?: return null
    return position.takeIf { it > 0 }
}

/** The stored write time, or null when the value is missing or malformed. */
fun parseLocalResumeUpdatedAt(value: String?): Long? =
    value?.substringAfter('|', "")?.toLongOrNull()

/** A resume key belongs to a local file when it addresses the device, not the server. */
fun isLocalResumeUri(key: String): Boolean =
    key.startsWith("content://") || key.startsWith("file://")

/**
 * Which stored entries to drop so only the [keep] newest (by write time)
 * survive. Entries with no readable write time count as the oldest. Pure, so
 * the pruning rule is pinned by a JVM test.
 */
fun localResumeKeysToPrune(entries: Map<String, String>, keep: Int = MAX_LOCAL_RESUMES): Set<String> {
    if (entries.size <= keep) return emptySet()
    return entries.entries
        .sortedBy { parseLocalResumeUpdatedAt(it.value) ?: 0L }
        .take(entries.size - keep)
        .map { it.key }
        .toSet()
}

/**
 * Where a local file stopped playing, so a video opened from the phone
 * resumes after the app restarts. The player's in-memory map dies with the
 * process, and a local file has no work ref for Room or the sync account to
 * hang a position on — so local URIs get their own small DataStore, one
 * string per file, keyed by the URI's hash.
 *
 * The write rule mirrors [PlayerViewModel.rememberResume] exactly: only a
 * real middle counts (past 5 s, before the end); a finished or barely-started
 * file clears its entry instead of storing a useless 0.
 */
@Singleton
class LocalResumeRepository @Inject constructor(
    @ApplicationContext context: Context,
) {
    private val dataStore: DataStore<Preferences> = context.localResumeDataStore

    suspend fun positionFor(uri: String): Long? {
        val preferences = dataStore.data.first()
        return parseLocalResume(preferences[stringPreferencesKey(localResumeKey(uri))])
    }

    suspend fun savePosition(uri: String, positionMs: Long, durationMs: Long) {
        if (durationMs <= 0) return
        dataStore.edit { preferences ->
            val key = stringPreferencesKey(localResumeKey(uri))
            if (positionMs > 5_000 && positionMs < durationMs) {
                preferences[key] = formatLocalResume(positionMs, System.currentTimeMillis())
                val stored = preferences.asMap()
                    .filterKeys { it.name.startsWith("local_resume_") }
                    .mapValues { (it.value as? String).orEmpty() }
                for (stale in localResumeKeysToPrune(stored)) {
                    preferences.remove(stringPreferencesKey(stale))
                }
            } else {
                preferences.remove(key)
            }
        }
    }

    suspend fun removePosition(uri: String) {
        dataStore.edit { preferences ->
            preferences.remove(stringPreferencesKey(localResumeKey(uri)))
        }
    }
}
