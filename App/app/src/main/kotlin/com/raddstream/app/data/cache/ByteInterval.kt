package com.raddstream.app.data.cache

/**
 * A half-open byte interval `[start, end)`.
 *
 * End-exclusive is deliberate: two neighbours `[0,100)` and `[100,200)` tile the range
 * with no overlap and no hole, which makes the merge rule "touching or overlapping → join"
 * exact and free of off-by-one drift. Every byte offset in the cache layer is a `Long`
 * (a 4K file can exceed `Int.MAX_VALUE`).
 *
 * This type is pure Kotlin — no Android, no coroutines — so it is unit-testable on the JVM.
 */
data class ByteInterval(val start: Long, val end: Long) {
    init {
        require(start >= 0) { "interval start must be >= 0, was $start" }
        require(end >= start) { "interval must have end >= start, was [$start,$end)" }
    }

    /** Number of bytes this interval represents. */
    val length: Long get() = end - start

    /** True when the interval holds no bytes (`start == end`). */
    val isEmpty: Boolean get() = start == end

    /** Does this interval contain the absolute byte [offset]? End is exclusive. */
    operator fun contains(offset: Long): Boolean = offset in start until end

    /** Do two intervals share at least one byte? */
    fun overlaps(other: ByteInterval): Boolean =
        start < other.end && other.start < end

    /** Do two intervals touch (one's end == the other's start)? Used to join contiguous runs. */
    fun touches(other: ByteInterval): Boolean =
        end == other.start || other.end == start

    companion object {
        fun of(start: Long, end: Long): ByteInterval = ByteInterval(start, end)
    }
}
