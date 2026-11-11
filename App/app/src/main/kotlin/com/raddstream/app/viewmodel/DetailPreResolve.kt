package com.raddstream.app.viewmodel

import com.raddstream.app.data.RegionChoices

/**
 * Audit #1 — the audio word the detail load sends with `?warm=1`: the
 * region card's own promise, or null when the region has no stance (an
 * East Asian viewer wants the original track — naming another language
 * would demote the track they asked for). A null is omitted from the
 * query, never sent as an empty value; an unknown region falls back to
 * the default card, never to a guess.
 */
internal fun detailWarmAudio(region: String): String? =
    RegionChoices.byId(region).audioLanguage

/**
 * Gap A2 — pre-resolve the top link on detail open, so pressing Play does not
 * pay the `playV2` round trip first.
 *
 * The detail screen already calls `playV2` at Play-press time with a 2 s
 * ceiling ([DetailViewModel.playPrint]); this file holds the two pure
 * decisions that move that call earlier, so both paths can be pinned by a
 * test without a repository:
 *
 *  - [bestPrintOf]: the same "best" the screen's own Play button offers
 *    (highest `rankKey` across every print of the title), so the
 *    pre-resolve warms the link Play would actually press.
 *  - [isPreresolveFresh]: a pre-resolved bundle is reused only for the
 *    print it was resolved for, and only inside [PRERESOLVE_FRESH_MS].
 *    The window is short on purpose — the bundle itself carries a session
 *    expiry the player still enforces at load time, so this is only the
 *    "don't re-call for the same tap" guard, never a second TTL.
 */
internal const val PRERESOLVE_FRESH_MS: Long = 120_000L

internal fun bestPrintOf(layout: ReleaseLayout?): RankedPrint? {
    val all = layout?.let {
        it.workPrints +
            it.seasons.flatMap { season -> season.episodes.flatMap { e -> e.prints } } +
            it.seasons.flatMap { season -> season.packedPrints }
    }.orEmpty()
    return all.maxByOrNull { print -> print.rankKey }
}

internal fun isPreresolveFresh(
    cachedReleaseId: Int?,
    cachedAtMs: Long?,
    releaseId: Int,
    nowMs: Long,
): Boolean {
    val atMs = cachedAtMs ?: return false
    if (cachedReleaseId != releaseId) return false
    if (nowMs < atMs) return false
    return nowMs - atMs <= PRERESOLVE_FRESH_MS
}
