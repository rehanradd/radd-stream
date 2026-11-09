package com.raddstream.app.viewmodel

/**
 * Where a newly launched playback starts when nobody typed a number in.
 *
 * Four things can answer that, and they are not equally trustworthy, so the order is stated
 * once here instead of being re-improvised at each play entry point:
 *
 *  1. an explicit start (a quality switch mid-scene, "Play again from", a pack offset) — the
 *     caller already holds it and nothing below may second-guess it;
 *  2. a position this process measured ([inProcessMs], the live `resumeByTarget` map) — the
 *     viewer is watching right now and a remembered row cannot be newer than that;
 *  3. a row the sync account pulled, which is another device's answer to "where did viewing
 *     stop", and the only answer a device that never opened this scope can have;
 *  4. a row THIS device wrote before its process died. [resumeByTarget] is in-memory, so a
 *     second viewing session found nothing to resume from even while the Continue watching
 *     rail was still showing the timestamp — the tile promised a place the tape never went.
 *
 * A null answer means "seed nothing", and the existing path starts at 0 exactly as it did.
 * The account row is asked before the local row because that order was already the documented
 * behaviour of this entry point; where both exist this device's own write is what the rail
 * fell back to, not a competing claim.
 */
object ResumeSeed {

    fun seedFor(
        explicitStartMs: Long?,
        inProcessMs: Long?,
        syncedMs: Long?,
        localHistoryMs: Long?,
    ): Long? = when {
        explicitStartMs != null -> null
        inProcessMs != null -> null
        else -> syncedMs ?: localHistoryMs
    }

    /**
     * Session 126 (audit bug d): the same handle re-opened after the viewer watched
     * further on another device must re-seed to the NEWER position — the old code
     * bailed out whenever a row already existed in `resumeByTarget`, so a position
     * that changed elsewhere was silently ignored. This answers the question the
     * bail-out used to answer with "nothing": given the position already seeded
     * ([existingMs]) and the freshest rows known ([syncedMs], [localHistoryMs]),
     * return the later position when it is strictly later than what is seeded, else
     * null. The seedFor rule is preserved — a remembered row never wins over a
     * position this process measured; this only decides between remembered rows.
     */
    fun newerSeed(existingMs: Long?, syncedMs: Long?, localHistoryMs: Long?): Long? {
        val freshest = listOfNotNull(syncedMs, localHistoryMs).maxOrNull() ?: return null
        return if (existingMs == null || freshest > existingMs) freshest else null
    }
}
