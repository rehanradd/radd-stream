package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The cadence rules, driven entirely by [FixedAdWallClock]. No test here sleeps, and none has to:
 * the whole point of passing `nowMs` into every decision is that "24 minutes later" is one integer
 * in a JVM test and four hours of waiting in a life.
 */
class AdCadenceTest {

    private val shipped = AdCadenceLimits.SHIPPED

    private fun state(
        enabled: Boolean = true,
        preRoll: Long = 0L,
        feedCard: Long = 0L,
        posters: Int = 0,
        appOpen: Long = 0L,
    ) = AdCadenceState(
        enabled = enabled,
        preRollShownAtMs = preRoll,
        feedCardShownAtMs = feedCard,
        postersSinceFeedCard = posters,
        appOpenShownAtMs = appOpen,
    )

    private fun dueAt(nowMs: Long, surface: AdSurface, state: AdCadenceState) =
        AdCadence.due(state, surface, shipped, nowMs)

    @Test
    fun `a fresh install is eligible on all three surfaces`() {
        val fresh = state()
        assertTrue(dueAt(TEN_MINUTES, AdSurface.PRE_ROLL, fresh))
        assertTrue(dueAt(TEN_MINUTES, AdSurface.APP_OPEN, fresh))
        assertTrue(dueAt(TEN_MINUTES, AdSurface.FEED_CARD, state(posters = shipped.feedCardEveryPosters)))
    }

    @Test
    fun `a pre-roll shown 24 minutes ago is refused and one shown 25 minutes ago is not`() {
        val shown = state(preRoll = ZERO)
        assertFalse("24 minutes is inside the window", dueAt(ZERO + 24 * MINUTE_MS, AdSurface.PRE_ROLL, shown))
        assertFalse("one second short is still short", dueAt(ZERO + 25 * MINUTE_MS - 1, AdSurface.PRE_ROLL, shown))
        assertTrue(dueAt(ZERO + 25 * MINUTE_MS, AdSurface.PRE_ROLL, shown))
        assertTrue(dueAt(ZERO + 26 * MINUTE_MS, AdSurface.PRE_ROLL, shown))
    }

    @Test
    fun `an app-open ad is refused for three hours and fifty-nine minutes`() {
        // Both arguments are absolute wall-clock instants, measured from the stamp itself. Written
        // as bare durations (HOUR_MS * 4) they sit centuries before ZERO, so intervalElapsed's
        // clock-behind-its-stamp rule refused them and the 3h59m assertFalse passed for a reason
        // that had nothing to do with the four-hour window.
        val shown = state(appOpen = ZERO)
        assertFalse("3h59m59.999s is inside the window", dueAt(ZERO + HOUR_MS * 4 - 1, AdSurface.APP_OPEN, shown))
        assertFalse("24 minutes in is nowhere near it", dueAt(ZERO + 24 * MINUTE_MS, AdSurface.APP_OPEN, shown))
        assertTrue(dueAt(ZERO + HOUR_MS * 4, AdSurface.APP_OPEN, shown))
        assertTrue(dueAt(ZERO + HOUR_MS * 4 + 1, AdSurface.APP_OPEN, shown))
    }

    @Test
    fun `the feed card counts posters and never reads the clock`() {
        // Eleven posters is not a card, at any time; twelve is, at any time.
        assertFalse(dueAt(0L, AdSurface.FEED_CARD, state(posters = 11)))
        assertFalse(dueAt(TEN_MINUTES, AdSurface.FEED_CARD, state(posters = 11)))
        assertTrue(dueAt(0L, AdSurface.FEED_CARD, state(posters = 12)))
        assertTrue(dueAt(TEN_MINUTES, AdSurface.FEED_CARD, state(posters = 12)))
    }

    @Test
    fun `the operator switch off refuses every surface even a never-shown one`() {
        val disabled = state(enabled = false)
        AdSurface.entries.forEach { surface ->
            assertFalse("$surface", dueAt(TEN_MINUTES, surface, disabled))
        }
        // A viewer who scrolled 500 posters while ads were off still gets nothing.
        assertFalse(dueAt(TEN_MINUTES, AdSurface.FEED_CARD, state(enabled = false, posters = 500)))
    }

    @Test
    fun `showing a surface stamps it and clears only its own budget`() {
        val before = state(posters = 12, preRoll = ZERO)
        val afterPreroll = AdCadence.shown(before, AdSurface.PRE_ROLL, TEN_MINUTES)
        assertEquals(TEN_MINUTES, afterPreroll.preRollShownAtMs)
        assertEquals("the feed counter belongs to the card", 12, afterPreroll.postersSinceFeedCard)
        assertEquals("the app-open window is untouched", 0L, afterPreroll.appOpenShownAtMs)

        val afterCard = AdCadence.shown(before, AdSurface.FEED_CARD, TEN_MINUTES)
        assertEquals(TEN_MINUTES, afterCard.feedCardShownAtMs)
        assertEquals("a card is the answer to the twelve posters", 0, afterCard.postersSinceFeedCard)
        assertEquals("and it does not spend the pre-roll", ZERO, afterCard.preRollShownAtMs)

        val afterOpen = AdCadence.shown(before, AdSurface.APP_OPEN, TEN_MINUTES)
        assertEquals(TEN_MINUTES, afterOpen.appOpenShownAtMs)
        assertEquals(ZERO, afterOpen.preRollShownAtMs)
    }

    @Test
    fun `a stamp in the future is refused rather than granted twice`() {
        // A viewer who sets their clock back keeps the window they already spent; a clock rolled
        // forward past a stamp that has not arrived yet must not read as "elapsed".
        val stamped = state(preRoll = TEN_MINUTES)
        assertFalse(dueAt(ZERO, AdSurface.PRE_ROLL, stamped))
        assertFalse(dueAt(TEN_MINUTES - 1, AdSurface.PRE_ROLL, stamped))
        assertTrue(dueAt(TEN_MINUTES + 25 * MINUTE_MS, AdSurface.PRE_ROLL, stamped))
    }

    @Test
    fun `a non-positive interval refuses instead of meaning unlimited`() {
        // Nothing on the wire can produce this (AdCadenceLimits falls back to the cap), so the
        // only way to reach it is a limits value assembled by a caller that was not read. It is
        // still the wrong answer for a zero to mean "every frame", so it means "never".
        val broken = AdCadenceLimits(
            preRollIntervalMs = 0L,
            feedCardEveryPosters = 0,
            appOpenIntervalMs = -1L,
            skippableAfterMs = 5_000L,
        )
        val stamped = state(preRoll = ZERO, appOpen = ZERO)
        assertFalse(AdCadence.due(stamped, AdSurface.PRE_ROLL, broken, TEN_MINUTES))
        assertFalse(AdCadence.due(stamped, AdSurface.APP_OPEN, broken, TEN_MINUTES))
        // A zero poster-count would be an ad on every scroll, which is the same mistake.
        assertFalse(AdCadence.due(state(posters = 0), AdSurface.FEED_CARD, broken, TEN_MINUTES))
    }

    @Test
    fun `scrolling advances the counter and never a negative report`() {
        val start = state(posters = 5)
        assertEquals(5, AdCadence.scrolled(start, 0, shipped).postersSinceFeedCard)
        assertEquals(5, AdCadence.scrolled(start, -3, shipped).postersSinceFeedCard)
        assertEquals(11, AdCadence.scrolled(start, 6, shipped).postersSinceFeedCard)
        assertEquals(12, AdCadence.scrolled(start, 7, shipped).postersSinceFeedCard)
    }

    @Test
    fun `the counter saturates at the cap so it cannot overflow into eligibility loss`() {
        val huge = AdCadence.scrolled(state(posters = Int.MAX_VALUE - 1), 1_000, shipped)
        assertEquals(shipped.feedCardEveryPosters, huge.postersSinceFeedCard)
        assertTrue(huge.postersSinceFeedCard > 0)
    }

    @Test
    fun `the skip deadline is never more than five seconds whatever the limits asked for`() {
        assertEquals(5_000L, AdCadence.skippableAtMs(shipped))
        assertEquals(3_000L, AdCadence.skippableAtMs(shipped.copy(skippableAfterMs = 3_000L)))
        assertEquals(
            AdCadenceLimits.MAX_SKIP_MS,
            AdCadence.skippableAtMs(shipped.copy(skippableAfterMs = 30_000L)),
        )
        assertEquals(
            AdCadenceLimits.MAX_SKIP_MS,
            AdCadence.skippableAtMs(shipped.copy(skippableAfterMs = Long.MAX_VALUE)),
        )
    }

    @Test
    fun `clearing the cadence is the fresh state and is idempotent`() {
        val stamped = state(preRoll = TEN_MINUTES, feedCard = TEN_MINUTES, posters = 9, appOpen = TEN_MINUTES)
        val cleared = AdCadence.shown(stamped, AdSurface.PRE_ROLL, TEN_MINUTES).let { AdCadence.cleared() }
        assertEquals(AdCadenceState(), cleared)
        assertEquals(AdCadence.cleared(), AdCadence.cleared())
        AdSurface.entries.forEach { surface ->
            assertFalse("cleared is switched off", AdCadence.due(cleared, surface, shipped, TEN_MINUTES))
        }
    }

    @Test
    fun `the shipped caps are the owners three numbers and nothing else`() {
        assertEquals(25L * 60_000L, shipped.preRollIntervalMs)
        assertEquals(12, shipped.feedCardEveryPosters)
        assertEquals(4L * 3_600_000L, shipped.appOpenIntervalMs)
        assertEquals(5_000L, shipped.skippableAfterMs)
        assertEquals(25L, AdCadenceLimits.PRE_ROLL_MINUTES)
        assertEquals(12, AdCadenceLimits.FEED_CARD_POSTERS)
        assertEquals(4L, AdCadenceLimits.APP_OPEN_HOURS)
        assertEquals(5L, AdCadenceLimits.SKIP_SECONDS)
    }

    @Test
    fun `the injected clock turns time without sleeping`() {
        val clock = FixedAdWallClock(startMillis = ZERO)
        val shown = state(preRoll = clock.nowMs(), appOpen = clock.nowMs())
        clock.advance(24 * MINUTE_MS)
        assertFalse(AdCadence.due(shown, AdSurface.PRE_ROLL, shipped, clock.nowMs()))
        clock.advanceTo(ZERO + 25 * MINUTE_MS)
        assertTrue(AdCadence.due(shown, AdSurface.PRE_ROLL, shipped, clock.nowMs()))
        assertFalse("four hours have not gone by", AdCadence.due(shown, AdSurface.APP_OPEN, shipped, clock.nowMs()))
        clock.advance(HOUR_MS * 4 - 25 * MINUTE_MS)
        assertTrue(AdCadence.due(shown, AdSurface.APP_OPEN, shipped, clock.nowMs()))
    }

    companion object {
        private const val MINUTE_MS = 60_000L
        private const val HOUR_MS = 3_600_000L
        private const val ZERO = 1_730_000_000_000L
        private const val TEN_MINUTES = 1_730_000_600_000L
    }
}
