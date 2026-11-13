package com.raddstream.app.viewmodel

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * Pre-resolve better (2026-11-13) — the detail-open preview seed's linger
 * gate.
 *
 * The `playV2` pre-resolve stays immediate, but the byte seed that follows
 * it must not start the moment the bundle lands: a viewer who opened the
 * title by accident leaves within a second or two, and a seed started for
 * them pulls an 8 MiB first window for nothing (the old code pulled the
 * full 40 MiB). This gate waits [PREVIEW_SEED_LINGER_MS] after the bundle
 * arrives, then asks [stillWanted] — the caller re-checks the bundle is
 * still this detail's current one and the device is still on Wi-Fi — and
 * only then runs [seed].
 *
 * Leaving the detail cancels the wait outright: the gate runs in the
 * caller's scope (the detail ViewModel's `viewModelScope`), so clearing
 * the ViewModel cancels the pending job, and [cancel] does the same when a
 * newer detail load supersedes this seed. A seed that never starts costs
 * nothing; the gate never starts a download itself, it only decides when
 * the caller's seed may run.
 *
 * [sleeper] is the wait itself (`delay` in production), injected so a
 * test can hold the wait open and release it without real time: the gate's
 * whole point is a temporal rule, and a rule that can only be tested by
 * sleeping 3 s is a rule that is never tested.
 */
internal class PreviewSeedGate(
    private val scope: CoroutineScope,
    private val lingerMs: Long = PREVIEW_SEED_LINGER_MS,
    private val sleeper: suspend (Long) -> Unit = { delay(it) },
) {
    private var job: Job? = null

    /** Arm the seed: wait the linger, re-check, then seed — once. */
    fun schedule(stillWanted: () -> Boolean, seed: suspend () -> Unit) {
        job?.cancel()
        job = scope.launch {
            sleeper(lingerMs)
            if (stillWanted()) seed()
        }
    }

    /** The viewer left, or a newer load superseded this seed: never run it. */
    fun cancel() {
        job?.cancel()
        job = null
    }
}
