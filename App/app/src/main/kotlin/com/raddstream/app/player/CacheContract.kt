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
 *
 * WHICH CURSOR IS REAL — and it is not this record's byte fields. [fetchedBytesSoFar],
 * [isByteCursorKnown], [bufferedMs] and [sharesCacheStorage] are assembled by
 * [CacheAffordance.buildAdoptRequest] from the player's *buffer-time* estimate and are read by
 * nothing in the engine: [com.raddstream.app.data.cache.OfflineCacheEngine] resumes from its own
 * committed-range ledger ([com.raddstream.app.data.cache.ByteRangeManifestDao]), which is exact
 * where a time-derived figure is only a guess, and a second owner for the resume cursor is exactly
 * how a byte gets fetched twice. They are disclosed here rather than quietly kept: four fields the
 * receiving side ignores, left in place because deleting them this pass would also delete
 * [CacheAffordance.estimateBytesSaved] and its cases, and this pass cannot compile to prove the cut
 * is clean. Requirement 2 below is satisfied by the ledger, not by them.
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

/**
 * What the player hands the engine the moment a title STARTS playing. Not a request to keep
 * anything: nobody asked, so nothing may be promised, evicted, or shown for it.
 *
 * This is the seed half of the watch-while-downloading story. Without a row there is nothing for a
 * progressing playhead to extend — the engine's playhead entry point looks a task up by its key and
 * returns when the lookup finds nothing — so "the playhead drives the cache" needs one opportunistic
 * row created by the fact that the viewer pressed play. That is all this is.
 *
 * Every field is the same fact [AdoptRequest] carries, and deliberately no position: where the
 * viewer has got to arrives on the playhead tick, which is the only place that number is fresh.
 */
data class PreviewRequest(
    val key: CacheSessionKey,
    val url: String,
    /** Print `size_bytes` when the catalog knows it; null = unknown, never a guess. */
    val expectedTotalBytes: Long?,
    val resumable: Boolean,
    /** Print label so the engine's library UI can show what this file is. */
    val printLabel: String,
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
 *  5. [seedPreview] is silent in BOTH directions: it returns no verdict because a preview that
 *     could not start must not surface anything — no gate, no spinner, no error text about a file
 *     the viewer never asked for. It must never delete or displace bytes the viewer *did* ask to
 *     keep, and it may not move a byte on a network the scheduler would refuse on a tick.
 */
interface ProgressiveCacheEngine {
    fun observe(key: CacheSessionKey): StateFlow<CacheSnapshot?>
    suspend fun adopt(request: AdoptRequest): KeepResult
    /**
     * The viewer pressed play on [request], so opportunistic bytes ahead of the playhead are worth
     * having. Called on load, from the player process's own service; safe to call repeatedly.
     */
    suspend fun seedPreview(request: PreviewRequest)
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
