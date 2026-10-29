package com.raddstream.app.player
import com.raddstream.app.network.models.Playability

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
 */
enum class HandoffWhy { DOWNLOAD_ONLY, NO_CANDIDATE_LEFT }

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

    /** Call when the active rendition fails with [errorSummary]. Returns the mandated next step. */
    fun onFailure(errorSummary: String): FailoverDecision {
        val index = activeIndex
        val current = renditions.getOrNull(index)
            ?: return FailoverDecision.Handoff(HandoffWhy.NO_CANDIDATE_LEFT, errorSummary, null)
        // Read-modify-write instead of `HashMap.merge`: `merge` is a Java 8 default method and
        // lint correctly refuses it against minSdk 21 (it ships in API 24). The count below is
        // only ever read on this thread, so the atomicity `merge` would have bought is not a
        // behaviour this class depends on.
        val usedSoFar = (attemptsByIndex[index] ?: 0) + 1
        attemptsByIndex[index] = usedSoFar
        val record = FailoverRecord(current.rank, current.releaseId, current.displayLabel(), errorSummary, "")

        return when {
            // retry_same budget still available for THIS candidate
            usedSoFar <= policy.retrySame -> {
                _log.add(record.copy(action = "retried (same rank)"))
                FailoverDecision.RetrySame(index, policy.backoffMs, record.copy(action = "retry"))
            }

            !policy.thenNextRank -> {
                _log.add(record.copy(action = "stopped (policy)"))
                FailoverDecision.Handoff(HandoffWhy.NO_CANDIDATE_LEFT, errorSummary, record.copy(action = "stopped"))
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
                ranksBurned += 1
                val next = (index + 1 until renditions.size).firstOrNull { isPlayable(it) }
                _log.add(record.copy(action = "died → failover"))
                // Walk forward while candidates are keep-only/none — record each skip honestly.
                var probe = next
                while (probe != null && !isPlayable(probe)) {
                    val skipped = renditions[probe]
                    _log.add(skipRecord(probe, skipped))
                    probe = (probe + 1 until renditions.size).firstOrNull { isPlayable(it) }
                }
                when {
                    probe != null && ranksBurned < policy.maxRanks -> {
                        activeIndex = probe
                        val target = renditions[probe]
                        FailoverDecision.Advance(probe, target.displayLabel(), record)
                    }
                    probe != null && ranksBurned >= policy.maxRanks -> {
                        // §5: never beyond max_ranks, even if a later rank looks alive.
                        FailoverDecision.Handoff(
                            HandoffWhy.NO_CANDIDATE_LEFT,
                            "Reached max_ranks=${policy.maxRanks} without stable playback",
                            record.copy(action = "stopped (max_ranks)"),
                        )
                    }
                    else -> FailoverDecision.Handoff(
                        HandoffWhy.NO_CANDIDATE_LEFT,
                        errorSummary,
                        record.copy(action = "no candidates remain"),
                    )
                }
            }
        }
    }

    /**
     * The first candidate that could only be kept, if any — the handoff UI offers it instead of
     * pretending there was no such link. Quality words only, so this cannot name a hoster.
     */
    fun keepOnlyFallback(): PlaybackRendition? =
        renditions.firstOrNull { !it.playback.playUrl.isNullOrBlank() }

}
