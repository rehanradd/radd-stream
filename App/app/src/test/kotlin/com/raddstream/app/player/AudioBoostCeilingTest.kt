package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The audio control used to offer 0..200% while `Player.setVolume` stops at 100% and this build
 * carries no software-gain stage to reach past it: every drag above the ceiling moved a thumb
 * that changed nothing, and the label read a number the player had refused.
 *
 * The rule these tests pin is one sentence — a control may only offer what this build can apply
 * — while [AudioBoost]'s 0..2 model stays intact, because that is the policy a future
 * DynamicsProcessing stage plugs into.
 */
class AudioBoostCeilingTest {

    @Test
    fun `with no software gain the offered ceiling is the player ceiling`() {
        assertEquals(AudioBoost.BASELINE, AudioBoostUi.MAX_OFFERED_LEVEL, 1e-6f)
    }

    @Test
    fun `a request past the ceiling is offered AT the ceiling, not above it`() {
        assertEquals(1f, AudioBoostUi.offeredLevel(1.8f), 1e-6f)
        assertEquals("Volume 100%", AudioBoost.labelFor(AudioBoostUi.offeredLevel(1.8f)))
    }

    @Test
    fun `a level an older build stored above the ceiling is reduced on read`() {
        // DataStore may hold 2.0 from a build that offered the dead range; the state the screen
        // paints must still be a level the player can honour.
        assertEquals(1f, AudioBoostUi.offeredLevel(AudioBoost.MAX), 1e-6f)
    }

    @Test
    fun `every level the control can produce is applied in full at full system volume`() {
        val walk = (0..10).map { it / 10f }
        walk.forEach { level ->
            assertEquals(
                "requested $level must be what the player receives",
                AudioBoostUi.requestedPercent(level),
                AudioBoostUi.appliedPercent(level, 1f),
            )
        }
        assertEquals(11, walk.size)
    }

    @Test
    fun `a level below the ceiling is still completely real`() {
        // At 60% system volume a 100% ask lands at 60% — the boost is headroom, not extra volume,
        // and honestSummary is what says so.
        assertEquals(60, AudioBoostUi.appliedPercent(1f, 0.6f))
    }

    @Test
    fun `junk still collapses to the baseline rather than poisoning a device write`() {
        assertEquals(AudioBoost.BASELINE, AudioBoostUi.offeredLevel(Float.NaN), 1e-6f)
        assertEquals(AudioBoost.BASELINE, AudioBoostUi.offeredLevel(Float.POSITIVE_INFINITY), 1e-6f)
        assertEquals(0f, AudioBoostUi.offeredLevel(-3f), 1e-6f)
    }

    /**
     * The policy object keeps modelling the excess. If it stopped doing so, the day a software
     * gain stage exists would mean rewriting the rule rather than flipping
     * [AudioBoostUi.SOFTWARE_GAIN_AVAILABLE] and letting the controls widen from one value.
     */
    @Test
    fun `the refusal is at the control, not inside the policy`() {
        assertEquals(2f, AudioBoost.MAX, 1e-6f)
        assertTrue(AudioBoost.plan(1.5f).boostActive)
        assertTrue(AudioBoost.plan(1.5f).gainDb > 0f)
        assertEquals(1f, AudioBoost.plan(1.5f).playerGain, 1e-6f)
    }
}
