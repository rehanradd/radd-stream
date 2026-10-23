package com.raddstream.app.player
import com.raddstream.app.network.models.CoverageType

/**
 * Episode offsets — client side of the durable `cat_offsets` ledger
 * (`Fast_Fetch/catalog_v2.py` DDL lines 304-314 and `record_offset()`).
 *
 * Semantics preserved here:
 *  - keyed by **stable identity** `(work_key, season_number, episode_number, release_label)`
 *    (the projection rewrites `cat_release_episodes` on every rebuild; offsets must survive it),
 *  - latest write wins, repeated confirmations accumulate (`confirmed_by` server-side),
 *  - an offset of `null` means "season pack, nobody has calibrated it yet" →
 *    `coverage.needs_offset_calibration` UI path from API_V2.md §2.3.
 *
 * Persistence note: this store is in-process memory only. Surviving app restarts requires the
 * data agent's DataStore/Room — exact request in `HANDOFF_appplayer.md`. Server reporting goes
 * through [OffsetReporter]; the real `POST /api/v2/episodes/{id}/offset` call (API_V2 §8) is
 * owned by the network agent, so the default reporter *buffers honestly* instead of faking.
 */

data class OffsetKey(
    val workKey: String,
    val seasonNumber: Int = 0,
    val episodeNumber: Int,
    /** Empty string = applies to any print label (matches cat_offsets default). */
    val releaseLabel: String = "",
)

/** Payload mirroring `catalog_v2.record_offset()` arguments. */
data class OffsetReport(
    val workKey: String,
    val seasonNumber: Int,
    val episodeNumber: Int,
    val releaseLabel: String,
    val offsetSeconds: Int,
    val chapterTitle: String? = null,
)

interface OffsetReporter {
    /** Fire-and-forget; implementations must not throw into the playback thread. */
    fun report(report: OffsetReport)
}

/**
 * Honest placeholder until the Retrofit call exists: keeps everything it would have sent so
 * the UI can show "queued, not yet uploaded", and a future network impl can drain [pending].
 */
class DeferredOffsetReporter : OffsetReporter {
    private val queue = java.util.concurrent.ConcurrentLinkedQueue<OffsetReport>()

    override fun report(report: OffsetReport) {
        queue.add(report)
    }

    /** Snapshot of unsent reports (oldest first). */
    fun pending(): List<OffsetReport> = ArrayList(queue)

    fun drain(): List<OffsetReport> {
        val out = ArrayList<OffsetReport>()
        while (true) {
            val head = queue.poll() ?: break
            out.add(head)
        }
        return out
    }
}

/** In-memory learned-offset store, latest-write-wins per stable key (mirrors cat_offsets). */
class LearnedOffsetStore {

    private data class Entry(val report: OffsetReport, val seq: Long)

    private val offsets = java.util.concurrent.ConcurrentHashMap<OffsetKey, Entry>()
    private val clock = java.util.concurrent.atomic.AtomicLong(0)

    fun learn(report: OffsetReport, reporter: OffsetReporter) {
        offsets[normalizeKey(report)] = Entry(report, clock.incrementAndGet())
        reporter.report(report) // may buffer/queue; must never throw here
    }

    /** Exact print-label row first, then the release-agnostic row; newest write wins. */
    fun lookup(workKey: String?, season: Int, episode: Int, releaseLabel: String?): Int? {
        if (workKey.isNullOrBlank() || episode <= 0) return null
        val label = releaseLabel.orEmpty()
        val exact = offsets[OffsetKey(workKey, season, episode, label)]
        val generic = offsets[OffsetKey(workKey, season, episode, "")]
        val best = when {
            exact == null -> generic
            generic == null -> exact
            exact.seq >= generic.seq -> exact
            else -> generic
        }
        return best?.report?.offsetSeconds
    }

    fun all(): List<OffsetReport> = offsets.values.map { it.report }

    private fun normalizeKey(r: OffsetReport) =
        OffsetKey(r.workKey, r.seasonNumber, r.episodeNumber, r.releaseLabel)
}

/** Outcome of "where does the requested episode actually start inside this file?" */
sealed class StartResolution {
    /** Absolute start position inside the media, milliseconds. */
    data class At(val positionMs: Long, val fromLearnedOffset: Boolean, val chapterTitle: String?) : StartResolution()

    /** Whole film / single episode file: start at 0 (or resume point handled separately). */
    object FromZero : StartResolution()

    /** Packed file with no known offset for this episode → calibration UI required. */
    data class NeedsCalibration(val packWarning: String?) : StartResolution()
}

object EpisodeOffsets {

    /**
     * Resolution order (API_V2 §2.3 + §5): locally-learned offset > server-provided
     * `coverage.offset_seconds`/episode chapter row > unknown.
     */
    fun resolveStart(
        rendition: PlaybackRendition,
        target: PlayTarget,
        learned: LearnedOffsetStore,
    ): StartResolution {
        val coverage = rendition.coverage
        return when (coverage.type()) {
            CoverageType.SINGLE_EPISODE, CoverageType.WHOLE_WORK, CoverageType.PARTS,
            CoverageType.UNKNOWN,
            -> StartResolution.FromZero

            CoverageType.SEASON_PACK, CoverageType.EPISODE_RANGE -> {
                val episode = if (target.episode > 0) target.episode else coverage.ordinal
                val label = rendition.print.label.orEmpty()
                val learnedOffset = learned.lookup(
                    workKey = target.workKey,
                    season = coverage.season,
                    episode = episode,
                    releaseLabel = label,
                )
                when {
                    learnedOffset != null ->
                        StartResolution.At(learnedOffset * 1000L, true, null)
                    coverage.serverOffsetFor(episode) != null ->
                        StartResolution.At(coverage.serverOffsetFor(episode)!! * 1000L, false, null)
                    coverage.needsOffsetCalibration || episode > 0 ->
                        StartResolution.NeedsCalibration(coverage.packWarning)
                    else -> StartResolution.FromZero
                }
            }
        }
    }

    /** Build the report the backend persists into `cat_offsets` via record_offset(). */
    fun buildReport(
        target: PlayTarget,
        rendition: PlaybackRendition,
        episodeNumber: Int,
        offsetMs: Long,
        chapterTitle: String?,
    ): OffsetReport? {
        val workKey = target.workKey ?: return null
        return OffsetReport(
            workKey = workKey,
            seasonNumber = rendition.coverage.season,
            episodeNumber = episodeNumber,
            releaseLabel = rendition.print.label.orEmpty(),
            offsetSeconds = (offsetMs / 1000L).toInt().coerceAtLeast(0),
            chapterTitle = chapterTitle,
        )
    }
}
