package com.raddstream.app.data.cache

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class EvictionPlannerTest {

    private fun cand(
        id: String,
        size: Long,
        origin: CacheOrigin = CacheOrigin.AUTO_PREVIEW,
        lastAccess: Long = 0L,
        watch: Int = 0,
        running: Boolean = false,
        temp: Boolean = false,
        complete: Boolean = true,
    ) = EvictionCandidate(id, size, origin, lastAccess, watch, running, temp, complete)

    @Test
    fun `user kept and running-task files are never evicted`() {
        val candidates = listOf(
            cand("keep-user", 100, origin = CacheOrigin.USER_KEEP),
            cand("keep-running", 100, running = true),
            cand("evictable", 100),
        )
        val plan = EvictionPlanner.plan(candidates, bytesToFree = 100, nowElapsedRealtime = 0L)
        assertEquals(listOf("evictable"), plan.deletions.map { it.fileId })
        assertTrue(plan.sufficient)
        assertEquals(200L, plan.protectedBytesRetained)
    }

    @Test
    fun `least useful files are evicted first`() {
        val candidates = listOf(
            cand("junk-temp", 10, temp = true, complete = false),
            cand("incomplete", 10, complete = false),
            cand("old-zero-watch", 10, lastAccess = 0L, watch = 0),
            cand("recent-watched", 10, lastAccess = 999_999L, watch = 5),
        )
        val ordered = EvictionPlanner.orderedForEviction(candidates, nowElapsedRealtime = 1_000_000L)
        // temp junk first, then incomplete, then oldest-zero-watch, most-useful last.
        assertEquals("junk-temp", ordered.first().fileId)
        assertEquals("recent-watched", ordered.last().fileId)
    }

    @Test
    fun `more recently touched beats idle of same watch count`() {
        val idle = cand("idle", 10, lastAccess = 0L, watch = 1)
        val fresh = cand("fresh", 10, lastAccess = 999_999L, watch = 1)
        val ordered = EvictionPlanner.orderedForEviction(listOf(idle, fresh), nowElapsedRealtime = 1_000_000L)
        assertEquals(listOf("idle", "fresh"), ordered.map { it.fileId })
    }

    @Test
    fun `full disk frees enough by deleting least useful until target met`() {
        val candidates = listOf(
            cand("a", 300, temp = true, complete = false),
            cand("b", 300, watch = 0, lastAccess = 0L),
            cand("c", 5000, watch = 20, lastAccess = 1_000_000L),
        )
        val plan = EvictionPlanner.plan(candidates, bytesToFree = 500, nowElapsedRealtime = 1_000_000L)
        assertTrue(plan.sufficient)
        // frees the two least useful (300+300) and stops before touching the prized file c
        assertEquals(listOf("a", "b"), plan.deletions.map { it.fileId })
        assertEquals(600L, plan.freedBytes)
        assertFalse(plan.deletions.any { it.fileId == "c" })
    }

    @Test
    fun `insufficient evictable headroom is reported not forced`() {
        val candidates = listOf(
            cand("protected", 1000, origin = CacheOrigin.USER_KEEP),
            cand("small", 50),
        )
        val plan = EvictionPlanner.plan(candidates, bytesToFree = 10_000, nowElapsedRealtime = 0L)
        assertFalse(plan.sufficient)
        assertEquals(listOf("small"), plan.deletions.map { it.fileId })
    }

    @Test
    fun `admit rejects when a single file exceeds the per-file cap`() {
        val limits = StorageLimits(hardCeilingBytes = 10_000_000, lowStorageFloorBytes = 1_000, perFileMaxBytes = 2_000_000)
        val decision = EvictionPlanner.admit(
            requestedBytes = 3_000_000,
            currentUsedBytes = 0,
            osFreeBytes = 100_000_000,
            limits = limits,
            candidates = emptyList(),
            nowElapsedRealtime = 0L,
        )
        assertTrue(decision is AdmitDecision.RejectPerFileCap)
    }

    @Test
    fun `admit rejects when it would breach the hard ceiling`() {
        val limits = StorageLimits(hardCeilingBytes = 5_000_000, lowStorageFloorBytes = 1_000, perFileMaxBytes = 10_000_000)
        val decision = EvictionPlanner.admit(
            requestedBytes = 2_000_000,
            currentUsedBytes = 4_000_000, // only 1MB headroom under the ceiling
            osFreeBytes = 100_000_000,
            limits = limits,
            candidates = emptyList(),
            nowElapsedRealtime = 0L,
        )
        assertTrue(decision is AdmitDecision.RejectTooBigForCeiling)
    }

    @Test
    fun `admit evicts then admits when os free space is below the floor`() {
        val limits = StorageLimits(hardCeilingBytes = 10_000_000, lowStorageFloorBytes = 500, perFileMaxBytes = 10_000_000)
        val candidates = listOf(
            cand("evict-me", 1000, temp = true, complete = false),
            cand("prized", 999_999, watch = 10, lastAccess = 1L),
        )
        val decision = EvictionPlanner.admit(
            requestedBytes = 100,
            currentUsedBytes = 0,
            osFreeBytes = 200, // below the 500 floor -> must free 300 bytes
            limits = limits,
            candidates = candidates,
            nowElapsedRealtime = 0L,
        )
        assertTrue(decision is AdmitDecision.EvictThenAdmit)
        val plan = (decision as AdmitDecision.EvictThenAdmit).plan
        assertTrue(plan.sufficient)
        assertTrue(plan.deletions.map { it.fileId }.contains("evict-me"))
    }

    @Test
    fun `admit refuses when even eviction cannot clear the floor`() {
        val limits = StorageLimits(hardCeilingBytes = 10_000_000, lowStorageFloorBytes = 10_000, perFileMaxBytes = 10_000_000)
        val candidates = listOf(cand("tiny", 50), cand("kept", 1_000_000, origin = CacheOrigin.USER_KEEP))
        val decision = EvictionPlanner.admit(
            requestedBytes = 100,
            currentUsedBytes = 0,
            osFreeBytes = 0,
            limits = limits,
            candidates = candidates,
            nowElapsedRealtime = 0L,
        )
        assertTrue(decision is AdmitDecision.RejectNoEvictableHeadroom)
    }

    @Test
    fun `admit allows a zero or negative request`() {
        val limits = StorageLimits(hardCeilingBytes = 100, lowStorageFloorBytes = 100, perFileMaxBytes = 100)
        assertTrue(EvictionPlanner.admit(0, 0, 0, limits, emptyList(), 0L) is AdmitDecision.Admit)
    }
}
