package com.raddstream.app.data.cache

import org.junit.Assert.assertEquals
import org.junit.Test

class TtlPolicyTest {

    private fun snapshot(
        origin: CacheOrigin,
        created: Long,
        temp: Boolean = false,
        running: Boolean = false,
    ) = FileSnapshot(
        fileId = "f1",
        origin = origin,
        createdElapsedRealtime = created,
        lastAccessElapsedRealtime = created,
        sizeBytes = 1_000_000L,
        isTemporary = temp,
        referencedByRunningTask = running,
    )

    @Test
    fun `user kept file is never auto-deleted even after many hours`() {
        val file = snapshot(CacheOrigin.USER_KEEP, created = 0L)
        val v = TtlPolicy.evaluate(file, nowElapsedRealtime = 100L * 3_600_000L, ttl = TtlHours.THREE)
        assertEquals(TtlDecision.KEEP, v.decision)
        assertEquals(TtlReason.USER_KEPT, v.reason)
    }

    @Test
    fun `auto preview within ttl is kept`() {
        val file = snapshot(CacheOrigin.AUTO_PREVIEW, created = 0L)
        val v = TtlPolicy.evaluate(file, nowElapsedRealtime = 2L * 3_600_000L, ttl = TtlHours.THREE)
        assertEquals(TtlDecision.KEEP, v.decision)
        assertEquals(TtlReason.WITHIN_TTL, v.reason)
    }

    @Test
    fun `auto preview past ttl expires`() {
        val file = snapshot(CacheOrigin.AUTO_PREVIEW, created = 0L)
        val v = TtlPolicy.evaluate(file, nowElapsedRealtime = 4L * 3_600_000L, ttl = TtlHours.THREE)
        assertEquals(TtlDecision.EXPIRE, v.decision)
        assertEquals(TtlReason.EXPIRED, v.reason)
    }

    @Test
    fun `six hour setting does not expire at four hours`() {
        val file = snapshot(CacheOrigin.AUTO_PREVIEW, created = 0L)
        val v = TtlPolicy.evaluate(file, nowElapsedRealtime = 4L * 3_600_000L, ttl = TtlHours.SIX)
        assertEquals(TtlDecision.KEEP, v.decision)
    }

    @Test
    fun `file held by a running task is deferred not deleted`() {
        val file = snapshot(CacheOrigin.AUTO_PREVIEW, created = 0L, running = true)
        val v = TtlPolicy.evaluate(file, nowElapsedRealtime = 100L * 3_600_000L, ttl = TtlHours.THREE)
        assertEquals(TtlDecision.DEFER, v.decision)
        assertEquals(TtlReason.HELD_BY_RUNNING_TASK, v.reason)
    }

    @Test
    fun `orphaned temp file leaks are swept after the grace window`() {
        val file = snapshot(CacheOrigin.AUTO_PREVIEW, created = 0L, temp = true)
        val within = TtlPolicy.evaluate(file, TtlPolicy.TEMP_GRACE_MILLIS - 1, TtlHours.THREE)
        assertEquals(TtlDecision.KEEP, within.decision)
        assertEquals(TtlReason.TEMP_GRACE_ACTIVE, within.reason)

        val after = TtlPolicy.evaluate(file, TtlPolicy.TEMP_GRACE_MILLIS + 1, TtlHours.THREE)
        assertEquals(TtlDecision.EXPIRE, after.decision)
        assertEquals(TtlReason.ORPHANED_TEMP, after.reason)
    }

    @Test
    fun `millisUntilDue is zero once due and correct before`() {
        val file = snapshot(CacheOrigin.AUTO_PREVIEW, created = 10_000L)
        assertEquals(
            TtlHours.SIX.millis - 5_000L,
            TtlPolicy.millisUntilDue(file, nowElapsedRealtime = 15_000L, ttl = TtlHours.SIX),
        )
        assertEquals(
            0L,
            TtlPolicy.millisUntilDue(file, nowElapsedRealtime = file.createdElapsedRealtime + TtlHours.SIX.millis + 1, ttl = TtlHours.SIX),
        )
        assertEquals(
            Long.MAX_VALUE,
            TtlPolicy.millisUntilDue(snapshot(CacheOrigin.USER_KEEP, 0L), 1_000L, TtlHours.THREE),
        )
    }

    @Test
    fun `clock never goes backwards - age clamps negative elapsed to zero`() {
        val file = snapshot(CacheOrigin.AUTO_PREVIEW, created = 50_000L)
        // now earlier than created (uptime anomaly): age treated as 0, kept.
        val v = TtlPolicy.evaluate(file, nowElapsedRealtime = 10_000L, ttl = TtlHours.THREE)
        assertEquals(TtlDecision.KEEP, v.decision)
    }

    @Test
    fun `ttl hours from user setting clamps`() {
        assertEquals(TtlHours.THREE, TtlHours.fromHours(1))
        assertEquals(TtlHours.THREE, TtlHours.fromHours(3))
        assertEquals(TtlHours.SIX, TtlHours.fromHours(4))
        assertEquals(TtlHours.SIX, TtlHours.fromHours(12))
    }

    @Test
    fun `fixed uptime clock drives an end to end expiry`() {
        val clock = FixedUptimeClock(0L)
        val file = snapshot(CacheOrigin.AUTO_PREVIEW, created = clock.nowElapsedRealtime())
        assertEquals(TtlDecision.KEEP, TtlPolicy.evaluate(file, clock.nowElapsedRealtime(), TtlHours.THREE).decision)
        clock.advance(4L * 3_600_000L)
        assertEquals(TtlDecision.EXPIRE, TtlPolicy.evaluate(file, clock.nowElapsedRealtime(), TtlHours.THREE).decision)
    }
}
