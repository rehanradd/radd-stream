package com.raddstream.app.player

import kotlin.math.abs
import kotlin.math.log10
import kotlin.math.roundToInt

/**
 * The user-facing audio level in 0..2 where 1.0 is the untouched baseline and 2.0 is the
 * MX Player "200% software boost" ceiling.
 */
private const val MIN_LEVEL = 0f
private const val MAX_LEVEL = 2f

/**
 * Why the split exists: Media3 documents `Player.setVolume` as a 0..1 linear gain. Anything
 * above 1.0 is outside the type's contract — pushing a 1.5 there is a bug, not a boost. So a
 * single "200%" request cannot be satisfied by the player alone. This policy separates the one
 * legal request into the two honest handles the platform actually offers, so the caller can
 * raise the *system stream volume* toward its hardware ceiling for the portion the player can
 * legitimately represent, and carry the remainder as *software dB* that only a
 * `DynamicsProcessing`/equalizer preset can apply. A caller without such a preset refuses the
 * excess rather than corrupting the 0..1 contract. Levels at or below 1.0 need no software
 * handling at all; exactly 1.0 changes nothing, so it must not even request a device move.
 */
object AudioBoost {

    /** Anchor level: leave the device and the player exactly as they are. */
    const val BASELINE: Float = 1f

    /** Largest level the policy models (200%). */
    const val MAX: Float = MAX_LEVEL

    /**
     * Sanitised, clamped view of a raw request. A non-finite level (NaN / ±Infinity) is treated
     * as "no valid gesture target" and collapses to the baseline rather than propagating poison
     * into a device write.
     */
    fun clampLevel(level: Float): Float =
        if (!level.isFinite()) BASELINE else level.coerceIn(MIN_LEVEL, MAX_LEVEL)

    /**
     * Split a raw level into the device-fraction / player-gain / software-dB triple. Every
     * computed field is safe for its sink: [BoostPlan.deviceStreamFraction] and
     * [BoostPlan.playerGain] are always within 0..1, and [BoostPlan.gainDb] is never negative
     * (attenuation is expressed through the fractions, not through a sub-unity dB).
     */
    fun plan(level: Float): BoostPlan {
        val eff = clampLevel(level)
        val deviceFraction = eff.coerceIn(MIN_LEVEL, 1f)
        val playerGain = eff.coerceIn(MIN_LEVEL, 1f)
        val gainDb = if (eff > 1f) (20.0 * log10(eff.toDouble())).toFloat() else 0f
        val boostActive = gainDb > 0f
        val reason = if (boostActive) {
            "Boost to +%.1f dB needs a DynamicsProcessing/equalizer preset; " +
                "Media3 Player.setVolume cannot exceed 1.0, so the %.0f%% over the " +
                "hardware ceiling is applied as software gain or refused."
                .format(gainDb, (eff - 1f) * 100f)
        } else {
            null
        }
        return BoostPlan(
            level = eff,
            deviceStreamFraction = deviceFraction,
            playerGain = playerGain,
            gainDb = gainDb,
            requestsDeviceChange = eff != BASELINE,
            boostActive = boostActive,
            reason = reason,
        )
    }

    /**
     * Apply a swipe delta to the current level. Never overshoots the 0..2 clamp; a non-finite
     * operand resets the HUD to the baseline instead of latching NaN.
     */
    fun step(current: Float, delta: Float): Float {
        val next = current + delta
        return if (!next.isFinite()) BASELINE else next.coerceIn(MIN_LEVEL, MAX_LEVEL)
    }

    /**
     * User-facing text, e.g. "Volume 140%". Purely numeric by construction: it names only the
     * level, never a source site, hoster, or URL, so it can never leak provenance.
     */
    fun labelFor(level: Float): String {
        val percent = (clampLevel(level) * 100f).roundToInt()
        return "Volume $percent%"
    }
}

/**
 * Immutable result of [AudioBoost.plan]. Carries both the values ready to hand to their sinks
 * and the flags a caller needs to decide whether to act. [playerGain] is the value that is safe
 * for `Player.setVolume` (it can never exceed 1.0); [deviceStreamFraction] is the target for the
 * system stream volume; [gainDb] is the software excess to feed a DynamicsProcessing preset.
 * [playerGain] and [deviceStreamFraction] encode the *same* at-or-below-unity portion — a caller
 * applies one handle for that region, never their product. [reason] is null whenever no software
 * excess exists.
 */
data class BoostPlan(
    val level: Float,
    val deviceStreamFraction: Float,
    val playerGain: Float,
    val gainDb: Float,
    val requestsDeviceChange: Boolean,
    val boostActive: Boolean,
    val reason: String?,
) {
    init {
        require(deviceStreamFraction in 0f..1f) { "device fraction out of 0..1 contract" }
        require(playerGain in 0f..1f) { "player gain out of 0..1 contract" }
        require(gainDb >= 0f || abs(gainDb) < 1e-6f) { "software gain must not be negative" }
    }
}
