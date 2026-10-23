package com.raddstream.app.data.cache

/** The user-configurable auto-preview retention window. */
enum class TtlHours(val hours: Int) {
    THREE(3),
    SIX(6),
    ;
    val millis: Long get() = hours * 3_600_000L

    companion object {
        fun fromHours(hours: Int): TtlHours =
            if (hours <= THREE.hours) THREE else SIX
    }
}

/** Result of a TTL evaluation for one file. */
enum class TtlDecision { KEEP, EXPIRE, DEFER }
enum class TtlReason {
    USER_KEPT,               // never auto-deleted
    WITHIN_TTL,              // not old enough yet
    HELD_BY_RUNNING_TASK,    // a queued/loading task still owns it — do not touch
    ORPHANED_TEMP,           // temp file with no live task — leak, sweep it
    TEMP_GRACE_ACTIVE,       // temp file but within the post-crash grace window
    EXPIRED,                 // aged past TTL
}

data class TtlVerdict(val decision: TtlDecision, val reason: TtlReason)

/**
 * Everything the TTL sweep needs to know about one file, kept as a plain snapshot so the
 * decision logic is pure and unit-testable without Room or a Context.
 */
data class FileSnapshot(
    val fileId: String,
    val origin: CacheOrigin,
    /** Monotonic creation stamp — MUST come from an uptime clock, see [UptimeClock]. */
    val createdElapsedRealtime: Long,
    /** Monotonic stamp of the last time a player or task touched the file. */
    val lastAccessElapsedRealtime: Long,
    val sizeBytes: Long,
    val isTemporary: Boolean,
    /** True when a task in [CacheTaskState.QUEUED] / [CacheTaskState.LOADING] references it. */
    val referencedByRunningTask: Boolean,
)

/**
 * Monotonic, sleep-counting clock (Android `SystemClock.elapsedRealtime()`): it keeps running
 * through device sleep and is immune to the user changing the wall clock or timezone. We use
 * it for every age comparison so an auto-preview file cannot be expired early by a clock jump,
 * and cannot survive 6 real hours just because the phone was off.
 */
fun interface UptimeClock {
    fun nowElapsedRealtime(): Long
}

/** Injected into a JVM test; the app wires [AndroidUptimeClock]. */
class FixedUptimeClock(startMillis: Long = 0L) : UptimeClock {
    private var now = startMillis
    override fun nowElapsedRealtime(): Long = now
    fun advanceTo(millis: Long) { now = millis }
    fun advance(deltaMillis: Long) { now += deltaMillis }
}

/**
 * TTL / auto-delete rules. All time inputs are monotonic elapsedRealtime values.
 *
 * Precedence (the rules from the spec, in the order they must win):
 *  1. A file the user explicitly kept (`origin = USER_KEEP`) is NEVER auto-deleted.
 *  2. A file still referenced by a running task is DEFERRED, not deleted, even if aged —
 *     deleting under a live writer would corrupt an in-flight download.
 *  3. A temporary file with no live task (a crash/kill left it behind) is swept as an
 *     ORPHANED_TEMP leak once a short grace window has passed; within the grace window it is
 *     left alone in case the owner resumes.
 *  4. Otherwise an auto-preview file expires once its age reaches the configured TTL,
 *     measured from creation; touching the file does NOT extend its life (a preview the user
 *     keeps re-watching is promoted to USER_KEEP by the player, that is the supported way to
 *     make it permanent).
 */
object TtlPolicy {

    /** Grace before an orphaned temp file is reclaimed; lets a quick resume keep its bytes. */
    const val TEMP_GRACE_MILLIS: Long = 20 * 60_000L // 20 minutes

    fun evaluate(
        file: FileSnapshot,
        nowElapsedRealtime: Long,
        ttl: TtlHours,
    ): TtlVerdict {
        // Rule 1 — user-kept files are never auto-deleted.
        if (file.origin == CacheOrigin.USER_KEEP) {
            return TtlVerdict(TtlDecision.KEEP, TtlReason.USER_KEPT)
        }

        val age = (nowElapsedRealtime - file.createdElapsedRealtime).coerceAtLeast(0L)

        // Rule 2 — a live writer owns it.
        if (file.referencedByRunningTask) {
            return TtlVerdict(TtlDecision.DEFER, TtlReason.HELD_BY_RUNNING_TASK)
        }

        // Rule 3 — orphaned temp file (owner is gone).
        if (file.isTemporary) {
            return if (age >= TEMP_GRACE_MILLIS) {
                TtlVerdict(TtlDecision.EXPIRE, TtlReason.ORPHANED_TEMP)
            } else {
                TtlVerdict(TtlDecision.KEEP, TtlReason.TEMP_GRACE_ACTIVE)
            }
        }

        // Rule 4 — normal auto-preview aging.
        return if (age >= ttl.millis) {
            TtlVerdict(TtlDecision.EXPIRE, TtlReason.EXPIRED)
        } else {
            TtlVerdict(TtlDecision.KEEP, TtlReason.WITHIN_TTL)
        }
    }

    /**
     * When an expired auto-preview file should next be re-examined (for WorkManager
     * scheduling). Returns millis-from-now until the TTL boundary, or 0 when already due.
     * User-kept files return [Long.MAX_VALUE] (never schedule a re-check for them).
     */
    fun millisUntilDue(file: FileSnapshot, nowElapsedRealtime: Long, ttl: TtlHours): Long {
        if (file.origin == CacheOrigin.USER_KEEP) return Long.MAX_VALUE
        val boundary = file.createdElapsedRealtime + ttl.millis
        return (boundary - nowElapsedRealtime).coerceAtLeast(0L)
    }
}
