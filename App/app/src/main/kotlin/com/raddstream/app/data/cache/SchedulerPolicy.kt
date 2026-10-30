package com.raddstream.app.data.cache

/** Coarse network class driving whether auto-preview downloads may run at all. */
enum class NetworkClass { WIFI, MOBILE, METERED_ROAMING, NONE }

/** A task as the scheduler sees it — pure, no Room, no Android. */
data class SchedulableTask(
    val taskId: Long,
    val priority: CachePriority,
    val estimatedRemainingBytes: Long,
    val enqueueElapsedRealtime: Long,
    val isRunning: Boolean,
)

/** Scheduler tuning; every field is a policy knob the app maps from user settings. */
data class SchedulerPolicy(
    val maxConcurrent: Int = 2,
    val allowAutoPreviewOnMobile: Boolean = false,
    /** Bytes the user is willing to spend on auto-preview over a period; 0 = unlimited. */
    val autoPreviewDataBudgetBytes: Long = 0L,
    val autoPreviewBytesSpentThisPeriod: Long = 0L,
)

/** A scheduling tick's outcome. */
data class SchedulingDecision(
    val startTaskIds: List<Long>,
    val preemptTaskIds: List<Long>,
    val throttledAutoPreviewIds: List<Long>,
    val reason: String,
)

/**
 * Pure queue / fairness selection.
 *
 * Rules:
 *  - a global concurrency cap ([SchedulerPolicy.maxConcurrent]); never exceeded.
 *  - user-requested tasks ALWAYS beat auto-preview: they are scheduled first and, when the
 *    pool is full of auto-preview work, the newest/least-progressed auto-preview tasks are
 *    pre-empted (paused, resumable) to open slots.
 *  - within a band, first-in-first-served (oldest enqueue wins) so nothing starves.
 *  - auto-preview is disabled on non-Wi-Fi unless [allowAutoPreviewOnMobile], and is further
 *    throttled when the data budget for the period is exhausted.
 *  - everything is pausable; pre-emption is a pause, never a cancel, so bytes are kept.
 */
object SchedulerPolicySelector {

    fun select(
        tasks: List<SchedulableTask>,
        network: NetworkClass,
        policy: SchedulerPolicy,
    ): SchedulingDecision {
        val running = tasks.filter { it.isRunning }
        val pending = tasks.filter { !it.isRunning }

        // No connectivity at all: nothing can transfer; keep everything parked.
        if (network == NetworkClass.NONE) {
            return SchedulingDecision(emptyList(), emptyList(), emptyList(), "no_network")
        }

        // Auto-preview is gated by network + budget; user-requested is not. Both rules live in the
        // two functions below, because the playhead path starts one task without running a tick and
        // must not be a second, weaker copy of this gate.
        val autoPreviewAllowed = autoPreviewAllowedOn(network, policy)
        val budgetLeft = autoPreviewBudgetLeftBytes(policy)

        val throttledAuto = pending.filter {
            it.priority == CachePriority.AUTO_PREVIEW && autoPreviewAllowed &&
                it.estimatedRemainingBytes > budgetLeft
        }.map { it.taskId }

        // Candidate ordering: user first, then auto (if allowed), FIFO within band.
        val orderedCandidates = pending
            .filter { it.priority == CachePriority.USER_REQUESTED || autoPreviewAllowed }
            .filter { it.taskId !in throttledAuto }
            .sortedWith(
                compareByDescending<SchedulableTask> { it.priority == CachePriority.USER_REQUESTED }
                    .thenBy { it.enqueueElapsedRealtime }
            )

        val freeSlots = (policy.maxConcurrent - running.size).coerceAtLeast(0)
        val starts = orderedCandidates.take(freeSlots).map { it.taskId }

        // Pre-emption: if more user tasks want slots than are free, pause running auto-preview.
        val userDemand = orderedCandidates.count { it.priority == CachePriority.USER_REQUESTED }
        val preempts = mutableListOf<Long>()
        if (userDemand > freeSlots) {
            var needed = userDemand - freeSlots
            val runningAuto = running
                .filter { it.priority == CachePriority.AUTO_PREVIEW }
                .sortedWith(
                    compareByDescending<SchedulableTask> { it.estimatedRemainingBytes } // least progressed first
                        .thenByDescending { it.enqueueElapsedRealtime }
                )
            for (t in runningAuto) {
                if (needed <= 0) break
                preempts.add(t.taskId)
                needed--
            }
        }

        val reason = when {
            network == NetworkClass.NONE -> "no_network"
            !autoPreviewAllowed -> "auto_preview_disabled_on_network"
            throttledAuto.isNotEmpty() -> "auto_preview_over_data_budget"
            preempts.isNotEmpty() -> "user_tasks_preempt_auto_preview"
            starts.isNotEmpty() -> "slots_available"
            else -> "pool_full"
        }

        return SchedulingDecision(starts, preempts, throttledAuto, reason)
    }

    /**
     * Whether opportunistic ahead-of-playback work may move at all on [network].
     *
     * Pulled out of [select] and given a name because the playhead callback starts ONE task without
     * running a tick: if it re-typed this `when` it would be a second owner of the network rule, and
     * the second owner is always the one that drifts. A viewer on roaming gets no preview from either
     * path, and neither path needs a file to be deleted to notice.
     */
    fun autoPreviewAllowedOn(network: NetworkClass, policy: SchedulerPolicy): Boolean = when (network) {
        NetworkClass.WIFI -> true
        NetworkClass.MOBILE -> policy.allowAutoPreviewOnMobile
        NetworkClass.METERED_ROAMING -> false
        NetworkClass.NONE -> false
    }

    /** Bytes auto-preview may still spend this period; [Long.MAX_VALUE] = no budget configured. */
    fun autoPreviewBudgetLeftBytes(policy: SchedulerPolicy): Long =
        if (policy.autoPreviewDataBudgetBytes <= 0L) Long.MAX_VALUE
        else (policy.autoPreviewDataBudgetBytes - policy.autoPreviewBytesSpentThisPeriod)
            .coerceAtLeast(0L)

    /**
     * The same two rules [select] applies, answering them for one task of [estimatedRemainingBytes]
     * without a queue to sort. Used by the playhead path, which is a start request and not a tick.
     */
    fun mayStartAutoPreview(
        network: NetworkClass,
        policy: SchedulerPolicy,
        estimatedRemainingBytes: Long,
    ): Boolean = autoPreviewAllowedOn(network, policy) && estimatedRemainingBytes <= autoPreviewBudgetLeftBytes(policy)
}
