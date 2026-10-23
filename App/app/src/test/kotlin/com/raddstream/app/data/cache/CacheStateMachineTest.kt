package com.raddstream.app.data.cache

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class CacheStateMachineTest {

    @Test
    fun `normal happy path transitions are allowed`() {
        assertTrue(CacheTaskStateMachine.canTransition(CacheTaskState.QUEUED, CacheTaskState.LOADING))
        assertTrue(CacheTaskStateMachine.canTransition(CacheTaskState.LOADING, CacheTaskState.COMPLETED))
        assertTrue(CacheTaskStateMachine.canTransition(CacheTaskState.COMPLETED, CacheTaskState.EXPIRED))
        assertTrue(CacheTaskStateMachine.canTransition(CacheTaskState.EXPIRED, CacheTaskState.DELETED))
    }

    @Test
    fun `requireTransition returns the target when legal`() {
        assertEquals(
            CacheTaskState.LOADING,
            CacheTaskStateMachine.requireTransition(CacheTaskState.QUEUED, CacheTaskState.LOADING),
        )
    }

    @Test
    fun `cannot complete without loading`() {
        assertFalse(CacheTaskStateMachine.canTransition(CacheTaskState.QUEUED, CacheTaskState.COMPLETED))
        assertThrows(IllegalStateTransition::class.java) {
            CacheTaskStateMachine.requireTransition(CacheTaskState.QUEUED, CacheTaskState.COMPLETED)
        }
    }

    @Test
    fun `a killed loading task can be re-queued to resume not restart`() {
        assertTrue(CacheTaskStateMachine.canTransition(CacheTaskState.LOADING, CacheTaskState.QUEUED))
        assertTrue(CacheTaskStateMachine.canTransition(CacheTaskState.LOADING, CacheTaskState.PAUSED))
        assertTrue(CacheTaskStateMachine.canTransition(CacheTaskState.PAUSED, CacheTaskState.LOADING))
    }

    @Test
    fun `deleted is terminal - nothing is allowed out of it`() {
        for (s in CacheTaskStateMachine.allStates) {
            assertFalse(CacheTaskStateMachine.canTransition(CacheTaskState.DELETED, s))
        }
    }

    @Test
    fun `expired file re-arms to queued when still referenced but never back to loading directly`() {
        assertTrue(CacheTaskStateMachine.canTransition(CacheTaskState.EXPIRED, CacheTaskState.QUEUED))
        assertTrue(CacheTaskStateMachine.canTransition(CacheTaskState.EXPIRED, CacheTaskState.DELETED))
        assertFalse(CacheTaskStateMachine.canTransition(CacheTaskState.EXPIRED, CacheTaskState.LOADING))
    }

    @Test
    fun `completed never goes back to loading`() {
        assertFalse(CacheTaskStateMachine.canTransition(CacheTaskState.COMPLETED, CacheTaskState.LOADING))
        assertFalse(CacheTaskStateMachine.canTransition(CacheTaskState.COMPLETED, CacheTaskState.QUEUED))
    }

    @Test
    fun `running task holders are exactly queued and loading`() {
        assertTrue(CacheTaskStateMachine.holdsRunningTask(CacheTaskState.QUEUED))
        assertTrue(CacheTaskStateMachine.holdsRunningTask(CacheTaskState.LOADING))
        assertFalse(CacheTaskStateMachine.holdsRunningTask(CacheTaskState.PAUSED))
        assertFalse(CacheTaskStateMachine.holdsRunningTask(CacheTaskState.COMPLETED))
        assertFalse(CacheTaskStateMachine.holdsRunningTask(CacheTaskState.FAILED))
    }

    @Test
    fun `self transitions are rejected`() {
        assertFalse(CacheTaskStateMachine.canTransition(CacheTaskState.LOADING, CacheTaskState.LOADING))
    }
}

class RetryPolicyTest {

    @Test
    fun `zero or negative attempt schedules nothing`() {
        assertEquals(0L, RetryPolicy.backoffCeilingMs(0))
        assertEquals(0L, RetryPolicy.nextRetryDelayMs(0, 123L))
    }

    @Test
    fun `backoff grows exponentially per attempt`() {
        assertEquals(2_000L, RetryPolicy.backoffCeilingMs(1))
        assertEquals(4_000L, RetryPolicy.backoffCeilingMs(2))
        assertEquals(8_000L, RetryPolicy.backoffCeilingMs(3))
    }

    @Test
    fun `backoff is capped`() {
        assertEquals(30L * 60_000L, RetryPolicy.backoffCeilingMs(40))
    }

    @Test
    fun `attempts exhaust at the max`() {
        assertFalse(RetryPolicy.isExhausted(RetryPolicy.MAX_ATTEMPTS - 1))
        assertTrue(RetryPolicy.isExhausted(RetryPolicy.MAX_ATTEMPTS))
    }

    @Test
    fun `retry delay stays within window`() {
        for (attempt in 1..8) {
            val ceiling = RetryPolicy.backoffCeilingMs(attempt)
            val delay = RetryPolicy.nextRetryDelayMs(attempt, seed(attempt))
            assertTrue("delay>=base", delay >= 2_000L)
            assertTrue("delay<=ceiling", delay <= ceiling)
        }
    }

    @Test
    fun `delay is deterministic for the same seed`() {
        val a = RetryPolicy.nextRetryDelayMs(3, 999_999L)
        val b = RetryPolicy.nextRetryDelayMs(3, 999_999L)
        assertEquals(a, b)
    }

    private fun seed(i: Int): Long = i.toLong() * 265_443_5761L
}
