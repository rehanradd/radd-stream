package com.raddstream.app.player

import kotlin.math.roundToLong

/**
 * Adaptive Network Quality Switcher — picks which band of the server's quality ladder
 * (`2160p / 1080p / 720p / 480p / sd / unspecified`, plus the ladder's `auto` pointer) the
 * player should follow when the user left quality on Auto.
 *
 * WHY THIS EXISTS: the server hands one best-and-fastest option per band, so the client's only
 * job is deciding *which rung it can actually feed*. That decision is fed by throughput samples
 * the caller measures from Media3's own load statistics — this class never touches the player,
 * the network or any Android type, so the whole policy is JVM-unit-testable and auditable.
 *
 * WHY HYSTERESIS: a naive "pick the highest band under the current estimate" rule oscillates
 * badly, because measured throughput jitters by tens of percent second to second and every
 * band switch costs a re-buffer. Two asymmetric guards stop that:
 *  - stepping UP requires the smoothed estimate to clear the higher band's nominal bitrate by
 *    [stepUpMargin] (1.3x by default) — a fleeting spike is never enough;
 *  - stepping DOWN requires the estimate to sit under the current band's nominal bitrate times
 *    [stepDownMargin] (0.8x) for [stepDownConfirmSamples] consecutive accepted samples — one
 *    stalled interval downgrades nothing.
 * Between the two thresholds lies a dead zone where the choice never changes, which is exactly
 * where a boundary-sitting estimate must remain parked.
 *
 * WHY SMOOTHING + A RING + A MEDIAN GUARD: a single measurement is meaningless (buffer flushes,
 * chunk boundaries, a 0-byte statistic from a cancelled load). Raw samples live in a small
 * ring so old network conditions are forgotten, the estimate is an exponential smoothing over
 * that ring, and any sample that differs from the ring's median by more than [outlierRatio]
 * is refused outright — rejection also pauses the step-down strike counter, so a corrupt
 * reading can neither collapse the estimate nor push the player down a rung.
 */
class AdaptiveQualitySwitcher(
    /** Number of raw samples remembered; older conditions age out of the estimate. */
    private val windowSize: Int = 8,
    /** Weight of the newest sample in the ring's exponential smoothing (0..1). */
    private val alpha: Double = 0.35,
    /** A higher rung is only taken when the estimate beats its nominal bitrate by this factor. */
    private val stepUpMargin: Double = 1.3,
    /** The current rung is only abandoned below nominal * this factor, and only after N samples. */
    private val stepDownMargin: Double = 0.8,
    /** Consecutive accepted samples below the down threshold required before stepping down. */
    private val stepDownConfirmSamples: Int = 5,
    /** A sample this many times away from the ring median (either direction) is refused. */
    private val outlierRatio: Double = 50.0,
) {

    init {
        require(windowSize >= 1) { "windowSize must be >= 1" }
        require(alpha > 0.0 && alpha < 1.0) { "alpha must be in (0,1)" }
        require(stepDownConfirmSamples >= 1) { "stepDownConfirmSamples must be >= 1" }
        require(stepUpMargin > stepDownMargin) {
            "stepUpMargin must exceed stepDownMargin or the dead zone inverts and oscillates"
        }
    }

    private val samples = ArrayDeque<Long>()
    private var estimate = 0.0
    private var trackedBand: String? = null
    private var downStrikes = 0

    /** Smoothed throughput in bits per second; 0 until at least one sample was accepted. */
    val estimateBps: Long get() = estimate.roundToLong()

    /** Accepted samples currently inside the ring (not counting refusals). */
    val acceptedSampleCount: Int get() = samples.size

    /**
     * Feed one measured transfer: [bytes] payload moved in [elapsedMs] as reported by the
     * caller's load statistics. Returns true when the sample was accepted and the estimate
     * updated; false when it was refused (zero/negative inputs, non-finite rate, or an outlier
     * far from the ring median). Refused samples change nothing — including the step-down
     * strike count, which is the point: a bad reading must not downgrade quality.
     */
    fun push(bytes: Long, elapsedMs: Long): Boolean {
        if (bytes <= 0L || elapsedMs <= 0L) return false
        val raw = bytes.toDouble() * 8_000.0 / elapsedMs.toDouble()
        if (!raw.isFinite() || raw <= 0.0) return false
        if (samples.size >= MIN_SAMPLES_FOR_OUTLIER_GUARD) {
            val median = ringMedian()
            if (median > 0.0 && (raw > median * outlierRatio || raw * outlierRatio < median)) {
                return false
            }
        }
        samples.addLast(raw.roundToLong())
        while (samples.size > windowSize) samples.removeFirst()
        estimate = smoothed()
        val band = trackedBand
        if (band != null && estimate < nominalBitrateFor(band) * stepDownMargin) {
            downStrikes++
        } else {
            downStrikes = 0
        }
        return true
    }

    /**
     * Which band Auto should select right now, given the ladder [bands] (server order, best
     * first) and the band the player is on ([current]).
     *
     *  - empty ladder -> null (nothing to pick; the caller must not crash the overlay);
     *  - [auto] false -> [current] is returned untouched: a manual choice outranks any estimate;
     *  - no samples yet -> the first listed (highest offered) band: the ladder is ordered by
     *    what the server believes is best, and the hysteresis below protects the viewer from a
     *    rung the network cannot feed within a few confirmed samples;
     *  - otherwise the band may step UP immediately when the estimate clears a higher rung's
     *    nominal bitrate by [stepUpMargin], or step DOWN only after [stepDownConfirmSamples]
     *    consecutive samples under [stepDownMargin]; anything in between keeps [current], which
     *    is what kills oscillation at a boundary.
     *
     * Calling this also arms the step-down strike counter against the returned band, so the
     * intended wiring is: [push] from load statistics, [pickBand] whenever the UI needs the
     * current Auto answer.
     */
    fun pickBand(bands: List<String>, current: String?, auto: Boolean): String? {
        if (bands.isEmpty()) return null
        val validCurrent = current?.takeIf { bands.contains(it) }
        if (!auto || estimate <= 0.0) {
            val chosen = validCurrent ?: bands.first()
            adopt(chosen)
            return chosen
        }
        val ladder = bands.sortedByDescending { nominalBitrateFor(it) }
        val idx = if (validCurrent != null) ladder.indexOf(validCurrent) else -1
        if (idx < 0) {
            // Auto engaged mid-session with no known current rung: fit plainly, margins aside,
            // because there is no band to defend with hysteresis yet.
            val chosen = ladder.firstOrNull { estimate >= nominalBitrateFor(it) } ?: ladder.last()
            adopt(chosen)
            return chosen
        }
        val up = (0 until idx).firstOrNull {
            estimate >= nominalBitrateFor(ladder[it]) * stepUpMargin
        }
        if (up != null) {
            val chosen = ladder[up]
            adopt(chosen)
            return chosen
        }
        val struggling = estimate < nominalBitrateFor(ladder[idx]) * stepDownMargin
        if (struggling && downStrikes >= stepDownConfirmSamples) {
            val landing = ladder.indices.firstOrNull {
                it > idx && estimate >= nominalBitrateFor(ladder[it]) * stepDownMargin
            }
            val chosen = if (landing != null) ladder[landing] else ladder.last()
            adopt(chosen)
            return chosen
        }
        val hold = ladder[idx]
        adopt(hold)
        return hold
    }

    /** Forget everything: call when a new media item starts; the network picture is stale. */
    fun reset() {
        samples.clear()
        estimate = 0.0
        trackedBand = null
        downStrikes = 0
    }

    private fun adopt(band: String) {
        if (band != trackedBand) {
            trackedBand = band
            downStrikes = 0
        }
    }

    /** EMA folded oldest -> newest over the ring; re-folding keeps it stateless and stable. */
    private fun smoothed(): Double {
        if (samples.isEmpty()) return 0.0
        var e = samples.first().toDouble()
        for (i in 1 until samples.size) {
            e += alpha * (samples[i] - e)
        }
        return e
    }

    private fun ringMedian(): Double {
        val sorted = samples.sorted()
        val n = sorted.size
        return if (n % 2 == 1) {
            sorted[n / 2].toDouble()
        } else {
            (sorted[n / 2 - 1] + sorted[n / 2]) / 2.0
        }
    }

    companion object {
        /**
         * Nominal bitrate per band in bits per second — what it costs to feed each rung.
         * Lives here deliberately: it mirrors the server's ladder, and `unspecified` (and any
         * band name this client does not know yet) is treated as 720p so an unrecognized rung
         * is neither the automatic winner nor an unaffordable ghost.
         */
        const val BAND_2160_BPS = 25_000_000L
        const val BAND_1080_BPS = 6_000_000L
        const val BAND_720_BPS = 3_000_000L
        const val BAND_480_BPS = 1_200_000L
        const val BAND_SD_BPS = 600_000L
        const val BAND_UNSPECIFIED_BPS = BAND_720_BPS

        private const val MIN_SAMPLES_FOR_OUTLIER_GUARD = 4

        fun nominalBitrateFor(band: String): Long = when (band.trim().lowercase()) {
            "2160p" -> BAND_2160_BPS
            "1080p" -> BAND_1080_BPS
            "720p" -> BAND_720_BPS
            "480p" -> BAND_480_BPS
            "sd" -> BAND_SD_BPS
            else -> BAND_UNSPECIFIED_BPS
        }
    }
}
