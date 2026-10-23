package com.raddstream.app.player

import kotlinx.coroutines.flow.StateFlow

/**
 * THE BOUNDARY between the player (this agent) and the download/cache ENGINE
 * (sibling agent, the `data/cache` package). PLAYER_SPEC.md §4.
 *
 * Everything the player needs is expressed here; the two halves meet when the data agent
 * supplies an implementation and assigns it to [CacheEngineHolder.engine] at app start
 * (see HANDOFF_appplayer.md). While [CacheEngineHolder.engine] is null every affordance in
 * the player UI degrades to "keep not available on this build" — visibly, never faked.
 *
 * Core contract — **never waste bytes**: when the user taps *Keep this* mid-playback, the
 * player hands over the byte/range progress already fetched (or an honest time-based
 * estimate) plus the playback position, and the engine must continue the remaining download
 * from that cursor, *not* re-fetch from zero.
 */

/** Identity of one playing session shared between the two sides. */
data class CacheSessionKey(val renditionKey: String, val url: String)

/** Live picture of how much of the current media is already on disk. */
data class CacheSnapshot(
    /** Bytes durably fetched so far (engine-authoritative if known). */
    val bytesSaved: Long,
    /** Full media size when known (print `size_bytes`, Content-Length, HLS sum). */
    val totalBytes: Long?, // null = unknown (live/segmented)
    /** Instantaneous fetch speed, bytes/sec (0 when idle). */
    val bytesPerSec: Long,
    /** True when [bytesSaved] is derived from playback buffer time, not the engine's counters. */
    val isEstimate: Boolean,
    /** Whether the current URL supports Range resume — governs the interrupt story. */
    val resumable: Boolean,
    /** When the *preview* copy auto-expires (TTL 3-6 h per engine policy); null = permanent. */
    val previewExpiresAt: Long?,
    val state: CacheState,
)

enum class CacheState {
    /** Only the rolling ahead-of-playback buffer exists (the default while watching). */
    PROGRESSIVE,
    /** The user tapped Keep and the engine took over fetching. */
    KEEPING,
    /** Fully stored; playable offline. */
    STORED,
    /** Interrupted (network died); resumable from [CacheSnapshot.bytesSaved] if possible. */
    INTERRUPTED,
    /** Refused for storage reasons — see [StoragePressure]. */
    STORAGE_FULL,
    /** File exists but only this app can open it (private-sandbox/encrypted preview). */
    APP_PRIVATE_ONLY,
    /** Preview TTL elapsed; copy auto-deleted by the engine policy. */
    EXPIRED,
    FAILED,
}

enum class StoragePressure { OK, NEAR_FULL, FULL }

/**
 * What the player hands the engine on *Keep this*. Byte cursor first (if the engine knows
 * it), time-based estimate second, so the engine can choose its resume strategy honestly.
 */
data class AdoptRequest(
    val key: CacheSessionKey,
    val url: String,
    /** Bytes already transferred for the media (authoritative when isByteCursorKnown). */
    val fetchedBytesSoFar: Long,
    val isByteCursorKnown: Boolean,
    /** Playback position right now, ms. */
    val positionMs: Long,
    /** Head of the playable buffer, ms (everything below it is certainly fetched). */
    val bufferedMs: Long,
    val durationMs: Long,
    /** Expected full size (print size_bytes / Content-Length); null = unknown. */
    val expectedTotalBytes: Long?,
    val resumable: Boolean,
    /** Print label so the engine's library UI can show what this file is. */
    val printLabel: String,
    /** True when this URL was already downloaded through the shared cache data source. */
    val sharesCacheStorage: Boolean,
)

/** Keep outcomes the UI must be able to explain (hostile realities from the task brief). */
sealed class KeepResult {
    data class Stored(val localHandle: String, val playableOffline: Boolean) : KeepResult()
    data class StorageFull(val requiredBytes: Long, val availableBytes: Long) : KeepResult()
    data class OnlyPlayableInApp(val reason: String, val ttlSeconds: Long?) : KeepResult()
    data class Interrupted(val fetchedBytes: Long, val willAutoResume: Boolean) : KeepResult()
    data class Failed(val message: String) : KeepResult()
    object EngineNotWired : KeepResult()
}

/**
 * THE ENGINE SIDE OF THE BOUNDARY (sibling implements this in the `data/cache` package).
 * Requirements we impose, mirrored in HANDOFF_appplayer.md:
 *  1. [observe] emits a snapshot at least each 500 ms while a session is live, including
 *     engine-authoritative byte counters for the SAME URL the player is fetching through the
 *     shared cache data source (this is what makes adoption byte-precise).
 *  2. [adopt] MUST NOT re-download [AdoptRequest.fetchedBytesSoFar] bytes.
 *  3. [adopt] is safe to call repeatedly (idempotent per key).
 *  4. Storage policy (near-full reserve, TTL auto-delete, preview→permanent upgrade) stays
 *     entirely inside the engine; the player only displays the state you report.
 */
interface ProgressiveCacheEngine {
    fun observe(key: CacheSessionKey): StateFlow<CacheSnapshot?>
    suspend fun adopt(request: AdoptRequest): KeepResult
    suspend fun cancelKeep(key: CacheSessionKey)
    suspend fun release(key: CacheSessionKey)
    fun storagePressure(): StoragePressure
    /** When the app opens an already-STORED file, ask the engine for its playable URL. */
    suspend fun playableUri(key: CacheSessionKey): String?
}

/** Wiring point the data agent sets at startup (Application/DI — their files, see handoff). */
object CacheEngineHolder {
    @Volatile
    var engine: ProgressiveCacheEngine? = null
}
