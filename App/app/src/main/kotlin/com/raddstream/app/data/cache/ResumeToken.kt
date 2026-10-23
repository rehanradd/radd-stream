package com.raddstream.app.data.cache

/**
 * A durable resume token: a compact, self-describing snapshot of "how far we got and where
 * to continue", safe to persist across app restarts, process death, and network changes.
 *
 * It is NOT a server HTTP `Range` echo token — the backend has no session state (the API is
 * unauthenticated and ephemeral URLs expire). This token lets the app rebuild its own request
 * plan after it is killed, using only the source identity plus the byte ledger it already
 * wrote to disk.
 *
 * Format (versioned, pipe-delimited, each interval as `start-end`):
 *   v1|<identityDigest>|<total>|<revision>|<start-end,start-end,...>
 * `revision` guards against a stale token being replayed after a newer partial file exists,
 * and any malformed token fails loud (returns null from [decode]) so callers never trust
 * garbage ranges.
 */
data class ResumeToken(
    val identityDigest: String,
    val totalSizeBytes: Long,
    val revision: Long,
    val ledger: IntervalLedger,
) {
    fun encode(): String {
        val ranges = ledger.intervals.joinToString(",") { "${it.start}-${it.end}" }
        return "v1|$identityDigest|$totalSizeBytes|$revision|${ranges.ifBlank { "-" }}"
    }

    companion object {
        private const val VERSION = "v1"

        fun decode(token: String): ResumeToken? {
            val parts = token.split("|")
            if (parts.size != 5) return null
            if (parts[0] != VERSION) return null
            val digest = parts[1]
            if (digest.isBlank()) return null
            val total = parts[2].toLongOrNull() ?: return null
            if (total < 0) return null
            val revision = parts[3].toLongOrNull() ?: return null
            val ledger = IntervalLedger()
            val rangesField = parts[4]
            if (rangesField != "-") {
                for (chunk in rangesField.split(",")) {
                    val se = chunk.split("-")
                    if (se.size != 2) return null
                    val s = se[0].toLongOrNull() ?: return null
                    val e = se[1].toLongOrNull() ?: return null
                    if (s < 0 || e < s) return null
                    ledger.add(s, e)
                }
            }
            return ResumeToken(digest, total, revision, ledger)
        }

        /**
         * Build the request plan for a resume: given the token and the freshly re-resolved
         * identity digest, decide exactly which byte ranges still need fetching. If the digest
         * does not match the resource (a different print slipped in under the same release),
         * we refuse to adopt the bytes and return the full range so nothing is corrupted —
         * matching bytes are only ever reused for a matching identity.
         */
        fun resumeRanges(token: ResumeToken, expectedDigest: String): List<ByteInterval> {
            if (token.identityDigest != expectedDigest) {
                return if (token.totalSizeBytes > 0) listOf(ByteInterval(0, token.totalSizeBytes))
                else emptyList()
            }
            return if (token.totalSizeBytes > 0) token.ledger.gaps(token.totalSizeBytes)
            else emptyList()
        }

        /**
         * The core "keep this mid-playback" accounting. Given a total file size and the bytes
         * we already hold, return the exact set of ranges to fetch to reach 100% — guaranteed
         * to exclude every already-covered byte. This is what proves the "70 of 130 minutes
         * watched" case re-fetches zero bytes: the returned plan partitions cleanly into
         * gaps, and `sum(gap.length) == total - covered`.
         */
        fun keepPlan(totalSizeBytes: Long, ledger: IntervalLedger): List<ByteInterval> =
            ledger.gaps(totalSizeBytes)

        /** Bytes that would be re-downloaded if a naive plan started at 0 — must be 0 on handoff. */
        fun wastedBytesIfRestartedFromZero(totalSizeBytes: Long, ledger: IntervalLedger): Long =
            ledger.coveredBytesWithin(totalSizeBytes)
    }
}
