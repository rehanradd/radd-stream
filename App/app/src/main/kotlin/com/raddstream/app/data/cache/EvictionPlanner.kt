package com.raddstream.app.data.cache

/**
 * A file the storage manager may consider keeping or deleting. Plain snapshot so the
 * eviction ordering is pure and unit-testable (the Android layer fills this from Room +
 * [android.os.StatFs]).
 */
data class EvictionCandidate(
    val fileId: String,
    val sizeBytes: Long,
    val origin: CacheOrigin,
    val lastAccessElapsedRealtime: Long,
    /** How useful it is to the user right now: plays/watch count. 0 = never watched. */
    val watchCount: Int,
    val referencedByRunningTask: Boolean,
    val isTemporary: Boolean,
    val isComplete: Boolean,
) {
    /** Files the user kept, and files a live task owns, are protected from eviction. */
    val isProtected: Boolean
        get() = origin == CacheOrigin.USER_KEEP || referencedByRunningTask

    /**
     * Lower = evict first. Protected files sort last via the planner, so their raw score is
     * not meaningful here. Ordering within evictable files:
     *   temp junk  <  incomplete previews  <  completed previews
     *   then lowest watchCount first, then oldest lastAccess first.
     */
    fun usefulnessScore(nowElapsedRealtime: Long): Int {
        var score = 0
        if (isTemporary) score -= 100
        if (!isComplete) score -= 30
        score += watchCount.coerceAtMost(20)
        // recency bonus: touched within the last hour scores higher
        val idleMillis = (nowElapsedRealtime - lastAccessElapsedRealtime).coerceAtLeast(0L)
        if (idleMillis < 3_600_000L) score += 10
        return score
    }
}

/** Result of an eviction plan: an ordered list of files to delete and how much they free. */
data class EvictionPlan(
    val deletions: List<EvictionCandidate>,
    val freedBytes: Long,
    val sufficient: Boolean,
    val protectedBytesRetained: Long,
)

/**
 * Storage limits for the cache workspace. All values in bytes.
 *
 * @param hardCeilingBytes the app-imposed ceiling on total cache usage (the "never be the
 *        reason the phone runs out of space" cap), a user setting.
 * @param lowStorageFloorBytes the OS free-space level below which we aggressively evict
 *        before accepting any new write.
 * @param perFileMaxBytes single-file cap so one 4K remaster cannot hog the workspace.
 */
data class StorageLimits(
    val hardCeilingBytes: Long,
    val lowStorageFloorBytes: Long,
    val perFileMaxBytes: Long,
)

/** Verdict for an incoming write of [requestedBytes] given [currentUsedBytes]. */
sealed class AdmitDecision {
    object Admit : AdmitDecision()
    data class EvictThenAdmit(val plan: EvictionPlan) : AdmitDecision()
    data class RejectTooBigForCeiling(val requestedBytes: Long, val ceilingHeadroom: Long) : AdmitDecision()
    data class RejectPerFileCap(val requestedBytes: Long, val perFileMaxBytes: Long) : AdmitDecision()
    data class RejectNoEvictableHeadroom(val stillNeededBytes: Long) : AdmitDecision()
}

/**
 * Decides what to delete and whether a write may proceed, given the hostile cases: disk full,
 * OS cache pressure, per-file and per-workspace quotas, a hard ceiling. It never deletes a
 * user-kept file or a file a running task owns. It frees the *least useful* bytes first.
 */
object EvictionPlanner {

    /** Sort candidates evict-first (lowest usefulness, then oldest access, then id). */
    fun orderedForEviction(candidates: List<EvictionCandidate>, nowElapsedRealtime: Long): List<EvictionCandidate> =
        candidates
            .filterNot { it.isProtected }
            .sortedWith(
                compareBy<EvictionCandidate> { it.usefulnessScore(nowElapsedRealtime) }
                    .thenBy { it.lastAccessElapsedRealtime }
                    .thenBy { it.fileId }
            )

    /**
     * Build a deletion plan to free at least [bytesToFree], evicting least-useful first and
     * never touching protected files. If the evictable pool cannot supply enough, the plan is
     * returned with `sufficient = false` so the caller can refuse the write rather than delete
     * something it must not.
     */
    fun plan(
        candidates: List<EvictionCandidate>,
        bytesToFree: Long,
        nowElapsedRealtime: Long,
    ): EvictionPlan {
        if (bytesToFree <= 0L) {
            return EvictionPlan(emptyList(), 0L, true, protectedBytes(candidates))
        }
        val ordered = orderedForEviction(candidates, nowElapsedRealtime)
        val chosen = ArrayList<EvictionCandidate>()
        var freed = 0L
        for (c in ordered) {
            chosen.add(c)
            freed += c.sizeBytes
            if (freed >= bytesToFree) break
        }
        return EvictionPlan(
            deletions = chosen,
            freedBytes = freed,
            sufficient = freed >= bytesToFree,
            protectedBytesRetained = protectedBytes(candidates),
        )
    }

    /**
     * The gate before any write. Combines the hard ceiling, the per-file cap, and the OS
     * low-storage floor into one decision. [osFreeBytes] is what the volume actually has;
     * [currentUsedBytes] is what the cache workspace currently occupies.
     */
    fun admit(
        requestedBytes: Long,
        currentUsedBytes: Long,
        osFreeBytes: Long,
        limits: StorageLimits,
        candidates: List<EvictionCandidate>,
        nowElapsedRealtime: Long,
    ): AdmitDecision {
        if (requestedBytes <= 0L) return AdmitDecision.Admit

        if (requestedBytes > limits.perFileMaxBytes) {
            return AdmitDecision.RejectPerFileCap(requestedBytes, limits.perFileMaxBytes)
        }

        val ceilingHeadroom = (limits.hardCeilingBytes - currentUsedBytes).coerceAtLeast(0L)
        if (requestedBytes > ceilingHeadroom) {
            return AdmitDecision.RejectTooBigForCeiling(requestedBytes, ceilingHeadroom)
        }

        // Bytes we must claw back = the larger of (workspace headroom deficit) and
        // (OS low-storage shortfall). Ceiling was already satisfied above, so only the OS
        // floor can still demand eviction.
        val deficitForFloor = (limits.lowStorageFloorBytes - osFreeBytes).coerceAtLeast(0L)
        if (deficitForFloor == 0L) return AdmitDecision.Admit

        val plan = plan(candidates, deficitForFloor, nowElapsedRealtime)
        return if (plan.sufficient) {
            AdmitDecision.EvictThenAdmit(plan)
        } else {
            AdmitDecision.RejectNoEvictableHeadroom(deficitForFloor - plan.freedBytes)
        }
    }

    private fun protectedBytes(candidates: List<EvictionCandidate>): Long =
        candidates.filter { it.isProtected }.sumOf { it.sizeBytes }
}
