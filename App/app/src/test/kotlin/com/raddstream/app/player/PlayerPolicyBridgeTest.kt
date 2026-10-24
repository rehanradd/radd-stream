package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * JVM tests for the wiring seam — the code that turns what Media3 reports into what the
 * four policy classes consume. The policies have their own suites; these cover the parts
 * only the seam is responsible for: the fire-once set it owns on the policy's behalf, the
 * rung bookkeeping it adds to the switcher, the 0..1 clamp the platform's contract demands,
 * and the caption that must never overstate what was applied.
 */
class PlayerPolicyBridgeTest {

    // ── audio language: preferred pick + cycle ─────────────────────────────────

    private val dualAudio = listOf(
        AudioTrackRow(id = "g0-t0", language = "en", label = "English"),
        AudioTrackRow(id = "g0-t1", language = "hin", label = "Hindi"),
    )

    @Test
    fun `preference matches across ISO-639 spellings`() {
        // The user typed the 2-letter form, the muxer wrote the 3-letter one.
        assertEquals("g0-t1", AudioTrackPolicy.pickPreferred(dualAudio, "hi"))
        assertEquals("g0-t1", AudioTrackPolicy.pickPreferred(dualAudio, "Hindi"))
    }

    @Test
    fun `a satisfied preference is not a re-selection`() {
        val already = listOf(
            AudioTrackRow(id = "g0-t0", language = "eng"),
            AudioTrackRow(id = "g0-t1", language = "hin", selected = true),
        )
        assertNull(AudioTrackPolicy.pickPreferred(already, "hi"))
    }

    @Test
    fun `an unmatched preference leaves the player alone`() {
        assertNull(AudioTrackPolicy.pickPreferred(dualAudio, "ta"))
        assertNull(AudioTrackPolicy.pickPreferred(emptyList(), "hi"))
        assertNull(AudioTrackPolicy.pickPreferred(dualAudio, null))
    }

    @Test
    fun `no preference means no forced override`() {
        assertNull(AudioTrackPolicy.pickPreferred(dualAudio, "  ", null))
    }

    @Test
    fun `cycle walks only supported tracks and wraps`() {
        val three = listOf(
            AudioTrackRow(id = "a", language = "eng"),
            AudioTrackRow(id = "b", language = "hin", supported = false),
            AudioTrackRow(id = "c", language = "jpn"),
        )
        assertEquals("c", AudioTrackPolicy.nextInCycle(three, "a"))
        assertEquals("a", AudioTrackPolicy.nextInCycle(three, "c"))
        // With one decodable track there is nothing to cycle to, and the row must say so.
        assertNull(AudioTrackPolicy.nextInCycle(listOf(AudioTrackRow(id = "a")), null))
        assertFalse(AudioTrackPolicy.canCycle(listOf(AudioTrackRow(id = "a"))))
        assertTrue(AudioTrackPolicy.canCycle(dualAudio))
    }

    @Test
    fun `language names are shown in the viewer words`() {
        assertEquals("Hindi", AudioTrackPolicy.nameFor("hi"))
        assertEquals("Hindi", AudioTrackPolicy.nameFor("HIN"))
        assertNull(AudioTrackPolicy.nameFor("und"))
    }

    // ── binge: the fire-once set the caller owns ───────────────────────────────

    private fun lateSeriesTick(handle: String?) =
        BingePreloadState(positionMs = 900_000L, durationMs = 1_000_000L, isSeries = true, nextEpisodeHandle = handle)

    @Test
    fun `a prefetch request is issued exactly once per handle`() {
        val planner = BingePrefetchPlanner()
        val first = planner.tick(900_000L, 1_000_000L, true, "next-handle")
        assertTrue(first is BingePreloadDecision.PrefetchNextHead)
        assertEquals("next-handle", (first as BingePreloadDecision.PrefetchNextHead).handle)
        // The same progress tick is re-delivered hundreds of times; none may re-ask.
        repeat(50) {
            val again = planner.tick(900_100L, 1_000_000L, true, "next-handle")
            assertEquals(BingePreloadDecision.Idle(BingeSkipReason.ALREADY_REQUESTED), again)
        }
        assertEquals(setOf("next-handle"), planner.alreadyRequested())
    }

    @Test
    fun `a new episode re-arms the planner`() {
        val planner = BingePrefetchPlanner()
        planner.tick(900_000L, 1_000_000L, true, "ep-2")
        planner.reset()
        assertTrue(planner.alreadyRequested().isEmpty())
        val second = planner.tick(900_000L, 1_000_000L, true, "ep-3")
        assertEquals("ep-3", (second as BingePreloadDecision.PrefetchNextHead).handle)
    }

    @Test
    fun `nothing is asked before the threshold or without a handle`() {
        val planner = BingePrefetchPlanner()
        assertEquals(
            BingePreloadDecision.Idle(BingeSkipReason.BEFORE_THRESHOLD),
            planner.tick(100_000L, 1_000_000L, true, "next-handle"),
        )
        // A packed file has no second handle: the policy must not be handed an empty one.
        assertEquals(
            BingePreloadDecision.Idle(BingeSkipReason.NO_NEXT_HANDLE),
            planner.tick(900_000L, 1_000_000L, true, null),
        )
        assertTrue(planner.alreadyRequested().isEmpty())
    }

    @Test
    fun `the requested head respects the brand byte budget`() {
        val decision = BingePrefetchPlanner().tick(900_000L, 1_000_000L, true, "h")
            as BingePreloadDecision.PrefetchNextHead
        assertTrue(decision.headBytes > 0L)
        assertTrue(decision.headBytes <= com.raddstream.app.brand.Brand.aheadFetchMaxBytesPerPass)
    }

    // ── auto quality: rungs the switcher does not know about ───────────────────

    private val fiveRungs = listOf(
        LadderRung("2160p", "h-4k"),
        LadderRung("1080p", "h-1080"),
        LadderRung("720p", "h-720"),
        LadderRung("480p", "h-480"),
        LadderRung("sd", "h-sd"),
    )

    @Test
    fun `auto is unarmed without a ladder to move along`() {
        val oneRung = AutoQualityDirector()
        oneRung.configure(listOf(LadderRung("1080p", "h-1080")), "1080p", auto = true)
        assertFalse(oneRung.isEnabled())
        assertFalse(oneRung.push(1_000_000L, 1_000L))
        // A single rung is still the rung being reported, so the label is never a lie.
        assertEquals("1080p", oneRung.targetBand())

        val manual = AutoQualityDirector()
        manual.configure(fiveRungs, "720p", auto = false)
        assertFalse(manual.isEnabled())
        assertEquals("720p", manual.targetBand())
        assertFalse(manual.push(1_000_000L, 1_000L))
    }

    @Test
    fun `configure drops rungs that have no handle of ours`() {
        val director = AutoQualityDirector()
        director.configure(
            listOf(LadderRung("1080p", ""), LadderRung("", "x"), LadderRung("720p", "h-720"), LadderRung("480p", "h-480")),
            "720p",
            auto = true,
        )
        assertEquals("720p", director.currentBand)
        assertTrue(director.isEnabled())
        assertNull(director.handleFor("1080p"))
        assertEquals("h-480", director.handleFor("480p"))
    }

    @Test
    fun `a sustained slow link steps the rung down after confirmation`() {
        val director = AutoQualityDirector()
        director.configure(fiveRungs, "1080p", auto = true)
        // 100 KB in 1 s = 800 kbps: cannot feed 1080p's 6 Mbps rung at all.
        director.push(100_000L, 1_000L)
        assertEquals("1080p", director.targetBand())
        assertTrue(director.estimateBps > 0L)
        // One bad interval changes nothing; the hysteresis needs confirmed samples.
        repeat(4) { director.push(100_000L, 1_000L) }
        assertEquals("1080p", director.targetBand())
        director.push(100_000L, 1_000L)
        assertEquals("sd", director.targetBand())
        assertEquals("h-sd", director.handleFor(director.currentBand))
    }

    @Test
    fun `a fast link climbs toward the best rung offered`() {
        val director = AutoQualityDirector()
        director.configure(fiveRungs, "720p", auto = true)
        director.push(1_000_000L, 1_000L) // 8 Mbps
        assertEquals("1080p", director.targetBand())
        director.push(4_000_000L, 1_000L) // 32 Mbps, smoothed upward
        assertNotNull(director.targetBand())
    }

    @Test
    fun `markPlaying corrects the rung without discarding the measurements`() {
        val director = AutoQualityDirector()
        director.configure(fiveRungs, "1080p", auto = true)
        director.push(500_000L, 1_000L)
        director.markPlaying("480p")
        assertEquals("480p", director.currentBand)
        // An unknown band must not strand the director on a rung the ladder does not offer.
        director.markPlaying("8k")
        assertEquals("480p", director.currentBand)
        assertTrue(director.estimateBps > 0L)
    }

    @Test
    fun `configure resets the throughput picture of the previous title`() {
        val director = AutoQualityDirector()
        director.configure(fiveRungs, "1080p", auto = true)
        director.push(100_000L, 1_000L)
        assertTrue(director.estimateBps > 0L)
        director.configure(fiveRungs, "2160p", auto = true)
        assertEquals(0L, director.estimateBps)
        assertEquals(0, director.sampleCount)
        assertEquals("2160p", director.currentBand)
    }

    // ── audio boost: the 0..1 contract and the honest caption ──────────────────

    @Test
    fun `boost multiplies the user volume and stops at the player ceiling`() {
        // Headroom below the ceiling is a real increase.
        assertEquals(0.9f, AudioBoostUi.effectivePlayerGain(1.5f, 0.6f), 1e-4f)
        // At the ceiling only the part up to 1.0 applies — never more.
        assertEquals(1f, AudioBoostUi.effectivePlayerGain(1.5f, 1f), 1e-4f)
        assertEquals(1f, AudioBoostUi.effectivePlayerGain(AudioBoost.MAX, 1f), 1e-4f)
        assertEquals(1f, AudioBoostUi.effectivePlayerGain(3f, 1f), 1e-4f)
        // Below unity the level is just attenuation, and 1.0 changes nothing.
        assertEquals(0.5f, AudioBoostUi.effectivePlayerGain(1f, 0.5f), 1e-4f)
        assertEquals(0.5f, AudioBoostUi.effectivePlayerGain(0.5f, 1f), 1e-4f)
    }

    @Test
    fun `poisoned numbers collapse to a legal value instead of reaching the player`() {
        assertEquals(1f, AudioBoostUi.effectivePlayerGain(Float.NaN, 1f), 1e-4f)
        assertEquals(1f, AudioBoostUi.effectivePlayerGain(1f, Float.NaN), 1e-4f)
        assertEquals(1f, AudioBoostUi.effectivePlayerGain(Float.POSITIVE_INFINITY, 1f), 1e-4f)
        assertEquals(1f, AudioBoostUi.effectivePlayerGain(1f, Float.POSITIVE_INFINITY), 1e-4f)
        assertEquals(0f, AudioBoostUi.effectivePlayerGain(2f, -3f), 1e-4f)
        val product = AudioBoostUi.effectivePlayerGain(Float.NaN, Float.NaN)
        assertTrue(product in 0f..1f)
    }

    @Test
    fun `the caption states the applied value when the request is capped`() {
        assertEquals("Volume 100%", AudioBoostUi.honestSummary(1f, 1f))
        assertEquals("Volume 60%", AudioBoostUi.honestSummary(0.6f, 1f))

        val headroom = AudioBoostUi.honestSummary(1.5f, 0.6f)
        assertTrue(headroom, headroom.contains("Requested 150%"))
        assertTrue(headroom, headroom.contains("applied 90%"))

        val capped = AudioBoostUi.honestSummary(1.5f, 1f)
        assertTrue(capped, capped.contains("Requested 150%"))
        assertTrue(capped, capped.contains("100%"))
        // The promise this build cannot keep is named as unavailable, not as done.
        assertTrue(capped, capped.contains("no software gain"))
        assertFalse(capped, capped.contains("Volume 150%"))
        assertEquals(90, AudioBoostUi.appliedPercent(1.5f, 0.6f))
        assertEquals(100, AudioBoostUi.appliedPercent(2f, 1f))
    }

    @Test
    fun `this build declares no software gain stage`() {
        // The caption's honesty rests on this flag; if a DynamicsProcessing/equalizer route
        // is ever added, this test is the place that has to change on purpose.
        assertFalse(AudioBoostUi.SOFTWARE_GAIN_AVAILABLE)
    }
}
