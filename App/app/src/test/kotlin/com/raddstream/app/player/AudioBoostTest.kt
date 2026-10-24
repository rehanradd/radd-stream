package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * JVM-only contract tests for the audio-boost policy. Robolectric-free: AudioBoost touches no
 * Android, so the 0..1 split, the dB maths, and the provenance-safe label are all assertable
 * directly. The +6.02 dB figure is the headline: it is 20*log10(2), the theoretical ceiling of a
 * "200%" software boost.
 */
class AudioBoostTest {

    private val delta = 0.01f

    @Test
    fun `zero level is full attenuation with no boost`() {
        val plan = AudioBoost.plan(0f)
        assertEquals(0f, plan.level, delta)
        assertEquals(0f, plan.deviceStreamFraction, delta)
        assertEquals(0f, plan.playerGain, delta)
        assertEquals(0f, plan.gainDb, delta)
        assertFalse(plan.boostActive)
        assertTrue(plan.requestsDeviceChange)
    }

    @Test
    fun `half level maps linearly and asks for nothing above unity`() {
        val plan = AudioBoost.plan(0.5f)
        assertEquals(0.5f, plan.level, delta)
        assertEquals(0.5f, plan.deviceStreamFraction, delta)
        assertEquals(0.5f, plan.playerGain, delta)
        assertEquals(0f, plan.gainDb, delta)
        assertFalse(plan.boostActive)
    }

    @Test
    fun `baseline is exactly one with zero db and no device change`() {
        val plan = AudioBoost.plan(1f)
        assertEquals(1f, plan.level, delta)
        assertEquals(1f, plan.playerGain, delta)
        assertEquals(1f, plan.deviceStreamFraction, delta)
        assertEquals(0f, plan.gainDb, delta)
        assertFalse(plan.boostActive)
        assertFalse(plan.requestsDeviceChange)
        assertNull(plan.reason)
    }

    @Test
    fun `one and a half splits into full device plus positive db`() {
        val plan = AudioBoost.plan(1.5f)
        assertEquals(1f, plan.deviceStreamFraction, delta)
        assertEquals(1f, plan.playerGain, delta)
        assertTrue(plan.boostActive)
        assertTrue(plan.requestsDeviceChange)
        // 20*log10(1.5) ~= 3.52 dB
        assertEquals(3.52f, plan.gainDb, delta)
        assertTrue(plan.reason != null && plan.reason!!.contains("dB"))
    }

    @Test
    fun `two hundred percent is about six point zero two db`() {
        val plan = AudioBoost.plan(2f)
        assertEquals(2f, plan.level, delta)
        assertEquals(1f, plan.deviceStreamFraction, delta)
        assertEquals(1f, plan.playerGain, delta)
        assertTrue(plan.boostActive)
        // 20*log10(2) = 6.0205999... dB
        assertEquals(6.02f, plan.gainDb, delta)
    }

    @Test
    fun `clamps below zero`() {
        assertEquals(0f, AudioBoost.plan(-1f).level, delta)
        assertEquals(0f, AudioBoost.plan(-1f).playerGain, delta)
    }

    @Test
    fun `clamps above the ceiling`() {
        assertEquals(2f, AudioBoost.plan(3f).level, delta)
        assertEquals(6.02f, AudioBoost.plan(3f).gainDb, delta)
    }

    @Test
    fun `non finite levels collapse to baseline`() {
        for (bad in listOf(Float.NaN, Float.POSITIVE_INFINITY, Float.NEGATIVE_INFINITY)) {
            val plan = AudioBoost.plan(bad)
            assertEquals(1f, plan.level, delta)
            assertEquals(0f, plan.gainDb, delta)
            assertFalse(plan.boostActive)
            assertFalse(plan.requestsDeviceChange)
        }
    }

    @Test
    fun `player gain never exceeds the media3 zero to one contract`() {
        val samples = floatArrayOf(-5f, 0f, 0.3f, 0.7f, 1f, 1.3f, 1.9f, 2f, 9f, Float.NaN)
        for (s in samples) {
            val plan = AudioBoost.plan(s)
            assertTrue("playerGain ${plan.playerGain} > 1", plan.playerGain <= 1f)
            assertTrue("playerGain ${plan.playerGain} < 0", plan.playerGain >= 0f)
            assertTrue("device ${plan.deviceStreamFraction} > 1", plan.deviceStreamFraction <= 1f)
        }
        // Positive infinity must not smuggle an out-of-range gain through.
        assertTrue(AudioBoost.plan(Float.POSITIVE_INFINITY).playerGain <= 1f)
    }

    @Test
    fun `label is purely numeric and never names a source`() {
        assertEquals("Volume 140%", AudioBoost.labelFor(1.4f))
        assertEquals("Volume 100%", AudioBoost.labelFor(1f))
        assertEquals("Volume 200%", AudioBoost.labelFor(2f))
        assertEquals("Volume 0%", AudioBoost.labelFor(0f))
        assertEquals("Volume 50%", AudioBoost.labelFor(0.5f))
        assertEquals("Volume 100%", AudioBoost.labelFor(Float.NaN))
        // Provenance rule: the label carries only the number.
        val label = AudioBoost.labelFor(1.7f)
        assertTrue(label, label.matches(Regex("""Volume \d+%""")))
        for (banned in listOf("http", ".com", "/", "vegamovies", "multimovies", "stream")) {
            assertFalse("label leaks '$banned': $label", label.contains(banned, ignoreCase = true))
        }
    }

    @Test
    fun `step applies delta without overshooting the clamp`() {
        assertEquals(1.8f, AudioBoost.step(1.5f, 0.3f), delta)
        assertEquals(0.2f, AudioBoost.step(0.5f, -0.3f), delta)
        assertEquals(2f, AudioBoost.step(2f, 5f), delta)      // ceiling
        assertEquals(2f, AudioBoost.step(1.9f, 0.5f), delta)  // no overshoot upward
        assertEquals(0f, AudioBoost.step(0f, -3f), delta)     // floor
        assertEquals(0f, AudioBoost.step(0.1f, -0.5f), delta) // no overshoot downward
        assertEquals(1f, AudioBoost.step(Float.NaN, 0.1f), delta)
        assertEquals(1f, AudioBoost.step(2f, Float.NaN), delta)
    }
}
