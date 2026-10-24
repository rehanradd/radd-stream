package com.raddstream.app.player

import com.raddstream.app.brand.Brand

/**
 * The whole state one binge-precache tick needs. Deliberately tiny so the caller can build it
 * from a Media3 progress tick plus the progression info it already has, without the policy
 * ever touching a Player, a Controller or the engine.
 *
 * [nextEpisodeHandle] is opaque on purpose: whether the next episode lives at a learned offset
 * in the same file (EpisodeProgression's InFileSeek) or behind a freshly resolved URL is a
 * wiring decision, and this policy must not re-derive it. The only promise is: a blank handle
 * means "we cannot address the next episode's bytes yet".
 */
data class BingePreloadState(
    val positionMs: Long,
    val durationMs: Long,
    val isSeries: Boolean,
    val nextEpisodeHandle: String?,
)

/** Why a tick asked for nothing. For diagnostics and future tuning — never user-facing copy. */
enum class BingeSkipReason {
    NOT_A_SERIES,

    /** durationMs <= 0: live/undefined (C.TIME_UNDEFINED) or an unprepared item. */
    DURATION_UNKNOWN,

    BEFORE_THRESHOLD,
    NO_NEXT_HANDLE,

    /** The fire-once rule: this episode already triggered its successor's prefetch. */
    ALREADY_REQUESTED,

    /** Brand storage policy leaves no room; requesting 0 bytes would be a lie to the engine. */
    BUDGET_EXHAUSTED,
}

/** Result of one [BingePreloader.decide] call — a decision, never an action. */
sealed class BingePreloadDecision {
    /**
     * Pull the first [headBytes] of the resource addressed by [handle] into the cache engine.
     * The wiring layer maps this onto whatever entry point the engine eventually exposes for
     * head-only pulls; the current [ProgressiveCacheEngine] boundary only has whole-file
     * [ProgressiveCacheEngine.adopt], which is why this class emits a request instead of
     * calling anything itself.
     */
    data class PrefetchNextHead(val handle: String, val headBytes: Long) : BingePreloadDecision()

    /** Nothing to do this tick. */
    data class Idle(val reason: BingeSkipReason) : BingePreloadDecision()
}

/**
 * Smart Binge Pre-Caching policy: at [thresholdPercent] of a series episode, ask for the head
 * (~[targetHeadBytes]) of the NEXT episode so the auto-advance transition opens instantly
 * instead of waiting on a cold first segment.
 *
 * WHY 85%: the remaining tail (~2-3 min of a typical episode) is more wall-clock than a
 * bounded head pull needs on any reasonable link, so the bytes are already on disk when
 * EpisodeProgression advances — without starting so early that a skipped/aborted episode
 * would have wasted the download.
 *
 * WHY fire-once lives in the caller's [BingePreloadState] set rather than here: the same
 * progress tick is re-delivered hundreds of times per episode, and the caller already owns
 * per-episode lifecycle state; a stateless decide() is trivially testable and cannot drift
 * across episode changes.
 *
 * WHY the byte cap comes from [Brand.aheadFetchMaxBytesPerPass]: a re-brand can lower the
 * engine's per-pass budget, and a binge prefetch must never be the request that ignores it.
 *
 * Pure JVM: no Android imports, no coroutines, no engine calls — the caller executes.
 */
class BingePreloader(
    /** Bytes to pull per next episode; the head is enough to make the open instant. */
    private val targetHeadBytes: Long = DEFAULT_HEAD_BYTES,
    /** Hard ceiling per request, from brand storage policy; 0 or less disables prefetch. */
    private val maxHeadBytesPerRequest: Long = Brand.aheadFetchMaxBytesPerPass,
    private val thresholdPercent: Int = THRESHOLD_PERCENT,
) {

    fun decide(
        state: BingePreloadState,
        alreadyRequested: Set<String>,
    ): BingePreloadDecision {
        if (!state.isSeries) return BingePreloadDecision.Idle(BingeSkipReason.NOT_A_SERIES)
        // Media3 reports C.TIME_UNDEFINED (Long.MIN_VALUE) or 0 before duration is known;
        // neither may divide, compare or seek — treat both as "not a finite episode".
        if (state.durationMs <= 0L) return BingePreloadDecision.Idle(BingeSkipReason.DURATION_UNKNOWN)

        val handle = state.nextEpisodeHandle?.trim()
        if (handle.isNullOrEmpty()) return BingePreloadDecision.Idle(BingeSkipReason.NO_NEXT_HANDLE)
        if (handle in alreadyRequested) return BingePreloadDecision.Idle(BingeSkipReason.ALREADY_REQUESTED)

        val threshold = thresholdPercent.coerceIn(1, 100)
        // Integer cross-multiplication: position/duration >= threshold/100 without floats
        // and without overflowing for any realistic ms pair.
        if (state.positionMs < 0L || state.positionMs * 100L < state.durationMs * threshold) {
            return BingePreloadDecision.Idle(BingeSkipReason.BEFORE_THRESHOLD)
        }

        val budget = minOf(targetHeadBytes, maxHeadBytesPerRequest)
        if (budget <= 0L) return BingePreloadDecision.Idle(BingeSkipReason.BUDGET_EXHAUSTED)
        return BingePreloadDecision.PrefetchNextHead(handle, budget)
    }

    companion object {
        /** ~10 MB covers the first minutes of even a high-bitrate head; enough for instant open. */
        const val DEFAULT_HEAD_BYTES = 10L * 1024 * 1024
        const val THRESHOLD_PERCENT = 85
    }
}
