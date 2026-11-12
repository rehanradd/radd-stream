package com.raddstream.app.viewmodel

import com.raddstream.app.data.RegionChoices
import com.raddstream.app.player.LadderForScope

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

/**
 * Gap A2 follow-up — the scope warm: the handle the quality card's Auto rung
 * would press for one season/episode scope, or null when the scope has
 * nothing playable here. The detail-open warm covers only the title's best
 * print and the server warms only the first scope, so an episode the viewer
 * is looking at would otherwise pay its 5-11 s live resolve inside the
 * player. Warming this handle (a metadata ask on our own redirector) makes
 * the server live-resolve AND bank the answer, so the Play press 302s from
 * cache. A download-only rung is never warmed — its handle is not a stream.
 */
internal fun scopeWarmHandle(ladder: LadderForScope): String? {
    val auto = ladder.autoOption ?: return null
    if (!auto.playsHere) return null
    return auto.streamId.takeIf { it.isNotBlank() }
}

/**
 * Gap A2 follow-up — the fallback's runner-ups: the other playable copies
 * of the same print, for the play path that never got a server bundle.
 * The v2 bundle stages its own runner-ups and the ladder stages its rung's,
 * but the client-side fallback (`playLink`) launched a bare
 * single-rendition bundle, so the 8 s watchdog could only retry the same
 * slow address and then give up. Same print, same quality, different copy —
 * exactly what a silent hop within the rung is for. Provider pages are
 * never backups (a hop must never land on a page), dead links are never
 * backups, and the list is capped so one print cannot stage the whole
 * ladder.
 */
internal fun siblingBackupHandles(
    print: RankedPrint,
    link: RankedLink,
    max: Int = 5,
): List<String> =
    print.links
        .filter { it.playableHere && !it.isProviderPage && it.streamId != link.streamId }
        .map { it.streamId }
        .filter { it.isNotBlank() }
        .distinct()
        .take(max)
