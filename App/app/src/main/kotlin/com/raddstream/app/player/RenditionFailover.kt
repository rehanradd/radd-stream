package com.raddstream.app.player
import androidx.media3.common.PlaybackException
import androidx.media3.datasource.HttpDataSource
import com.raddstream.app.network.models.Playability

/** The HTTP status our own redirector answers when the quality gate refuses a rung. */
const val GATE_REFUSED_HTTP_STATUS: Int = 402

/**
 * Salaar (2026-11-12): did this player error come from OUR redirector refusing the
 * rung — the quality gate's 402 — rather than from a copy that merely failed?
 * Media3 1.3.1 (the pinned version) carries the status in the exception two ways:
 * the message of [HttpDataSource.InvalidResponseCodeException] is exactly
 * "Response code: 402", and the cause chain holds the exception itself. Either
 * signal is enough; a 404/403 is NOT a refusal (that handle may be dead while its
 * same-rung runner-ups are fine), and any other code is not a gate at all.
 */
internal fun isGateRefusalError(error: PlaybackException): Boolean {
    if (error.errorCode == PlaybackException.ERROR_CODE_IO_BAD_HTTP_STATUS &&
        error.message?.contains("Response code: $GATE_REFUSED_HTTP_STATUS") == true
    ) return true
    var cause: Throwable? = error.cause
    while (cause != null) {
        if (cause is HttpDataSource.InvalidResponseCodeException &&
            cause.responseCode == GATE_REFUSED_HTTP_STATUS
        ) return true
        cause = cause.cause
    }
    return false
}

/**
 * Pure failover policy for a [PlayBundle], implementing API_V2.md §5:
 * "Try rank 1; on error, retry once, then move to rank 2, then rank 3 — never beyond
 * max_ranks (each failover is reported back)."
 *
 * Deliberately Android-free so it is JVM-unit-testable; `PlaybackService` drives it with real
 * player errors and `PlayerSessionStore` carries the visible outcome (which print settled and
 * why each previous candidate died) to the overlay UI.
 */

/** One entry of the auditable failover trail (shown in the UI + future telemetry POST). */
data class FailoverRecord(
    val rank: Int,
    val releaseId: Int,
    val label: String,
    /** Short human reason, e.g. "HTTP 404", "Decoder failed at 00:12", "link expired". */
    val reason: String,
    /** What the player did about it: "retried", "skipped to next rank", "skipped (keep-only)". */
    val action: String,
)

/**
 * Why the player stopped and needs someone else. There is no WebView member because a page never
 * reaches the player: [com.raddstream.app.viewmodel.DetailViewModel] opens the provider-page screen
 * for it before playback starts. Inside a failover bundle, then, [DOWNLOAD_ONLY] and
 * [NO_CANDIDATE_LEFT] are the only honest exits — a link that cannot play here is kept, and says so.
 * [START_TIMEOUT] is the third: no candidate failed, but none produced a frame within the start
 * deadline, so the player stops waiting and hands the viewer the choice.
 */
enum class HandoffWhy {
    DOWNLOAD_ONLY,
    NO_CANDIDATE_LEFT,
    START_TIMEOUT,
    /**
     * NAV-4 (Session 126): the shared link itself rotted — a signed handle whose
     * window closed, or a bundle the server says is stale. The give-up card must
     * say exactly that ("this shared link has expired"), not the generic "nothing
     * playable", because the fix is a fresh link, not another print.
     */
    EXPIRED_LINK,
    /**
     * Salaar (2026-11-12): the server refused every rung it was handed with the
     * quality gate's 402 — the best quality is VIP-only and no free rung was left
     * to step down to. The give-up card must say that plainly ("this quality
     * needs VIP"), not the generic "nothing playable", because the fix is a lower
     * quality or VIP, not another retry of the same rung.
     */
    GATE_REFUSED,
}

sealed class FailoverDecision {
    /** Keep the same rendition, prepare again after [backoffMs] (policy.retry_same). */
    data class RetrySame(val index: Int, val backoffMs: Long, val record: FailoverRecord) : FailoverDecision()

    /**
     * Switch to another copy of the SAME rung, [streamId], at [playUrl] (our own
     * redirector, one handle swapped for another). Silent by contract: same quality,
     * same position, no banner, no dialog — the viewer keeps watching while a
     * different server answers.
     */
    data class AdvanceBackup(
        val index: Int,
        val streamId: String,
        val playUrl: String,
        val record: FailoverRecord,
    ) : FailoverDecision()

    /** Switch to rendition [index]; [settledLabel] is what the top-bar chip must show. */
    data class Advance(val index: Int, val settledLabel: String, val record: FailoverRecord) : FailoverDecision()

    /** Nothing else the native player can try — surface [why] to the user. */
    data class Handoff(val why: HandoffWhy, val detail: String?, val record: FailoverRecord?) : FailoverDecision()
}

/**
 * Session 121 (P-6): human words for a raw player error summary. `PlaybackService.summarize`
 * returns ExoPlayer's `errorCodeName` plus the exception's first line — e.g.
 * "ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT ..." — which the give-up card used to print
 * verbatim, wrapped mid-word. A viewer cannot act on a constant name, so the machine
 * translates the known codes into sentences and the raw text never reaches a
 * user-visible surface. Anything without an `ERROR_CODE_` token is already human
 * ("link expired before load", "Reached max_ranks=…") and passes through untouched, so
 * this is idempotent. The raw code is still written to logcat by `PlaybackService`
 * before it calls `onFailure`, so diagnosis loses nothing.
 */
internal fun humanizeErrorSummary(raw: String): String {
    if (!raw.contains("ERROR_CODE_")) return raw
    return when {
        raw.contains("ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT") ->
            "The connection timed out. Check your connection and try again."
        raw.contains("ERROR_CODE_IO_NETWORK_CONNECTION_FAILED") ->
            "Could not reach the server. Check your connection and try again."
        raw.contains("ERROR_CODE_IO_INVALID_HTTP_CONTENT_TYPE") ->
            "The server sent something that is not a video."
        raw.contains("ERROR_CODE_IO_BAD_HTTP_STATUS") ->
            "The server refused this link."
        raw.contains("ERROR_CODE_IO_FILE_NOT_FOUND") ->
            "This copy is no longer on the server."
        raw.contains("ERROR_CODE_IO_NO_PERMISSION") ->
            "The server refused access to this copy."
        raw.contains("ERROR_CODE_DECODER") ->
            "This device could not play this video."
        raw.contains("ERROR_CODE_IO_") ->
            "The video could not be loaded. Check your connection and try again."
        else -> "Playback failed. Retry, or try another version."
    }
}

class FailoverStateMachine(
    private val renditions: List<PlaybackRendition>,
    private val policy: PlaybackFailurePolicy,
) {

    private val attemptsByIndex = HashMap<Int, Int>()
    private val backupsUsedByIndex = HashMap<Int, Int>()
    private var ranksBurned = 0
    private val _log = ArrayList<FailoverRecord>()

    val log: List<FailoverRecord> get() = _log.toList()

    /**
     * The next silent runner-up of rung [index], as handle + address of ours, or null
     * when this rung has none left. A backup only ever replaces a URL on our own
     * redirector ([streamUrlForHandle]), so a hop can never aim the player at an
     * address the app was not given.
     */
    private fun nextBackupFor(index: Int): Pair<String, String>? {
        val rendition = renditions.getOrNull(index) ?: return null
        val used = backupsUsedByIndex[index] ?: 0
        for (handle in rendition.playback.backupStreamIds.drop(used)) {
            val url = streamUrlForHandle(rendition.playback.playUrl, handle) ?: continue
            backupsUsedByIndex[index] = used + 1
            return handle to url
        }
        return null
    }

    /** Index chosen at bundle load time, or null when no candidate is directly playable. */
    var activeIndex: Int = -1
        private set

    /**
     * Directly playable = our own address can go to ExoPlayer today: a stream/both file or HLS
     * manifest, non-blank `play_url`. `download`, `none` and anything unclassified are NOT
     * playable in-player and are offered for keeping instead, with [NOT_PLAYABLE_HERE] on them.
     */
    private fun isPlayable(index: Int): Boolean {
        val r = renditions.getOrNull(index) ?: return false
        return !r.playback.playUrl.isNullOrBlank() &&
            r.playback.playabilityOrUnknown() in setOf(Playability.STREAM, Playability.BOTH)
    }

    /** Initial rendition selection. Records why skipped candidates were skipped. */
    fun selectInitial(): Int? {
        for (i in renditions.indices) {
            val r = renditions[i]
            if (isPlayable(i)) {
                activeIndex = i
                return i
            }
            _log.add(skipRecord(i, r))
        }
        activeIndex = -1
        return null
    }

    /**
     * Why a candidate was not chosen — in quality/behaviour words, never naming who hosts
     * anything. A keep-only link says the true thing: this app cannot present it.
     */
    private fun skipRecord(i: Int, r: PlaybackRendition): FailoverRecord {
        val why = when (r.playback.playabilityOrUnknown()) {
            Playability.DOWNLOAD -> NOT_PLAYABLE_HERE
            Playability.WEBVIEW, Playability.RESOLVE_REQUIRED ->
                "$NOT_PLAYABLE_HERE — only presents outside this app"
            Playability.NONE, Playability.UNKNOWN -> "no usable link on this rank"
            else -> if (r.playback.playUrl.isNullOrBlank()) "no address of ours on this rank" else "unusable"
        }
        return FailoverRecord(r.rank, r.releaseId, r.displayLabel(), why, "skipped")
    }

    /**
     * Call when the active rendition fails with [errorSummary]. Returns the mandated next step.
     *
     * [isExpiry] marks a failure the machine must not retry: a rotted handle will not heal
     * on a second try, and a silent hop onto a runner-up of the same rotted handle is the
     * same failure wearing a different address. An expiry goes straight to the handoff with
     * [HandoffWhy.EXPIRED_LINK], so the card can say the link expired instead of the
     * generic "nothing playable".
     *
     * [isGateRefusal] marks a 402 from our own redirector: the quality gate refused this
     * rung, and every copy of the rung shares the refusal (the gate is per print band,
     * not per handle). Retrying the same address and hopping to same-rung runner-ups
     * are both futile — each hop re-pays Media3's ~3 s of loader retries before it
     * 402s again — so a refusal skips straight to the next rank (or the handoff when
     * no rank remains), instead of burning the start budget on copies that cannot play.
     */
    fun onFailure(
        errorSummary: String,
        isExpiry: Boolean = false,
        isGateRefusal: Boolean = false,
    ): FailoverDecision {
        // Session 121 (P-6): the summary may be a raw ExoPlayer code; the machine is the
        // single funnel every failure passes through, so translate it here — the Handoff
        // detail (the give-up card's message) and the FailoverRecord reason (the print
        // sheet's failover log) are both user-visible and both get human words.
        val displaySummary = humanizeErrorSummary(errorSummary)
        val index = activeIndex
        val current = renditions.getOrNull(index)
            ?: return FailoverDecision.Handoff(HandoffWhy.NO_CANDIDATE_LEFT, displaySummary, null)
        if (isExpiry) {
            val record = FailoverRecord(current.rank, current.releaseId, current.displayLabel(), displaySummary, "expired")
            _log.add(record)
            return FailoverDecision.Handoff(HandoffWhy.EXPIRED_LINK, displaySummary, record)
        }
        if (isGateRefusal) {
            // The gate refused the whole rung: no retry, no same-rung hop — the next
            // rank (or the honest give-up) is the only move that can play.
            val record = FailoverRecord(
                current.rank, current.releaseId, current.displayLabel(),
                displaySummary, "gate refused this rung",
            )
            return advanceToNextRank(index, displaySummary, record, HandoffWhy.GATE_REFUSED)
        }
        // Read-modify-write instead of `HashMap.merge`: `merge` is a Java 8 default method and
        // lint correctly refuses it against minSdk 21 (it ships in API 24). The count below is
        // only ever read on this thread, so the atomicity `merge` would have bought is not a
        // behaviour this class depends on.
        val usedSoFar = (attemptsByIndex[index] ?: 0) + 1
        attemptsByIndex[index] = usedSoFar
        val record = FailoverRecord(current.rank, current.releaseId, current.displayLabel(), displaySummary, "")

        return when {
            // retry_same budget still available for THIS candidate
            usedSoFar <= policy.retrySame -> {
                _log.add(record.copy(action = "retried (same rank)"))
                FailoverDecision.RetrySame(index, policy.backoffMs, record.copy(action = "retry"))
            }

            !policy.thenNextRank -> {
                _log.add(record.copy(action = "stopped (policy)"))
                FailoverDecision.Handoff(HandoffWhy.NO_CANDIDATE_LEFT, displaySummary, record.copy(action = "stopped"))
            }

            else -> {
                // Same rung first, other copies next: a different server serving the
                // same quality is not a downgrade, so it costs no rank and says nothing.
                val backup = nextBackupFor(index)
                if (backup != null) {
                    _log.add(record.copy(action = "silent hop within rung"))
                    return FailoverDecision.AdvanceBackup(
                        index = index,
                        streamId = backup.first,
                        playUrl = backup.second,
                        record = record.copy(action = "hopped to a runner-up of this rung"),
                    )
                }
                advanceToNextRank(index, displaySummary, record)
            }
        }
    }

    /**
     * Move to the next playable rank after this one, or hand off when no rank remains.
     * Shared by the ordinary exhaustion path and the gate-refusal path, so both agree
     * about what "no candidates remain" means.
     */
    private fun advanceToNextRank(
        index: Int,
        displaySummary: String,
        record: FailoverRecord,
        handoffWhy: HandoffWhy = HandoffWhy.NO_CANDIDATE_LEFT,
    ): FailoverDecision {
        ranksBurned += 1
        val next = (index + 1 until renditions.size).firstOrNull { isPlayable(it) }
        // A record that already names its action (the gate refusal) keeps it; the
        // ordinary path arrives with a blank action and gets the generic one.
        _log.add(record.copy(action = record.action.ifBlank { "died → failover" }))
        // Walk forward while candidates are keep-only/none — record each skip honestly.
        var probe = next
        while (probe != null && !isPlayable(probe)) {
            val skipped = renditions[probe]
            _log.add(skipRecord(probe, skipped))
            probe = (probe + 1 until renditions.size).firstOrNull { isPlayable(it) }
        }
        return when {
            probe != null && ranksBurned < policy.maxRanks -> {
                activeIndex = probe
                val target = renditions[probe]
                FailoverDecision.Advance(probe, target.displayLabel(), record)
            }
            probe != null && ranksBurned >= policy.maxRanks -> {
                // §5: never beyond max_ranks, even if a later rank looks alive.
                FailoverDecision.Handoff(
                    handoffWhy,
                    "Reached max_ranks=${policy.maxRanks} without stable playback",
                    record.copy(action = "stopped (max_ranks)"),
                )
            }
            else -> FailoverDecision.Handoff(
                handoffWhy,
                displaySummary,
                record.copy(action = "no candidates remain"),
            )
        }
    }

    /**
     * The first candidate that could only be kept, if any — the handoff UI offers it instead of
     * pretending there was no such link. Quality words only, so this cannot name a hoster.
     */
    fun keepOnlyFallback(): PlaybackRendition? =
        renditions.firstOrNull { !it.playback.playUrl.isNullOrBlank() }

}
