package com.raddstream.app.network.models

/*
 * LINK RECOVERY — the part of the contract that exists because "a link can expire between
 * listing and playback" (API_V2.md §8.4, and the reason `is_temporary` is in the schema at
 * all).
 *
 * WHAT THE SERVER SUPPORTS TODAY:
 *  - the app may hit `GET /api/v1/stream?id=<handle>&redirect=1` as many times as it likes:
 *    OUR OWN redirector refreshes a stale cached target and answers a fresh 302, which is the
 *    only re-resolve mechanism that exists and the only one a client is allowed to use;
 *  - `redirect=0` on the public port names no URL at all — it reports our handle plus the
 *    measured facts (mime, size, resumability, expiry) — so recovery re-reads those facts and
 *    replays the SAME address, never an address it was handed;
 *  - there is no way to tell the server a link is dead: `POST` is not implemented at all and
 *    `/api/heal` (a GET) never writes a response body.
 *  - // NOT SERVED YET — needs POST /api/v2/links/{id}/report (see EndpointGaps.REPORT)
 *
 * So recovery here is CLIENT-SIDE and honest: pick the next candidate, re-hit the same handle,
 * and stop after a bounded number of attempts. It never pretends to notify the server, and it
 * never unwraps a bridge itself — that work belongs behind our redirector.
 */

/** Why playback did not start. Drives the UI's message and the recovery decision. */
enum class RecoveryReason {
    /** Nothing playable was ever offered (the bundle had no streamable candidate). */
    NOTHING_AVAILABLE,

    /** Our redirector said success but handed back no usable handle. */
    RESOLVER_EMPTY,

    /** The redirect round-trip failed outright (error text, non-2xx, hidden 404). */
    RESOLVE_FAILED,

    /** The link played and then stopped working: an ephemeral link that rotted. */
    LINK_EXPIRED,

    /**
     * A link that only presents outside this app was asked to be a stream. The player has no
     * WebView presentation: the honest answer is "Not playable here" plus a keep. (A page is
     * opened by the provider-page screen BEFORE playback is ever launched, so reaching this state
     * means a page arrived as a candidate anyway — a stale bundle, not a feature.)
     */
    WRONG_PRESENTATION,

    /** Every candidate has been tried. */
    EXHAUSTED,
}

/** The outcome of one playback attempt against one candidate. */
data class ResolveOutcome(
    val streamId: String?,
    /** OUR OWN redirector address for that handle — the only thing a player may be given. */
    val playUrl: String?,
    val ephemeral: Boolean,
    val expiresAtEpochMillis: Long? = null,
    val problem: ProblemDetails? = null,
) {
    val playable: Boolean
        get() = streamId != null && WireText.isHttpUrl(playUrl) && problem == null
}

/** One step of the recovery walk. */
data class RecoveryStep(
    val link: MediaLink?,
    val attempt: Int,
    val reason: RecoveryReason,
    /** True when the caller must hit `/api/v1/stream` again rather than move on. */
    val reResolve: Boolean,
    val problem: ProblemDetails? = null,
)

/**
 * The bounded failover algorithm. Stateless except for the attempts it has already made,
 * so a ViewModel can keep one per playback session.
 */
class PlaybackRecovery(
    private val bundle: PlayBundle,
    private val policy: FailurePolicy = FailurePolicy(),
) {
    // Keyed by the opaque handle, not by `link_id`: the public link view carries no raw ledger
    // id, so the handle is the only stable per-candidate key the client has.
    private val tried = linkedSetOf<String>()
    private var attempts = 0

    /** Candidates in offer order: playable here first, then keep-only, then nothing. */
    val candidates: List<Rendition> = orderForPlayback(bundle.renditions)

    val exhausted: Boolean
        get() = candidates.isEmpty() || attempts > MAX_ATTEMPTS ||
            tried.size >= candidates.size

    /** The next link to try, or null when the session is over. */
    fun next(): RecoveryStep {
        if (candidates.isEmpty()) {
            return RecoveryStep(
                link = null,
                attempt = attempts,
                reason = RecoveryReason.NOTHING_AVAILABLE,
                reResolve = false,
                problem = ProblemDetails(
                    status = 404,
                    title = "Not found",
                    detail = "No playable source for this print",
                    code = ProblemCode.NO_PLAYABLE_SOURCE,
                ),
            )
        }
        if (attempts >= MAX_ATTEMPTS) {
            return RecoveryStep(null, attempts, RecoveryReason.EXHAUSTED, reResolve = false,
                problem = ProblemDetails(
                    status = 502,
                    title = "Bad gateway",
                    detail = "Playback recovery budget exhausted",
                    code = ProblemCode.UNAVAILABLE,
                ))
        }
        val candidate = candidates.firstOrNull { it.streamId == null || it.streamId !in tried }
            ?: return RecoveryStep(null, attempts, RecoveryReason.EXHAUSTED, reResolve = false,
                problem = ProblemDetails(
                    status = 404,
                    title = "Not found",
                    detail = "Every candidate in this bundle has been attempted",
                    code = ProblemCode.NO_PLAYABLE_SOURCE,
                ))
        attempts += 1
        candidate.streamId?.let { tried.add(it) }
        return RecoveryStep(
            link = null,
            attempt = attempts,
            reason = when (candidate.playability) {
                Playability.RESOLVE_REQUIRED -> RecoveryReason.NOTHING_AVAILABLE
                Playability.WEBVIEW -> RecoveryReason.WRONG_PRESENTATION
                else -> RecoveryReason.LINK_EXPIRED
            },
            // An ephemeral (or not-yet-resolved) handle must always be re-fetched; a durable
            // one is only worth re-resolving once it has actually failed.
            reResolve = candidate.ephemeral ||
                candidate.playability == Playability.RESOLVE_REQUIRED ||
                attempts <= policy.maxRetriesPerLink,
        )
    }

    /** Records the result of the step just taken and produces the action for the caller. */
    fun record(outcome: ResolveOutcome, step: RecoveryStep): PlaybackPlan {
        if (outcome.playable) {
            return PlaybackPlan(
                rendition = candidates.firstOrNull { candidate ->
                    step.link?.streamId?.isNotEmpty() == true && candidate.streamId == step.link.streamId
                } ?: candidates.firstOrNull(),
                // Exactly one presentation: our own redirector, into Media3, which follows the
                // 302 and sniffs the container. HLS and progressive differ only in protocol,
                // never in mode, so nothing here can strand a file type.
                mode = PlaybackMode.DIRECT,
            )
        }
        val reason = when {
            outcome.problem?.code == ProblemCode.TARGET_UNRESOLVABLE -> RecoveryReason.RESOLVER_EMPTY
            step.reResolve && policy.reResolveWhenEphemeral -> RecoveryReason.LINK_EXPIRED
            else -> RecoveryReason.RESOLVE_FAILED
        }
        val nextStep = next()
        val nextCandidate = candidates.getOrElse(attempts - 1) { candidates.lastOrNull() }
        return if (nextStep.reason == RecoveryReason.EXHAUSTED ||
            !policy.failoverToNextRendition ||
            nextCandidate == null
        ) {
            PlaybackPlan(rendition = null, mode = PlaybackMode.NOTHING, problem = outcome.problem)
        } else {
            PlaybackPlan(
                rendition = nextCandidate.takeIf { reason != RecoveryReason.RESOLVE_FAILED },
                mode = modeFor(nextCandidate),
                problem = outcome.problem ?: ProblemDetails(
                    status = 502,
                    title = "Bad gateway",
                    detail = "Recovery: $reason",
                    code = ProblemCode.TARGET_UNRESOLVABLE,
                ),
            )
        }
    }

    /**
     * The presentation this app's PLAYER has, in one place. A candidate that cannot be played here
     * is offered for keeping — said out loud — and one with no address at all is nothing. Inside a
     * bundle there is no WebView mode and no client-side resolver step to fall back to.
     */
    private fun modeFor(rendition: Rendition): PlaybackMode = when (rendition.playability) {
        Playability.STREAM, Playability.BOTH -> PlaybackMode.DIRECT
        Playability.DOWNLOAD -> PlaybackMode.DOWNLOAD
        Playability.RESOLVE_REQUIRED, Playability.WEBVIEW,
        Playability.NONE, Playability.UNKNOWN -> PlaybackMode.NOTHING
    }

    companion object {
        /**
         * §8.4's bound, kept small: a user should not wait through a long failover chain
         * before seeing a problem. One re-resolve of the same link, then failover, then stop.
         */
        const val MAX_ATTEMPTS = 4

        /**
         * The offer order the v2 `/play` contract specifies (§9), applied client-side because
         * v1 gives no ranking: an address our player can open beats one that must be kept,
         * which beats one that says nothing; `dead_end` never appears at all; within a band,
         * the higher link score first, then the handle for determinism.
         */
        fun orderForPlayback(renditions: List<Rendition>): List<Rendition> =
            renditions
                .filter { it.playability != Playability.NONE }
                .sortedWith(
                    compareBy<Rendition> { bandOf(it) }
                        .thenByDescending { it.linkScore }
                        .thenBy { it.streamId ?: it.linkId ?: Long.MAX_VALUE },
                )

        /**
         * The bands the §9 order names, minus the presentations the player can no longer start:
         * there is no playable WebView band and no resolver band, because the client unwraps
         * nothing itself. A candidate in the top band plays here; anything below it is offered for
         * keeping.
         */
        private fun bandOf(rendition: Rendition): Int = when (rendition.playability) {
            Playability.STREAM, Playability.BOTH -> 0
            Playability.RESOLVE_REQUIRED, Playability.WEBVIEW -> 1
            Playability.DOWNLOAD -> 2
            Playability.UNKNOWN -> 3
            Playability.NONE -> 4
        }

        /**
         * A bundle whose URLs are ephemeral must be re-fetched, not replayed from cache.
         * 900 s is the contract's TTL for a play bundle (§8.4); v1 reports no TTL at all, so
         * the client uses the contract's number as its own ceiling and treats any ephemeral
         * link as already stale past it.
         */
        const val BUNDLE_TTL_SECONDS = 900
    }
}
