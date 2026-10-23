package com.raddstream.app.data.cache

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The flagship guarantee: a user watched 70 of 130 minutes, taps "keep this", and the app
 * continues downloading from where the buffer already is — it never re-fetches from byte 0.
 */
class HandoffAccountingTest {

    // 1.3 MB / 130 min gives an exact 100 bytes per second for crisp assertions.
    private val total = 1_300_000L
    private val durationSec = 7_800.0 // 130 * 60

    @Test
    fun `70 of 130 minutes kept resumes at the buffer head and re-fetches zero held bytes`() {
        // The ahead-of-playback fetcher runs ~5 min ahead of the 70-minute playhead.
        val playMinutes = 70.0
        val bufferedMinutes = 75.0
        val mapping = CoverageMapping.simple(total, durationSec)
        val playBytes = mapping.fileByteAt(playMinutes * 60)
        val bufferedBytes = mapping.fileByteAt(bufferedMinutes * 60)

        val ledger = IntervalLedger()
        ledger.add(0, bufferedBytes) // contiguous forward buffer is what we hold

        val plan = HandoffAccounting.plan(
            HandoffRequest(
                totalSizeBytes = total,
                ledger = ledger,
                playPositionBytes = playBytes,
                verifiedPrefixBytes = ledger.verifiedPrefix(),
            )
        )

        // Continues from exactly where the buffer ended, not from 0 and not from the playhead.
        assertEquals(bufferedBytes, plan.resumeFromByte)
        assertTrue(plan.resumeFromByte >= playBytes)

        // The whole remaining tail is the only thing fetched; the head is adopted.
        assertEquals(1, plan.resumeRanges.size)
        assertEquals(bufferedBytes, plan.resumeRanges.first().start)
        assertEquals(total, plan.resumeRanges.first().end)
        assertEquals(total - bufferedBytes, plan.bytesToFetch)

        // Nothing already held would be re-downloaded.
        assertEquals(bufferedBytes, plan.bytesSaved)
        assertEquals(ResumeToken.wastedBytesIfRestartedFromZero(total, ledger), plan.bytesSaved)

        // And the accounting invariant: fetched + held == total, exactly the gaps.
        assertEquals(total, plan.bytesToFetch + plan.alreadyHeldBytes)
        assertTrue(plan.refetchIsExactlyTheGaps())
        assertFalse(plan.completionDetected)
    }

    @Test
    fun `non contiguous buffer still re-fetches only the gaps`() {
        val ledger = IntervalLedger()
        ledger.add(0, 300_000)
        ledger.add(500_000, 800_000) // a hole at [300k,500k) and tail [800k,total)
        val plan = HandoffAccounting.plan(
            HandoffRequest(total, ledger, playPositionBytes = 100_000, verifiedPrefixBytes = 300_000)
        )
        assertEquals(listOf(ByteInterval(300_000, 500_000), ByteInterval(800_000, total)), plan.resumeRanges)
        assertEquals(total - ledger.coveredBytesWithin(total), plan.bytesToFetch)
        assertEquals(300_000L, plan.resumeFromByte)
    }

    @Test
    fun `already complete file yields empty resume plan and completion flag`() {
        val ledger = IntervalLedger()
        ledger.add(0, total)
        val plan = HandoffAccounting.plan(
            HandoffRequest(total, ledger, playPositionBytes = 10, verifiedPrefixBytes = total)
        )
        assertTrue(plan.resumeRanges.isEmpty())
        assertEquals(0L, plan.bytesToFetch)
        assertEquals(total, plan.alreadyHeldBytes)
        assertTrue(plan.completionDetected)
        assertEquals(total, plan.resumeFromByte)
    }

    @Test
    fun `unknown total size (ephemeral with no content-length) yields empty plan not full restart`() {
        val ledger = IntervalLedger()
        ledger.add(0, 1234)
        val plan = HandoffAccounting.plan(
            HandoffRequest(0, ledger, playPositionBytes = 0, verifiedPrefixBytes = 1234)
        )
        assertTrue(plan.resumeRanges.isEmpty())
        assertTrue(plan.completionDetected) // total<=0 is treated as trivially satisfied
        assertEquals(0L, plan.bytesToFetch)
    }

    @Test
    fun `reverse case - partial download resumed after restart reads from persisted token`() {
        // Before restart we had buffered [0,600k). We persist a token.
        val before = IntervalLedger()
        before.add(0, 600_000)
        val token = ResumeToken("digest", total, 2L, before).encode()

        // After restart we only have the token; the plan must resume from 600k, not 0.
        val decoded = ResumeToken.decode(token)!!
        val ranges = ResumeToken.resumeRanges(decoded, expectedDigest = "digest")
        assertEquals(listOf(ByteInterval(600_000, total)), ranges)
        assertEquals(600_000L, ranges.first().start)
    }
}
