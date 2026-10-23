package com.raddstream.app.data.cache

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ResumeTokenTest {

    @Test
    fun `encode then decode round trips the ledger and metadata`() {
        val ledger = IntervalLedger()
        ledger.add(0, 1000)
        ledger.add(1500, 2000)
        val token = ResumeToken("abcd1234", 3000L, 7L, ledger)
        val decoded = ResumeToken.decode(token.encode())
        assertNotNull(decoded)
        decoded!!.let {
            assertEquals("abcd1234", it.identityDigest)
            assertEquals(3000L, it.totalSizeBytes)
            assertEquals(7L, it.revision)
            assertEquals(ledger.intervals, it.ledger.intervals)
        }
    }

    @Test
    fun `empty ledger encodes to decodable token`() {
        val token = ResumeToken("hash", 5000L, 1L, IntervalLedger())
        val decoded = ResumeToken.decode(token.encode())
        assertNotNull(decoded)
        assertTrue(decoded!!.ledger.intervals.isEmpty())
    }

    @Test
    fun `malformed token is rejected not trusted`() {
        assertNull(ResumeToken.decode("v1|only|three"))
        assertNull(ResumeToken.decode("v2|hash|100|0|-"))      // wrong version
        assertNull(ResumeToken.decode("v1||100|0|-"))          // blank digest
        assertNull(ResumeToken.decode("v1|hash|notanumber|0|-"))
        assertNull(ResumeToken.decode("v1|hash|100|0|5-2"))    // end < start
        assertNull(ResumeToken.decode("v1|hash|100|0|a-b"))    // non numeric range
    }

    @Test
    fun `resumeRanges with matching digest only asks for gaps`() {
        val ledger = IntervalLedger()
        ledger.add(0, 1000)
        val token = ResumeToken("same", 1500L, 3L, ledger)
        val ranges = ResumeToken.resumeRanges(token, expectedDigest = "same")
        assertEquals(listOf(ByteInterval(1000, 1500)), ranges)
    }

    @Test
    fun `resumeRanges with different digest refuses to reuse bytes and re-fetches all`() {
        val ledger = IntervalLedger()
        ledger.add(0, 1000)
        val token = ResumeToken("old", 1500L, 3L, ledger)
        val ranges = ResumeToken.resumeRanges(token, expectedDigest = "new")
        // identity changed -> do NOT adopt the stale bytes; full range requested
        assertEquals(listOf(ByteInterval(0, 1500)), ranges)
    }

    @Test
    fun `keepPlan totals equal the remaining bytes and never overlap held ranges`() {
        val total = 1000L
        val ledger = IntervalLedger()
        ledger.add(0, 400)
        ledger.add(500, 700)
        val plan = ResumeToken.keepPlan(total, ledger)
        val planBytes = plan.sumOf { it.length }
        val held = ledger.coveredBytesWithin(total)
        assertEquals(total - held, planBytes)
        // no plan range overlaps any held range
        for (p in plan) {
            for (h in ledger.intervals) {
                org.junit.Assert.assertFalse(p.overlaps(h))
            }
        }
    }

    @Test
    fun `wastedIfRestartedFromZero equals bytes already held`() {
        val ledger = IntervalLedger()
        ledger.add(0, 700)
        assertEquals(700L, ResumeToken.wastedBytesIfRestartedFromZero(1000L, ledger))
    }
}
