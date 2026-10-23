package com.raddstream.app.data.cache

/**
 * The mergeable gap list — the single source of truth for "which bytes of one resource do
 * we already hold on disk".
 *
 * Invariants (maintained by every mutation, asserted by tests):
 *  - intervals are sorted ascending by `start`
 *  - no two intervals overlap
 *  - no two intervals touch (adjacent intervals are always merged)
 *  - no empty intervals are stored
 *
 * Because the ledger canonicalises on insert, `coveredBytes` never double-counts an overlap
 * and `gaps(totalSize)` is a correct, minimal answer regardless of the order segments or
 * range chunks arrived in. Out-of-order network completion is the whole reason this exists.
 */
class IntervalLedger() {

    // Kept sorted and canonical after every add. `ByteInterval` is immutable; we rebuild
    // this list on merge. For files up to a few GB with chunked range writes the list is
    // short (tens of entries), so O(n) insert is fine and far clearer than a tree.
    private val _intervals = mutableListOf<ByteInterval>()

    /** Read-only view of the current canonical intervals. */
    val intervals: List<ByteInterval> get() = _intervals.toList()

    constructor(seed: List<ByteInterval>) : this() {
        seed.forEach { add(it.start, it.end) }
    }

    /** Add `[start, end)` bytes, merging any overlapping or touching neighbours. */
    fun add(start: Long, end: Long) {
        if (start >= end) return // empty range — nothing to record
        val incoming = ByteInterval(start, end)
        val merged = ArrayList<ByteInterval>(_intervals.size + 1)
        var lo = start
        var hi = end
        for (existing in _intervals) {
            if (existing.overlaps(incoming) || existing.touches(incoming)) {
                lo = minOf(lo, existing.start)
                hi = maxOf(hi, existing.end)
            } else {
                merged.add(existing)
            }
        }
        merged.add(ByteInterval(lo, hi))
        merged.sortBy { it.start }
        _intervals.clear()
        _intervals.addAll(merged)
    }

    /** Total distinct bytes held. Because the list is disjoint this is a plain sum. */
    fun coveredBytes(): Long = _intervals.sumOf { it.length }

    /** Total distinct bytes held, clamped to a known [totalSize] (excludes any overrun). */
    fun coveredBytesWithin(totalSize: Long): Long =
        _intervals.sumOf { maxOf(0L, minOf(it.end, totalSize) - it.start) }

    /** True if [offset] is already on disk. */
    fun isCovered(offset: Long): Boolean = _intervals.any { offset in it }

    /**
     * The largest offset such that every byte in `[0, offset)` is present — the contiguous
     * verified prefix. This is the amount a sequential (progressive-download) player can
     * trust for gapless playback and the natural "resume from here" point for MP4-style
     * forward fetching. Returns 0 when the first byte is missing.
     */
    fun verifiedPrefix(): Long {
        val first = _intervals.firstOrNull() ?: return 0L
        return if (first.start == 0L) first.end else 0L
    }

    /**
     * The end of the contiguous run that covers [offset], or [offset] itself if it is not
     * covered. Used by the player to read `[offset, nextContiguousEnd(offset))` locally
     * without seeking into a hole.
     */
    fun nextContiguousEnd(offset: Long): Long =
        _intervals.firstOrNull { offset in it }?.end ?: offset

    /** All missing byte ranges within `[0, totalSize)`, sorted ascending, merged. */
    fun gaps(totalSize: Long): List<ByteInterval> {
        if (totalSize <= 0L) return emptyList()
        val out = ArrayList<ByteInterval>()
        var cursor = 0L
        for (iv in _intervals) {
            if (iv.start >= totalSize) break
            if (iv.start > cursor) out.add(ByteInterval(cursor, minOf(iv.start, totalSize)))
            cursor = maxOf(cursor, iv.end)
            if (cursor >= totalSize) break
        }
        if (cursor < totalSize) out.add(ByteInterval(cursor, totalSize))
        return out
    }

    /** The lowest missing byte in `[0, totalSize)`, or null when complete. */
    fun firstMissing(totalSize: Long): Long? = gaps(totalSize).firstOrNull()?.start

    /**
     * Missing intervals that fall inside the target window `[windowStart, windowEnd)`.
     * This is the "fetch exactly these bytes, nothing already held" answer that makes the
     * handoff zero-waste: intersecting the request with the ledger guarantees we never
     * re-download a range we already have.
     */
    fun missingWithin(windowStart: Long, windowEnd: Long): List<ByteInterval> {
        if (windowEnd <= windowStart) return emptyList()
        return gaps(windowEnd)
            .mapNotNull { clip(it, windowStart, windowEnd) }
            .filter { !it.isEmpty }
    }

    /** True when every byte of `[0, totalSize)` is present. */
    fun isComplete(totalSize: Long): Boolean =
        totalSize <= 0L || (gaps(totalSize).isEmpty())

    /** True when the contiguous prefix alone reaches [totalSize] (complete via prefix). */
    fun isContiguousComplete(totalSize: Long): Boolean =
        totalSize <= 0L || verifiedPrefix() >= totalSize

    override fun toString(): String =
        _intervals.joinToString(",") { "[${it.start},${it.end})" }.let { "Ledger{$it}" }

    private fun clip(iv: ByteInterval, lo: Long, hi: Long): ByteInterval? {
        val s = maxOf(iv.start, lo)
        val e = minOf(iv.end, hi)
        return if (s < e) ByteInterval(s, e) else null
    }
}
