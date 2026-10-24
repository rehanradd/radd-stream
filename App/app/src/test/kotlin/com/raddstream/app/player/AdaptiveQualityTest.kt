package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * JVM-level policy tests for [AdaptiveQualitySwitcher]: the whole reason the switcher is a
 * pure class is that every hysteresis rule below can be proven here without a device, a player
 * or a network. The sample arithmetic is exact on purpose — the step-down test counts the
 * precise confirmation window, and the boundary test asserts one fixed band across a long
 * alternating chain, which is exactly what a margin-free picker would thrash on.
 */
class AdaptiveQualityTest {

    private val ladder = listOf("2160p", "1080p", "720p", "480p", "sd", "unspecified")

    /** Push [times] samples of a steady [bps] stream, measured over 1000 ms intervals. */
    private fun AdaptiveQualitySwitcher.warm(bps: Long, times: Int) {
        repeat(times) { assertTrue(push(bps / 8, 1000L)) }
    }

    @Test
    fun `empty band list yields no pick`() {
        val aq = AdaptiveQualitySwitcher()
        assertNull(aq.pickBand(emptyList(), "720p", auto = true))
    }

    @Test
    fun `cold auto pick returns the first playable band`() {
        val aq = AdaptiveQualitySwitcher()
        assertEquals(0L, aq.estimateBps)
        assertEquals(ladder.first(), aq.pickBand(ladder, null, auto = true))
        assertEquals("2160p", aq.pickBand(ladder, null, auto = true))
    }

    @Test
    fun `manual choice is never overridden by the estimate`() {
        val aq = AdaptiveQualitySwitcher()
        aq.warm(40_000_000, 8)
        assertEquals("sd", aq.pickBand(ladder, "sd", auto = false))
        assertEquals("720p", aq.pickBand(ladder, "720p", auto = false))
    }

    @Test
    fun `sustained fast chain steps up toward the ladder top`() {
        val aq = AdaptiveQualitySwitcher()
        // 10 Mbps clears 1080p's 6 Mbps * 1.3 but not 2160p's 25 Mbps * 1.3.
        aq.warm(10_000_000, 8)
        assertEquals("1080p", aq.pickBand(ladder, "480p", auto = true))
        // A further sustained 40 Mbps chain clears the 2160p up-margin and steps once more.
        aq.warm(40_000_000, 8)
        assertEquals("2160p", aq.pickBand(ladder, "1080p", auto = true))
    }

    @Test
    fun `slow chain steps down only after the confirmation window`() {
        val aq = AdaptiveQualitySwitcher()
        aq.warm(10_000_000, 8)
        assertEquals("1080p", aq.pickBand(ladder, "1080p", auto = true))

        // With the ring full of 10 Mbps and alpha 0.35, the smoothed estimate only drops below
        // 6 Mbps * 0.8 on the THIRD slow sample, so strikes start at 3 and reach 5 at push 7.
        aq.warm(1_000_000, 3)
        assertEquals("1080p", aq.pickBand(ladder, "1080p", auto = true))
        aq.warm(1_000_000, 3)
        assertEquals("1080p", aq.pickBand(ladder, "1080p", auto = true))
        aq.push(1_000_000 / 8, 1000L) // 7th slow sample: the confirmation threshold is met.
        assertEquals("480p", aq.pickBand(ladder, "1080p", auto = true))
    }

    @Test
    fun `a single zero-byte sample does not collapse the estimate`() {
        val aq = AdaptiveQualitySwitcher()
        aq.warm(5_000_000, 8)
        val before = aq.estimateBps
        assertEquals(5_000_000L, before)

        assertFalse(aq.push(0L, 1000L))
        assertFalse(aq.push(1_000_000L, 0L))
        assertEquals(before, aq.estimateBps)
        // One corrupt reading must also not advance the step-down clock.
        assertEquals("1080p", aq.pickBand(ladder, "1080p", auto = true))
    }

    @Test
    fun `an absurd outlier is refused without disturbing the estimate`() {
        val aq = AdaptiveQualitySwitcher()
        aq.warm(5_000_000, 8)
        // 80 Gbps in 1 s against a 5 Mbps median ring: garbage, not a network upgrade.
        assertFalse(aq.push(10_000_000_000L, 1_000L))
        assertEquals(5_000_000L, aq.estimateBps)
        assertEquals("1080p", aq.pickBand(ladder, "1080p", auto = true))
        // But a genuine sustained climb (40 Mbps, an 8x ratio) passes the outlier guard.
        aq.warm(40_000_000, 8)
        assertEquals(40_000_000L, aq.estimateBps)
    }

    @Test
    fun `estimate parked on a band boundary never oscillates`() {
        val aq = AdaptiveQualitySwitcher()
        // Alternating 7 Mbps / 5 Mbps samples keep the smoothed estimate inside
        // (6 Mbps * 0.8, 6 Mbps * 1.3) — the dead zone around 1080p's nominal bitrate.
        var high = true
        for (i in 0 until 100) {
            val bps = if (high) 7_000_000L else 5_000_000L
            high = !high
            aq.push(bps / 8, 1000L)
            assertEquals("1080p", aq.pickBand(ladder, "1080p", auto = true))
        }
    }

    @Test
    fun `unknown and unspecified band names are priced as 720p`() {
        assertEquals(3_000_000L, AdaptiveQualitySwitcher.nominalBitrateFor("unspecified"))
        assertEquals(3_000_000L, AdaptiveQualitySwitcher.nominalBitrateFor("something-new"))
        assertEquals(3_000_000L, AdaptiveQualitySwitcher.nominalBitrateFor(" 720P "))
        assertEquals(25_000_000L, AdaptiveQualitySwitcher.nominalBitrateFor("2160p"))
        assertEquals(600_000L, AdaptiveQualitySwitcher.nominalBitrateFor("sd"))
    }

    @Test
    fun `reset forgets the whole network picture`() {
        val aq = AdaptiveQualitySwitcher()
        aq.warm(10_000_000, 8)
        aq.pickBand(ladder, "1080p", auto = true)
        aq.reset()
        assertEquals(0L, aq.estimateBps)
        assertEquals(0, aq.acceptedSampleCount)
        assertEquals(ladder.first(), aq.pickBand(ladder, null, auto = true))
    }
}
