package com.raddstream.app.player

import com.raddstream.app.network.models.VipRemoteAds
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The boundary between a remote-config body and the caps this app enforces.
 *
 * The whole risk in the cadence feature is the empty body: a deployment that has never published
 * a monetization field must not end up with an ad on every scroll, and `q5-monet-fields-20261029`
 * has not merged, so today every real server answer is exactly that body. These tests pin the
 * absence, the nonsense, and the explicit case, in that order of importance.
 */
class AdCadenceLimitsTest {

    @Test
    fun `a body that says nothing about cadence gets the shipped caps`() {
        val limits = AdCadenceLimits.from(VipRemoteAds())
        assertEquals(AdCadenceLimits.SHIPPED, limits)
    }

    @Test
    fun `a zero from the server means absent and not every minute`() {
        val limits = AdCadenceLimits.from(
            VipRemoteAds(
                prerollIntervalMinutes = 0,
                feedCardEveryPosters = 0,
                appOpenIntervalHours = 0,
                skippableAfterSeconds = 0,
            ),
        )
        assertEquals(AdCadenceLimits.SHIPPED, limits)
    }

    @Test
    fun `a negative interval cannot buy an ad per frame either`() {
        val limits = AdCadenceLimits.from(
            VipRemoteAds(
                prerollIntervalMinutes = -25,
                feedCardEveryPosters = -12,
                appOpenIntervalHours = -4,
                skippableAfterSeconds = -5,
            ),
        )
        assertEquals(AdCadenceLimits.SHIPPED, limits)
    }

    @Test
    fun `an explicit cadence is honoured exactly`() {
        val limits = AdCadenceLimits.from(
            VipRemoteAds(
                prerollIntervalMinutes = 40,
                feedCardEveryPosters = 20,
                appOpenIntervalHours = 8,
                skippableAfterSeconds = 3,
            ),
        )
        assertEquals(40L * 60_000L, limits.preRollIntervalMs)
        assertEquals(20, limits.feedCardEveryPosters)
        assertEquals(8L * 3_600_000L, limits.appOpenIntervalMs)
        assertEquals(3_000L, limits.skippableAfterMs)
    }

    /**
     * The owner called the five-second skip rule non-negotiable, so a server edit is not allowed
     * to be the thing that turns an ad into a gate. This is the one field the client overrides.
     */
    @Test
    fun `a server asking for thirty seconds is answered with five`() {
        val limits = AdCadenceLimits.from(VipRemoteAds(skippableAfterSeconds = 30))
        assertEquals(AdCadenceLimits.MAX_SKIP_MS, limits.skippableAfterMs)
        assertEquals(
            AdCadenceLimits.MAX_SKIP_MS,
            AdCadenceLimits.from(VipRemoteAds(skippableAfterSeconds = Int.MAX_VALUE)).skippableAfterMs,
        )
    }

    @Test
    fun `only one field of a partial cadence still falls back on its own`() {
        val limits = AdCadenceLimits.from(VipRemoteAds(feedCardEveryPosters = 30))
        assertEquals(30, limits.feedCardEveryPosters)
        assertEquals("the other three were never published", AdCadenceLimits.SHIPPED.preRollIntervalMs, limits.preRollIntervalMs)
        assertEquals(AdCadenceLimits.SHIPPED.appOpenIntervalMs, limits.appOpenIntervalMs)
        assertEquals(AdCadenceLimits.SHIPPED.skippableAfterMs, limits.skippableAfterMs)
    }
}
