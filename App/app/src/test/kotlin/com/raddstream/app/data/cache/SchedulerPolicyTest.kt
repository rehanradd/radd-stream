package com.raddstream.app.data.cache

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SchedulerPolicyTest {

    private fun task(
        id: Long,
        priority: CachePriority,
        remaining: Long = 1_000L,
        enqueued: Long = 0L,
        running: Boolean = false,
    ) = SchedulableTask(id, priority, remaining, enqueued, running)

    @Test
    fun `concurrency cap is never exceeded`() {
        val tasks = listOf(
            task(1, CachePriority.USER_REQUESTED),
            task(2, CachePriority.USER_REQUESTED),
            task(3, CachePriority.AUTO_PREVIEW),
        )
        val d = SchedulerPolicySelector.select(tasks, NetworkClass.WIFI, SchedulerPolicy(maxConcurrent = 2))
        assertEquals(2, d.startTaskIds.size)
    }

    @Test
    fun `user requested always scheduled before auto preview`() {
        val tasks = listOf(
            task(10, CachePriority.AUTO_PREVIEW, enqueued = 0L),   // enqueued earlier
            task(20, CachePriority.USER_REQUESTED, enqueued = 5L), // but user wins
        )
        val d = SchedulerPolicySelector.select(tasks, NetworkClass.WIFI, SchedulerPolicy(maxConcurrent = 1))
        assertEquals(listOf(20L), d.startTaskIds)
    }

    @Test
    fun `user preempts a running auto preview when the pool is full`() {
        val tasks = listOf(
            task(1, CachePriority.AUTO_PREVIEW, running = true),
            task(2, CachePriority.USER_REQUESTED),
        )
        val d = SchedulerPolicySelector.select(tasks, NetworkClass.WIFI, SchedulerPolicy(maxConcurrent = 1))
        assertEquals(listOf(1L), d.preemptTaskIds)
        assertTrue(d.reason.contains("preempt") || d.reason == "pool_full" || d.reason == "user_tasks_preempt_auto_preview")
    }

    @Test
    fun `auto preview is not started on mobile unless allowed`() {
        val tasks = listOf(
            task(1, CachePriority.AUTO_PREVIEW),
            task(2, CachePriority.USER_REQUESTED),
        )
        val d = SchedulerPolicySelector.select(tasks, NetworkClass.MOBILE, SchedulerPolicy(maxConcurrent = 2, allowAutoPreviewOnMobile = false))
        assertEquals(listOf(2L), d.startTaskIds) // only the user task starts
        assertFalse(d.startTaskIds.contains(1L))
    }

    @Test
    fun `auto preview runs on mobile when the user opted in`() {
        val tasks = listOf(task(1, CachePriority.AUTO_PREVIEW))
        val d = SchedulerPolicySelector.select(tasks, NetworkClass.MOBILE, SchedulerPolicy(maxConcurrent = 2, allowAutoPreviewOnMobile = true))
        assertEquals(listOf(1L), d.startTaskIds)
    }

    @Test
    fun `nothing starts with no network`() {
        val tasks = listOf(task(1, CachePriority.USER_REQUESTED))
        val d = SchedulerPolicySelector.select(tasks, NetworkClass.NONE, SchedulerPolicy())
        assertTrue(d.startTaskIds.isEmpty())
        assertEquals("no_network", d.reason)
    }

    @Test
    fun `auto preview over the data budget is throttled`() {
        val tasks = listOf(task(1, CachePriority.AUTO_PREVIEW, remaining = 5_000L))
        val policy = SchedulerPolicy(
            maxConcurrent = 2,
            autoPreviewDataBudgetBytes = 1_000L,
            autoPreviewBytesSpentThisPeriod = 0L,
        )
        val d = SchedulerPolicySelector.select(tasks, NetworkClass.WIFI, policy)
        assertEquals(listOf(1L), d.throttledAutoPreviewIds)
        assertTrue(d.startTaskIds.isEmpty())
    }

    @Test
    fun `roaming metered blocks auto preview entirely`() {
        val tasks = listOf(task(1, CachePriority.AUTO_PREVIEW))
        val d = SchedulerPolicySelector.select(tasks, NetworkClass.METERED_ROAMING, SchedulerPolicy(maxConcurrent = 2, allowAutoPreviewOnMobile = true))
        assertTrue(d.startTaskIds.isEmpty())
    }

    @Test
    fun `first in first served within the same band`() {
        val tasks = listOf(
            task(30, CachePriority.USER_REQUESTED, enqueued = 100L),
            task(40, CachePriority.USER_REQUESTED, enqueued = 10L),
        )
        val d = SchedulerPolicySelector.select(tasks, NetworkClass.WIFI, SchedulerPolicy(maxConcurrent = 1))
        assertEquals(listOf(40L), d.startTaskIds) // oldest first
    }

    @Test
    fun `preemption pauses the least progressed auto preview first`() {
        val tasks = listOf(
            task(1, CachePriority.AUTO_PREVIEW, remaining = 10_000L, running = true), // far from done
            task(2, CachePriority.AUTO_PREVIEW, remaining = 500L, running = true),    // almost done
            task(3, CachePriority.USER_REQUESTED),
        )
        val d = SchedulerPolicySelector.select(tasks, NetworkClass.WIFI, SchedulerPolicy(maxConcurrent = 2))
        // free slots = 0; userDemand = 1; pause the one with most remaining bytes = task 1
        assertEquals(listOf(1L), d.preemptTaskIds)
    }
}
