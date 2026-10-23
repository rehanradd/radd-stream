package com.raddstream.app.data.cache

/** Lifecycle states of a cache/download task. Mirrors the spec's required state set. */
enum class CacheTaskState {
    QUEUED,        // scheduled, not yet started, holds no network
    LOADING,       // actively transferring bytes
    PAUSED,        // deliberately stopped (user pause / network policy / backoff wait), resumable
    COMPLETED,     // ledger reports 100% of known size, file verified
    FAILED,        // unrecoverable for now (auth/expired/404), resumable if re-resolved
    EXPIRED,       // TTL elapsed for an auto-preview file, pending deletion
    DELETED,       // file removed from disk, terminal bookkeeping state
    ;

    companion object {
        val ACTIVE = setOf(QUEUED, LOADING, PAUSED)
        val NEEDS_FILE = setOf(LOADING, COMPLETED, PAUSED, EXPIRED)
    }
}

/** Priority band. User-requested always outranks auto-preview regardless of enqueue order. */
enum class CachePriority {
    USER_REQUESTED, // the user tapped "keep this" / explicit download
    AUTO_PREVIEW,   // opportunistic ahead-of-playback buffering, TTL-managed
    ;
}

/** Why a task is being started, drives whether it is TTL-managed. */
enum class CacheOrigin { AUTO_PREVIEW, USER_KEEP }

/**
 * Pure state machine for [CacheTaskState].
 *
 * Transitions are whitelisted; anything else is rejected so a bug in the fetcher or a
 * late callback from a cancelled request cannot corrupt the DB into an impossible state.
 * The rules encode the hostile cases from the spec:
 *  - a killed/failed LOADING task can go back to QUEUED/PAUSED (resume, never restart)
 *  - COMPLETED is only reachable through verify, never implicitly
 *  - EXPIRED -> DELETED only (never back to LOADING — a deleted-then-wanted file becomes
 *    QUEUED from the identity, which is the resume-not-leak path)
 */
object CacheTaskStateMachine {

    private val allowed: Map<CacheTaskState, Set<CacheTaskState>> = mapOf(
        CacheTaskState.QUEUED to setOf(
            CacheTaskState.LOADING,
            CacheTaskState.PAUSED,
            CacheTaskState.FAILED,
            CacheTaskState.DELETED, // cancelled before start
        ),
        CacheTaskState.LOADING to setOf(
            CacheTaskState.PAUSED,
            CacheTaskState.COMPLETED,
            CacheTaskState.FAILED,
            CacheTaskState.QUEUED,  // pre-empted / re-resolved
            CacheTaskState.DELETED, // cancelled mid-download, temp cleaned
        ),
        CacheTaskState.PAUSED to setOf(
            CacheTaskState.QUEUED,
            CacheTaskState.LOADING,
            CacheTaskState.FAILED,
            CacheTaskState.EXPIRED, // auto-preview paused too long -> age out
            CacheTaskState.DELETED,
        ),
        CacheTaskState.COMPLETED to setOf(
            CacheTaskState.EXPIRED, // auto-preview file ages out
            CacheTaskState.DELETED,  // user deletes a kept file
        ),
        CacheTaskState.FAILED to setOf(
            CacheTaskState.QUEUED,  // re-resolve and retry
            CacheTaskState.LOADING,
            CacheTaskState.PAUSED,
            CacheTaskState.EXPIRED,
            CacheTaskState.DELETED,
        ),
        CacheTaskState.EXPIRED to setOf(
            CacheTaskState.DELETED,
            CacheTaskState.QUEUED,  // still referenced by a live task: re-arm instead of delete
        ),
        CacheTaskState.DELETED to emptySet(), // terminal
    )

    fun canTransition(from: CacheTaskState, to: CacheTaskState): Boolean =
        from != CacheTaskState.DELETED && to in (allowed[from] ?: emptySet())

    /**
     * Enforce a transition. Returns the new state on success, throws [IllegalStateTransition]
     * on a disallowed move (the fetcher treats that as a bug and leaves the DB untouched).
     */
    fun requireTransition(from: CacheTaskState, to: CacheTaskState): CacheTaskState {
        if (!canTransition(from, to)) {
            throw IllegalStateTransition(from, to)
        }
        return to
    }

    val allStates: List<CacheTaskState> get() = CacheTaskState.values().toList()

    /** True when the state still logically "owns" a running task (blocks auto-delete). */
    fun holdsRunningTask(state: CacheTaskState): Boolean =
        state == CacheTaskState.QUEUED || state == CacheTaskState.LOADING
}

class IllegalStateTransition(from: CacheTaskState, to: CacheTaskState) :
    IllegalStateException("Illegal cache task transition: $from -> $to")

/**
 * Retry / backoff policy, computed purely from an attempt counter so it is testable and
 * identical across restarts (a restart must not reset the backoff clock to zero).
 *
 * Exponential with a full jitter ceiling; clamped so a long-lived failed task never schedules
 * absurdly far out. `attempt` is 1-based.
 */
object RetryPolicy {
    const val MAX_ATTEMPTS = 6
    private const val BASE_MS = 2_000L
    private const val CAP_MS = 30 * 60_000L // 30 minutes max backoff

    fun isExhausted(attempt: Int): Boolean = attempt >= MAX_ATTEMPTS

    /** Upper bound of the backoff window for [attempt], before jitter. */
    fun backoffCeilingMs(attempt: Int): Long {
        if (attempt <= 0) return 0L
        val exp = (1L shl (attempt - 1).coerceAtMost(20)) // guard shift overflow
        return (BASE_MS * exp).coerceAtMost(CAP_MS)
    }

    /**
     * Deterministic jitter for tests and reproducibility: spreads the retry within the window
     * using a simple mix of attempt and a caller-supplied stable seed (the source identity
     * digest), so many tasks for one resource do not all retry on the same instant.
     */
    fun nextRetryDelayMs(attempt: Int, stableSeed: Long): Long {
        val ceiling = backoffCeilingMs(attempt)
        if (ceiling <= 0L) return 0L
        val mixed = (stableSeed xor (attempt * 0x9E3779B97F4A7C15uL.toLong()))
            .toUnsignedPositiveLong()
        return BASE_MS + (mixed % (ceiling - BASE_MS + 1))
    }

    private fun Long.toUnsignedPositiveLong(): Long =
        if (this == Long.MIN_VALUE) 0L else kotlin.math.abs(this)
}
