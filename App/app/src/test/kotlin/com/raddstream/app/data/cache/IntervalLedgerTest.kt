package com.raddstream.app.data.cache

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class IntervalLedgerTest {

    @Test
    fun `empty interval is ignored`() {
        val l = IntervalLedger()
        l.add(50, 50)
        assertTrue(l.intervals.isEmpty())
        assertEquals(0L, l.coveredBytes())
    }

    @Test
    fun `single interval is stored as given`() {
        val l = IntervalLedger()
        l.add(0, 100)
        assertEquals(listOf(ByteInterval(0, 100)), l.intervals)
        assertEquals(100L, l.coveredBytes())
    }

    @Test
    fun `adjacent intervals merge`() {
        val l = IntervalLedger()
        l.add(0, 100)
        l.add(100, 200)
        assertEquals(listOf(ByteInterval(0, 200)), l.intervals)
        assertEquals(200L, l.coveredBytes())
    }

    @Test
    fun `overlapping intervals merge without double counting`() {
        val l = IntervalLedger()
        l.add(0, 100)
        l.add(50, 150)
        assertEquals(listOf(ByteInterval(0, 150)), l.intervals)
        // Naive sum of lengths would be 200; the disjoint merge must be 150.
        assertEquals(150L, l.coveredBytes())
    }

    @Test
    fun `contained interval collapses`() {
        val l = IntervalLedger()
        l.add(0, 1000)
        l.add(400, 500)
        assertEquals(listOf(ByteInterval(0, 1000)), l.intervals)
        assertEquals(1000L, l.coveredBytes())
    }

    @Test
    fun `out of order arrival still produces canonical sorted disjoint list`() {
        val l = IntervalLedger()
        l.add(300, 400)
        l.add(0, 100)
        l.add(200, 300) // touches 300 -> merges with [300,400)
        l.add(150, 160)
        assertEquals(
            listOf(ByteInterval(0, 100), ByteInterval(150, 160), ByteInterval(200, 400)),
            l.intervals,
        )
        assertEquals(100L + 10L + 200L, l.coveredBytes())
    }

    @Test
    fun `gaps reports holes within total`() {
        val l = IntervalLedger()
        l.add(0, 100)
        l.add(200, 250)
        val gaps = l.gaps(300)
        assertEquals(listOf(ByteInterval(100, 200), ByteInterval(250, 300)), gaps)
    }

    @Test
    fun `gaps reports the leading hole when the prefix is missing`() {
        val l = IntervalLedger()
        l.add(100, 200)
        // bytes 0..100 and 200..250 are both missing
        assertEquals(
            listOf(ByteInterval(0, 100), ByteInterval(200, 250)),
            l.gaps(250),
        )
    }

    @Test
    fun `verifiedPrefix stops at first hole`() {
        val l = IntervalLedger()
        l.add(0, 100)
        l.add(150, 200)
        assertEquals(100L, l.verifiedPrefix())
    }

    @Test
    fun `verifiedPrefix is zero when start missing`() {
        val l = IntervalLedger()
        l.add(50, 100)
        assertEquals(0L, l.verifiedPrefix())
    }

    @Test
    fun `firstMissing returns lowest gap start`() {
        val l = IntervalLedger()
        l.add(0, 100)
        l.add(200, 300)
        assertEquals(100L, l.firstMissing(400))
    }

    @Test
    fun `firstMissing null when complete`() {
        val l = IntervalLedger()
        l.add(0, 400)
        assertNull(l.firstMissing(400))
    }

    @Test
    fun `completion detection via gaps and via prefix`() {
        val l = IntervalLedger()
        l.add(0, 500)
        assertTrue(l.isComplete(500))
        assertTrue(l.isContiguousComplete(500))
        assertFalse(l.isComplete(501))
    }

    @Test
    fun `non contiguous completion still counts as complete`() {
        val l = IntervalLedger()
        l.add(0, 250)
        l.add(250, 500) // merges -> complete
        assertTrue(l.isComplete(500))
        assertTrue(l.isContiguousComplete(500))
    }

    @Test
    fun `missingWithin intersect excludes already held bytes`() {
        val l = IntervalLedger()
        l.add(0, 100)
        l.add(150, 200)
        // We want the window [50, 250). Already held inside it: [50,100) and [150,200).
        val missing = l.missingWithin(50, 250)
        assertEquals(listOf(ByteInterval(100, 150), ByteInterval(200, 250)), missing)
    }

    @Test
    fun `isCovered and contains`() {
        val l = IntervalLedger()
        l.add(100, 200)
        assertTrue(l.isCovered(100))
        assertTrue(l.isCovered(199))
        assertFalse(l.isCovered(200)) // end exclusive
        assertFalse(l.isCovered(99))
    }

    @Test
    fun `nextContiguousEnd extends read window from offset`() {
        val l = IntervalLedger()
        l.add(0, 300)
        assertEquals(300L, l.nextContiguousEnd(100))
        // The documented contract for an uncovered offset is "returns offset", i.e. 500 here.
        assertEquals(500L, l.nextContiguousEnd(500)) // not covered -> returns offset
    }
}
