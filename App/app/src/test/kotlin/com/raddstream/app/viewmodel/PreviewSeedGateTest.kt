package com.raddstream.app.viewmodel

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pre-resolve better (2026-11-13): the seed waits out the linger before a
 * single byte moves, and leaving first means it never runs.
 *
 * Plain JUnit4, no Robolectric, no virtual time: the gate's wait is an
 * injected sleeper, so the test holds it open with a [CompletableDeferred]
 * and releases it exactly when it wants to — the temporal rule is pinned
 * without sleeping 3 s. The scope is [Dispatchers.Unconfined], so a
 * scheduled job runs inline up to the sleeper and resumes inline when the
 * sleeper is released; nothing here depends on a scheduler.
 */
class PreviewSeedGateTest {

    /** One held-open wait: records the linger asked for, runs nothing until released. */
    private class HeldSleeper {
        val askedMs = mutableListOf<Long>()
        val gate = CompletableDeferred<Unit>()

        suspend fun sleep(ms: Long) {
            askedMs.add(ms)
            gate.await()
        }

        fun release() {
            gate.complete(Unit)
        }
    }

    private fun gateWith(sleeper: HeldSleeper): PreviewSeedGate =
        PreviewSeedGate(
            scope = CoroutineScope(Dispatchers.Unconfined + SupervisorJob()),
            lingerMs = PREVIEW_SEED_LINGER_MS,
            sleeper = { ms -> sleeper.sleep(ms) },
        )

    @Test
    fun `the seed does not start before the linger elapses`() = runBlocking {
        val sleeper = HeldSleeper()
        val gate = gateWith(sleeper)
        var seeded = false

        gate.schedule(stillWanted = { true }, seed = { seeded = true })

        // The job is inside the wait: the linger was asked for, nothing seeded.
        assertEquals(listOf(PREVIEW_SEED_LINGER_MS), sleeper.askedMs)
        assertEquals("no byte moves before the linger", false, seeded)

        sleeper.release()
        // Unconfined resumes inline: the re-check passes and the seed runs.
        assertTrue("the seed runs once the linger elapses", seeded)
    }

    @Test
    fun `leaving before the linger means the seed never runs`() = runBlocking {
        val sleeper = HeldSleeper()
        val gate = gateWith(sleeper)
        var seeded = false

        gate.schedule(stillWanted = { true }, seed = { seeded = true })
        // The viewer leaves: the pending wait is cancelled outright.
        gate.cancel()
        sleeper.release()

        assertEquals("a cancelled wait must not seed when it is released", false, seeded)
    }

    @Test
    fun `a re-check that fails after the linger means no seed`() = runBlocking {
        val sleeper = HeldSleeper()
        val gate = gateWith(sleeper)
        var seeded = false

        // The bundle was superseded (or wifi dropped) during the wait.
        gate.schedule(stillWanted = { false }, seed = { seeded = true })
        sleeper.release()

        assertEquals("the re-check is the second line of defence", false, seeded)
    }

    @Test
    fun `re-scheduling supersedes the pending seed`() = runBlocking {
        val first = HeldSleeper()
        val second = HeldSleeper()
        var seeds = 0
        val gate = PreviewSeedGate(
            scope = CoroutineScope(Dispatchers.Unconfined + SupervisorJob()),
            lingerMs = PREVIEW_SEED_LINGER_MS,
            sleeper = { ms ->
                // Each schedule gets its own held wait, in order.
                if (first.askedMs.isEmpty()) first.sleep(ms) else second.sleep(ms)
            },
        )

        gate.schedule(stillWanted = { true }, seed = { seeds++ })
        // A newer detail load re-arms the gate: the first wait is cancelled.
        gate.schedule(stillWanted = { true }, seed = { seeds++ })

        first.release()
        assertEquals("the superseded wait must not seed", 0, seeds)
        second.release()
        assertEquals("only the latest schedule seeds, exactly once", 1, seeds)
    }
}
