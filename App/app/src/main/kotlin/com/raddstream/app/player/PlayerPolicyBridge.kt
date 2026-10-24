package com.raddstream.app.player

import kotlin.math.roundToInt

/*
 * ─────────────────────────────────────────────────────────────────────────────
 *  THE WIRING LAYER — player state in, policy inputs out
 * ─────────────────────────────────────────────────────────────────────────────
 * The four policy classes next to this file (AudioBoost, AudioTrackMatcher,
 * AdaptiveQualitySwitcher, BingePreloader) are deliberately Android-free, and the
 * player around them is deliberately not. This file is the seam: it holds NO rule of
 * its own, only the reduction from what Media3 reports to what a rule consumes, plus
 * the small amount of state a rule needs but refuses to own (the fire-once set, the
 * staged ladder, "which rung are we actually playing").
 *
 * Everything here is plain Kotlin, so the seam itself is JVM-unit-testable:
 * PlayerPolicyBridgeTest exercises these reductions without a device.
 *
 * The rule that governs all of it: a value leaves this file only when the player can
 * really act on it. Where the platform caps a request, the cap is applied here and the
 * UI is given the honest sentence, never the aspiration.
 */

/**
 * One audio track reduced to what a language decision needs. Mirrors
 * [AudioCandidate] but is owned by the seam, because the player's own row type carries
 * a Media3 `TrackGroup` and a seam that needs a device to test is a seam nobody trusts.
 */
data class AudioTrackRow(
    val id: String,
    val language: String? = null,
    val label: String? = null,
    val selected: Boolean = false,
    val supported: Boolean = true,
)

/**
 * The audio-language preference applied to real track lists: [pickPreferred] for
 * "what should be playing", [nextInCycle] for "what the cycle button does next".
 * Both delegate every judgement to [AudioTrackMatcher]; this object only converts.
 */
object AudioTrackPolicy {

    fun candidates(rows: List<AudioTrackRow>): List<AudioCandidate> =
        rows.map { AudioCandidate(it.id, it.language, it.label, it.selected, it.supported) }

    /** The id to select, or null meaning "leave the player's own choice alone". */
    fun pickPreferred(rows: List<AudioTrackRow>, preferred: String?, fallback: String? = null): String? =
        AudioTrackMatcher.match(candidates(rows), preferred, fallback)

    /** The id to select when the user cycles, or null when cycling is not worth offering. */
    fun nextInCycle(rows: List<AudioTrackRow>, currentId: String?): String? =
        AudioTrackMatcher.cycle(candidates(rows), currentId)

    /** True when a cycle control would actually change the sound. */
    fun canCycle(rows: List<AudioTrackRow>): Boolean =
        rows.count { it.supported } >= 2

    /** The English name for a language tag, when this catalog knows it; null otherwise. */
    fun nameFor(tag: String?): String? = AudioTrackMatcher.displayName(tag)
}

/**
 * [BingePreloader] plus the fire-once set its contract makes the CALLER own.
 *
 * The policy is stateless on purpose, and the player's progress tick is delivered
 * hundreds of times per episode, so somebody has to remember that this episode already
 * asked for its successor. That somebody is this class: [tick] returns a
 * [BingePreloadDecision.PrefetchNextHead] at most once per handle, for the whole life of
 * the planner. A new episode means a new bundle, which means [reset].
 *
 * It does not execute anything — the caller decides what "prefetch" can honestly mean on
 * the engine boundary it has.
 */
class BingePrefetchPlanner(
    private val preloader: BingePreloader = BingePreloader(),
) {

    private val requested = LinkedHashSet<String>()

    /** Handles this planner already asked for; exposed for diagnostics only. */
    fun alreadyRequested(): Set<String> = requested.toSet()

    fun tick(
        positionMs: Long,
        durationMs: Long,
        isSeries: Boolean,
        nextEpisodeHandle: String?,
    ): BingePreloadDecision {
        val decision = preloader.decide(
            BingePreloadState(positionMs, durationMs, isSeries, nextEpisodeHandle),
            requested,
        )
        if (decision is BingePreloadDecision.PrefetchNextHead) requested.add(decision.handle)
        return decision
    }

    fun reset() {
        requested.clear()
    }
}

/**
 * One rung of the server's ladder, in the shape Auto needs: the band name the switcher
 * reasons about, the opaque handle of ours that plays it, and that rung's own silent
 * runner-ups (handles only, never addresses).
 */
data class LadderRung(
    val band: String,
    val streamId: String,
    val backupHandles: List<String> = emptyList(),
    /** The server's own quality-only caption for this rung ("Full HD · X264"); null = show the band. */
    val label: String? = null,
) {
    val usable: Boolean get() = band.isNotBlank() && streamId.isNotBlank()
}

/**
 * [AdaptiveQualitySwitcher] plus the two pieces of context it deliberately does not hold:
 * which rungs exist, and which rung the player is actually on right now.
 *
 * Two callers share one instance through [PlayerSessionStore.autoQuality]: the service
 * feeds samples and asks for a rung, the ViewModel only reads [currentBand] and
 * [estimateBps] to display. Hence the volatile fields — a UI read must never be allowed
 * to disagree with the service that is switching.
 */
class AutoQualityDirector(
    private val switcher: AdaptiveQualitySwitcher = AdaptiveQualitySwitcher(),
) {

    private var rungs: List<LadderRung> = emptyList()

    @Volatile
    private var auto: Boolean = false

    @Volatile
    private var band: String? = null

    /** The rung the director believes is playing, for the top-bar "Auto" label. */
    val currentBand: String? get() = band

    /** Smoothed throughput in bits/sec; 0 until a sample was accepted. */
    val estimateBps: Long get() = switcher.estimateBps

    /** Accepted samples in the switcher's ring — 0 means the estimate is not yet real. */
    val sampleCount: Int get() = switcher.acceptedSampleCount

    /**
     * Arm the director for one playback. [rungs] are the bands offered in the CURRENT
     * scope (server order), [startBand] the rung playback begins on, [auto] false when the
     * user picked a band by hand — a manual choice outranks any estimate, so the director
     * then reports [currentBand] and never proposes a move.
     */
    fun configure(rungs: List<LadderRung>, startBand: String?, auto: Boolean) {
        switcher.reset()
        this.rungs = rungs.filter { it.usable }.distinctBy { it.band }
        this.auto = auto
        this.band = startBand?.takeIf { rungFor(it) != null } ?: this.rungs.firstOrNull()?.band
    }

    /** Disabled unless Auto is on and the ladder can actually move (two rungs minimum). */
    fun isEnabled(): Boolean = auto && rungs.size >= 2

    /** Feed one measured transfer. Returns false when the sample was refused or unused. */
    fun push(bytes: Long, elapsedMs: Long): Boolean = isEnabled() && switcher.push(bytes, elapsedMs)

    /**
     * Which rung Auto wants now, updating [currentBand] to the answer. Null when nothing
     * is armed. Calling this repeatedly is safe: the switcher's hysteresis keeps returning
     * the current rung inside the dead zone, which is what stops oscillation.
     */
    fun targetBand(): String? {
        if (!isEnabled()) return band
        val next = switcher.pickBand(rungs.map { it.band }, band, true)
        if (next != null) band = next
        return band
    }

    /**
     * Correct the director to the truth from outside: the rung actually playing after a
     * switch that was refused, or after a failover moved playback by itself. Does not
     * discard the throughput history — the network picture is still valid, only the rung
     * assumption was wrong.
     */
    fun markPlaying(playingBand: String?) {
        band = playingBand?.takeIf { rungFor(it) != null } ?: band
    }

    fun rungFor(band: String?): LadderRung? = if (band == null) null else rungs.firstOrNull { it.band == band }

    /** The handle of ours that plays [band]; null when that rung is not in this scope. */
    fun handleFor(band: String?): String? = rungFor(band)?.streamId

    /** Forget the throughput picture; call when a new media item starts. */
    fun reset() {
        switcher.reset()
    }
}

/**
 * The 0..2 boost level translated into the one value Media3 may be given, plus the
 * honest sentence about what that value means.
 *
 * WHY A CEILING EXISTS AND IS SAID OUT LOUD: `Player.setVolume` is documented 0..1, so
 * a "200%" request cannot be met by the player, and this build has no software gain
 * stage to meet it with either — media3 1.3.1 ships no `DynamicsProcessing` renderer and
 * the app declares no equalizer dependency. [effectivePlayerGain] therefore multiplies
 * the boost into the user's own volume and clamps the product to the contract. Below the
 * ceiling the boost is completely real (a viewer at 60% who asks for 150% gets 90%); at
 * the ceiling only the part up to 100% applies, and [honestSummary] says which part, so
 * the UI can never claim a boost it did not apply.
 */
object AudioBoostUi {

    /** False on this build: no software gain stage is available, so dB excess is refused. */
    const val SOFTWARE_GAIN_AVAILABLE: Boolean = false

    /** The single value that is legal for `Player.setVolume`, always within 0..1. */
    fun effectivePlayerGain(level: Float, userVolume: Float): Float {
        // clampLevel already kills a non-finite level, and a non-finite volume falls back to
        // unity, so the product below is always finite and its clamp is the player's contract.
        val safeVolume = if (userVolume.isFinite()) userVolume.coerceIn(0f, 1f) else 1f
        return (AudioBoost.clampLevel(level) * safeVolume).coerceIn(0f, 1f)
    }

    /** Percent actually applied to the player, for the caption and the HUD. */
    fun appliedPercent(level: Float, userVolume: Float): Int =
        (effectivePlayerGain(level, userVolume) * 100f).roundToInt()

    /** Requested percent, clamped exactly as the policy clamps it. */
    fun requestedPercent(level: Float): Int = (AudioBoost.clampLevel(level) * 100f).roundToInt()

    /**
     * User-facing caption. Never promises more than [effectivePlayerGain] delivers: at or
     * below the ceiling it states the level, above it states the request AND the applied
     * value, because those differ and the difference is the honest part.
     */
    fun honestSummary(level: Float, userVolume: Float): String {
        val plan = AudioBoost.plan(level)
        if (!plan.boostActive) return AudioBoost.labelFor(level)
        val requested = requestedPercent(level)
        val applied = appliedPercent(level, userVolume)
        return if (applied >= 100) {
            "Requested $requested% — applied at the 100% player ceiling; " +
                "the extra ${requested - 100}% needs system volume, this build adds no software gain."
        } else {
            "Requested $requested% — applied $applied% of the player's 0..100% range; " +
                "no software gain is available on this build."
        }
    }
}
