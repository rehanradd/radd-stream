package com.raddstream.app.player

/**
 * A-B repeat (plan §5 step 14, P13): loop one segment of the file, A to B. Pure,
 * so a JVM test can prove the loop without a player.
 *
 * Media3's REPEAT_MODE_ONE loops the WHOLE item, so a segment loop is ticker-driven:
 * the ViewModel's 200 ms ticker asks [loopTargetMs] on every visit and seeks back
 * to A when the playhead reaches B. The 1-second re-arm window is the guard that
 * keeps a seek still in flight from being re-issued on every tick.
 */
data class AbRepeat(
    val aMs: Long? = null,
    val bMs: Long? = null,
) {
    /** A segment exists only when both points are set and A comes before B. */
    val isActive: Boolean get() = aMs != null && bMs != null && aMs < bMs
    val hasA: Boolean get() = aMs != null
    val hasB: Boolean get() = bMs != null
}

/** One second between loop-backs: the seek needs that long to take effect. */
const val AB_REARM_MS = 1_000L

/**
 * Set point A at the current position. An A at or past the current B starts a new
 * segment: the old B no longer bounds anything, so it is cleared rather than kept
 * as a B that comes before its A.
 */
fun abRepeatWithA(ab: AbRepeat, positionMs: Long): AbRepeat =
    if (ab.bMs != null && positionMs >= ab.bMs) AbRepeat(aMs = positionMs, bMs = null)
    else ab.copy(aMs = positionMs)

/**
 * Set point B at the current position. A B at or before A is not a segment, so the
 * tap is ignored and the old state stands — the viewer keeps whatever A they had
 * instead of losing it to a mis-tap.
 */
fun abRepeatWithB(ab: AbRepeat, positionMs: Long): AbRepeat =
    if (ab.aMs == null || positionMs <= ab.aMs) ab else ab.copy(bMs = positionMs)

/**
 * Where the playhead must jump, or null when it must not: no segment, not at B yet,
 * or inside the re-arm window after the last loop-back. The caller seeks to the
 * returned position and records the time it did so.
 */
fun loopTargetMs(positionMs: Long, ab: AbRepeat, lastLoopAtMs: Long?, nowMs: Long): Long? {
    val a = ab.aMs ?: return null
    val b = ab.bMs ?: return null
    if (a >= b || positionMs < b) return null
    if (lastLoopAtMs != null && nowMs - lastLoopAtMs < AB_REARM_MS) return null
    return a
}
