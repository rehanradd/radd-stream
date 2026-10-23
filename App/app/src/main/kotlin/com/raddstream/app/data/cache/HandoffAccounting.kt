package com.raddstream.app.data.cache

/**
 * The pure accounting behind the "zero-waste handoff" the player triggers when the user taps
 * "keep this" mid-playback, and behind the reverse case (a partial download resumed after a
 * restart or a network change).
 *
 * Everything here is byte-math over the [IntervalLedger]; there is no Android and no network,
 * so the flagship "70 of 130 minutes watched → resume from 70, never from 0" guarantee is a
 * unit test, not a hope.
 */
data class HandoffRequest(
    val totalSizeBytes: Long,
    val ledger: IntervalLedger,
    /** Absolute byte offset the player is currently at (from [CoverageMapping]). */
    val playPositionBytes: Long,
    /** The contiguous verified prefix at commit time — the safe local read boundary. */
    val verifiedPrefixBytes: Long,
)

data class HandoffPlan(
    val resumeRanges: List<ByteInterval>,
    val alreadyHeldBytes: Long,
    val bytesToFetch: Long,
    /** Bytes that WOULD have been wasted had we naively restarted from 0. */
    val bytesSaved: Long,
    val resumeFromByte: Long,
    val completionDetected: Boolean,
) {
    /** Hard invariant: fetched + held == total (clamped), so we never re-request held bytes. */
    fun refetchIsExactlyTheGaps(): Boolean =
        bytesToFetch == resumeRanges.sumOf { it.length }
}

object HandoffAccounting {

    fun plan(request: HandoffRequest): HandoffPlan {
        val total = request.totalSizeBytes.coerceAtLeast(0L)
        val held = request.ledger.coveredBytesWithin(total)
        val resume = ResumeToken.keepPlan(total, request.ledger)
        val toFetch = resume.sumOf { it.length }
        // Resume point = the lowest byte we still need, but never below what the player is
        // already reading locally (the verified prefix), so we always extend forward.
        val resumeFrom = request.ledger.firstMissing(total) ?: total
        return HandoffPlan(
            resumeRanges = resume,
            alreadyHeldBytes = held,
            bytesToFetch = toFetch,
            bytesSaved = held,
            resumeFromByte = resumeFrom,
            completionDetected = request.ledger.isComplete(total),
        )
    }
}
