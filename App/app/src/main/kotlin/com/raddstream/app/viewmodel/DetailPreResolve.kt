package com.raddstream.app.viewmodel

import com.raddstream.app.data.RegionChoices
import com.raddstream.app.player.LadderForScope
import com.raddstream.app.player.QualityOption
import java.io.IOException
import retrofit2.HttpException

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
 * The detail screen already calls `playV2` at Play-press time with a
 * ceiling ([DetailViewModel.playPrint], [PLAY_V2_TIMEOUT_MS]); this file
 * holds the two pure decisions that move that call earlier, so both paths
 * can be pinned by a test without a repository:
 *
 *  - [bestPrintOf]: the same "best" the screen's own Play button offers
 *    (highest `rankKey` across every print of the title), so the
 *    pre-resolve warms the link Play would actually press. It is
 *    deliberately VIP-blind — the raw best, whatever the caller may play —
 *    so [bestPlayablePrintOf] is the one Play paths call: the best print
 *    the caller may actually play, never a VIP-only tier for a free viewer.
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

/**
 * Salaar (2026-11-13) — the best print the caller may actually play.
 * [bestPrintOf] is the raw best, and on Salaar that is the 2160p 4K print
 * (release 1318138, score 755) — a print the server's preresolve refuses
 * for a free caller (`premium_quality_requires_vip`, zero tiers), so Auto
 * pointing at it is a quality the free viewer can never play. A free
 * caller gets the highest non-VIP print instead (Salaar: the 720p print,
 * release 1318132, score 530, which preresolves playable with a 720p
 * tier); a VIP caller keeps the raw best. Same preference shape as
 * [stepDownPrint] — a playable copy first, any allowed print second —
 * and null when no allowed print remains, so the caller shows the VIP
 * lock instead of pressing a tier it cannot play.
 */
internal fun bestPlayablePrintOf(
    layout: ReleaseLayout?,
    premiumAccess: Boolean,
    freeQualityCap: String,
): RankedPrint? {
    if (premiumAccess) return bestPrintOf(layout)
    val all = layout?.let {
        it.workPrints +
            it.seasons.flatMap { season -> season.episodes.flatMap { e -> e.prints } } +
            it.seasons.flatMap { season -> season.packedPrints }
    }.orEmpty()
    val allowed = all.filter {
        !VipQualityGate.isPremiumResolution(it.resolution, freeQualityCap)
    }
    return allowed.filter { it.playableHere }.maxByOrNull { it.rankKey }
        ?: allowed.maxByOrNull { it.rankKey }
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
 * Salaar (2026-11-12) — step down from a premium print the server would not
 * bundle. The mint refuses a gated print for a free caller, and the print's
 * own link 402s at press time, so pressing it anyway burns the player's
 * whole watchdog budget on copies that cannot play. The step-down is the
 * best print the caller may actually play (highest `rankKey` among the
 * prints the quality cap allows, never the failed print itself), preferring
 * one with a playable copy — a free print with nothing playable is still a
 * better answer than a gated one, but only when nothing better exists.
 * Null when the caller already has premium access (their empty bundle is a
 * transient or dead print, not a gate) or when no allowed print remains.
 */
internal fun stepDownPrint(
    layout: ReleaseLayout?,
    failedPrint: RankedPrint,
    premiumAccess: Boolean,
    freeQualityCap: String,
): RankedPrint? {
    if (premiumAccess) return null
    val all = layout?.let {
        it.workPrints +
            it.seasons.flatMap { season -> season.episodes.flatMap { e -> e.prints } } +
            it.seasons.flatMap { season -> season.packedPrints }
    }.orEmpty()
    val allowed = all.filter {
        it.releaseId != failedPrint.releaseId &&
            !VipQualityGate.isPremiumResolution(it.resolution, freeQualityCap)
    }
    return allowed.filter { it.playableHere }.maxByOrNull { it.rankKey }
        ?: allowed.maxByOrNull { it.rankKey }
}

/**
 * Salaar (2026-11-12) — the print Play actually starts on. A locked print is never
 * the answer when a free print can play: the hero's Watch Now and the print rows
 * step down to the best allowed print first, and only show the VIP lock when no
 * allowed print remains. The old shape showed the lock for a locked best print
 * even while a 720p copy of the same title sat playable — Salaar's detail said
 * "4K and 1080p are part of VIP" for a film with a free 720p print. Null means
 * "locked, and nothing free to fall back to".
 */
internal fun playStartPrint(
    layout: ReleaseLayout?,
    print: RankedPrint,
    premiumAccess: Boolean,
    freeQualityCap: String,
): RankedPrint? =
    if (VipQualityGate.allowsResolution(print.resolution, premiumAccess)) print
    else stepDownPrint(layout, print, premiumAccess, freeQualityCap)

/**
 * Salaar (2026-11-12) — the rung the quality card actually starts on. Same rule as
 * [playStartPrint], for a tapped ladder rung: a locked rung steps down to the best
 * allowed rung that plays here (the ladder is best-first, so the first allowed
 * playable rung is the best free picture), and only when no rung survives does the
 * tap become the VIP lock. A provider page is never a step-down target — a hop
 * must never land on a page — and the failed rung itself is excluded.
 */
internal fun stepDownRung(
    ladder: LadderForScope,
    failed: QualityOption,
    premiumAccess: Boolean,
    freeQualityCap: String,
): QualityOption? {
    if (premiumAccess) return null
    return ladder.options.firstOrNull {
        it.band != failed.band &&
            !it.isProviderPage &&
            it.playsHere &&
            it.streamId.isNotBlank() &&
            VipQualityGate.allowsBand(it.band, premiumAccess, freeQualityCap) &&
            !VipQualityGate.isPremiumLabel(it.title, freeQualityCap)
    }
}

/**
 * Salaar (2026-11-13) — the rung Auto actually starts at for this viewer.
 * [LadderForScope.autoOption] is the server's pointer, VIP-blind: on
 * Salaar it is the 2160p rung, which the server refuses to bundle for a
 * free caller — so a free Auto must never resolve to it. A premium caller
 * keeps the server pointer. A free caller gets that rung only when it
 * survives the gate, else the best free rung that plays here (the ladder
 * is best-first), else the first allowed rung. Same rule as
 * [VipQualityGate.gate] — band and label both checked — applied at the
 * selection point, so a rung the gate would have removed can never be the
 * Auto answer even if it reaches this function ungated.
 */
internal fun autoOptionFor(
    ladder: LadderForScope,
    premiumAccess: Boolean,
    freeQualityCap: String,
): QualityOption? {
    if (premiumAccess) return ladder.autoOption
    val allowed = ladder.options.filter {
        VipQualityGate.allowsBand(it.band, premiumAccess, freeQualityCap) &&
            !VipQualityGate.isPremiumLabel(it.title, freeQualityCap)
    }
    return allowed.firstOrNull { it.band == ladder.autoBand }
        ?: allowed.firstOrNull { it.playsHere }
        ?: allowed.firstOrNull()
}

/**
 * Session 153 — the VIP the quality gate may trust.
 *
 * The entitlement flag alone is not enough: the stream endpoint serves a
 * gated band only to a caller carrying a live VIP capability (the signed
 * pass), and the Sauce Labs device test proved a trial account can hold
 * `vip=true` while its presses are still refused (402 on every gated
 * handle, while the same handle with a fresh pass 302s). The gate lifts
 * only when the account is VIP AND a live pass is in hand; anything else
 * is a free viewer for quality purposes, so Auto resolves to the best free
 * print (720p on Salaar) and the ladder, the card, the player and the
 * preresolve all agree — they all read `premiumAccess`, which is built
 * from this. A VIP whose pass has not landed yet sees the free ladder
 * until the pass arrives; the entitlement refresh re-publishes then, so
 * the gate lifts without reopening the screen.
 */
internal fun qualityVipAccess(serverVip: Boolean, hasLiveVipPass: Boolean): Boolean =
    serverVip && hasLiveVipPass

/**
 * Session 153 — is this rung the ladder's Auto pick.
 *
 * The same pointer the card reads ([LadderForScope.effectiveAutoBand]),
 * not the server's raw `autoBand`: the gate nulls `autoBand` on a gated
 * ladder, so comparing against it would record `auto = false` for an Auto
 * play staged from a gated ladder, and the player would never step down
 * from it. The effective band survives the gate, so a gated Auto play is
 * still recognised as Auto.
 */
internal fun isAutoRung(ladder: LadderForScope, option: QualityOption): Boolean =
    ladder.effectiveAutoBand != null && option.band == ladder.effectiveAutoBand

/**
 * Session 153 — the rung of one band, for staging a step-down plan.
 * The winner's print is known by its resolution band, not by a link, so
 * the Play-button path stages the rungs of the winner's band this way.
 */
internal fun rungForBand(ladder: LadderForScope, band: String): QualityOption? =
    ladder.options.firstOrNull { it.band == band }

/**
 * Gap A2 follow-up — the scope warm: the handle the quality card's Auto rung
 * would press for one season/episode scope, or null when the scope has
 * nothing playable here. The detail-open warm covers only the title's best
 * print and the server warms only the first scope, so an episode the viewer
 * is looking at would otherwise pay its 5-11 s live resolve inside the
 * player. Warming this handle (a metadata ask on our own redirector) makes
 * the server live-resolve AND bank the answer, so the Play press 302s from
 * cache. A download-only rung is never warmed — its handle is not a stream.
 *
 * Salaar (2026-11-13): the warm resolves Auto through [autoOptionFor], so
 * a free viewer warms the best free rung, never a gated one — warming a
 * rung the viewer may not play would spend the server's answer on nothing.
 */
internal fun scopeWarmHandle(
    ladder: LadderForScope,
    premiumAccess: Boolean,
    freeQualityCap: String,
): String? {
    val auto = autoOptionFor(ladder, premiumAccess, freeQualityCap) ?: return null
    if (!auto.playsHere) return null
    return auto.streamId.takeIf { it.isNotBlank() }
}

/** The same warm with no VIP question asked: the server pointer, as before. */
internal fun scopeWarmHandle(ladder: LadderForScope): String? =
    scopeWarmHandle(ladder, premiumAccess = true, freeQualityCap = "720p")

/**
 * Gap A2 follow-up — the fallback's runner-ups: the other playable copies
 * of the same print, for the play path that never got a server bundle.
 * The v2 bundle stages its own runner-ups and the ladder stages its rung's,
 * but the client-side fallback (`playLink`) launched a bare
 * single-rendition bundle, so the 20 s watchdog could only retry the same
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

/**
 * Appetize FAILED 2 (2026-11-12) — the detail-load retry policy.
 *
 * The device test showed detail pages failing on FIRST load ("Failed to
 * load details. Check connection.") and loading fully on a manual Retry,
 * every time. The failure class is transient by construction: the server
 * chain for a v2 detail is slow cold (the family work-ref lookup alone was
 * a 4.8 s full-table scan, the bridge another 4.7-6.4 s), so a first call
 * can trip over a deadline, a reset socket, or a 429/503 under load — and
 * the second call, warm, sails through. The load therefore retries itself,
 * with the same backoff a thumb-tap would have cost, instead of making
 * the viewer tap Retry.
 *
 * The policy is deliberately narrow, and it is pure so a test can pin it:
 *
 *  - [isTransientDetailError]: only transport failures (`IOException`,
 *    including timeouts) and retryable HTTP statuses (429, 5xx) retry. A
 *    parse/mapping error, a 400/403/404, or a bad address is deterministic
 *    — retrying it would fail identically and burn the server's budget.
 *  - [detailLoadBackoffMs]: 600 ms after the first failure, 1.5 s after the
 *    second — short enough to feel instant, long enough for the server's
 *    per-minute bucket to breathe.
 *  - A null detail retries once ([DETAIL_LOAD_NULL_RETRIES]): the v2 path
 *    swallows HTTP/IO failures into null inside the repository, so a null
 *    is the only shape a 429/503 takes there. A title that genuinely is
 *    not on the server answers null twice and stays "not available".
 */
internal const val DETAIL_LOAD_MAX_ATTEMPTS: Int = 3
/**
 * Session 153: a null after a swallowed timeout deserves two more chances,
 * not one — the first tap on a cold connection can die before any byte
 * leaves the device, and a single retry is not enough to cover a cold
 * pool plus a slow first call. The v2 path swallows HTTP/IO failures into
 * null inside the repository, so a null is the only shape a 429/503 takes
 * there. A title that genuinely is not on the server answers null three
 * times and stays "not available".
 */
internal const val DETAIL_LOAD_NULL_RETRIES: Int = 2

internal fun detailLoadBackoffMs(attempt: Int): Long =
    when (attempt) {
        1 -> 600L
        else -> 1_500L
    }

internal fun isTransientDetailError(ex: Exception): Boolean {
    if (ex is IOException) return true
    if (ex is HttpException) return ex.code() == 429 || ex.code() >= 500
    return false
}

/**
 * Appetize FAILED 1 (2026-11-12) — the `playV2` ceilings.
 *
 * Both were 2 s, set when the bundle call was assumed to answer in
 * milliseconds. Measured from the server (2026-11-12, 1-vCPU box), the call
 * alone costs 0.25-0.37 s of CPU in the per-request version-vector read
 * plus the bundle reads, so under load 2 s times out a call that would
 * have answered — and the fallback is a cold single link, strictly worse
 * than the ranked bundle with its runner-ups. The expected case is still
 * well under a second; the ceilings are a margin, not a wait. Both are
 * far under the player's 20 s watchdog (which only starts at playback),
 * and neither call resolves a link — the resolve is paid by the server
 * warm and inside the player — so a longer ceiling cannot stall playback,
 * it only lets the bundle arrive.
 */
internal const val PRERESOLVE_TIMEOUT_MS: Long = 10_000L
internal const val PLAY_V2_TIMEOUT_MS: Long = 6_000L
