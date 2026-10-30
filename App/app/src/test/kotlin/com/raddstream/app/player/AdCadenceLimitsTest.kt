package com.raddstream.app.player

import com.raddstream.app.network.models.VipRemoteAds
import com.raddstream.app.network.models.VipRemoteAdCadence
import com.raddstream.app.network.models.VipRemoteEngagement
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

    // ── the engagement block, which is the shape the enforcement side actually publishes ──

    /**
     * Absence here is the whole test: no route serves `engagement` yet, so every real body this
     * client can receive carries nothing, and the shipped caps must still be what is enforced.
     */
    @Test
    fun `an absent engagement block changes nothing`() {
        assertEquals(
            AdCadenceLimits.from(VipRemoteAds()),
            AdCadenceLimits.from(VipRemoteAds(), VipRemoteEngagement()),
        )
        assertEquals(
            AdCadenceLimits.SHIPPED,
            AdCadenceLimits.from(VipRemoteAds(), VipRemoteEngagement(VipRemoteAdCadence(0, 0, 0))),
        )
    }

    /**
     * The two bodies state the same rule in different units — `ads` speaks app-open in HOURS,
     * `engagement` in MINUTES — so the conversion is pinned at both the value and the precedence.
     * Six hours stated as `360` minutes must never be read as 360 hours.
     */
    @Test
    fun `the engagement block outranks the ads block and speaks minutes`() {
        val limits = AdCadenceLimits.from(
            VipRemoteAds(prerollIntervalMinutes = 5, feedCardEveryPosters = 3, appOpenIntervalHours = 1),
            VipRemoteEngagement(VipRemoteAdCadence(prerollGapMinutes = 45, feedCardEveryPosters = 18, appOpenGapMinutes = 360)),
        )
        assertEquals(45L * 60_000L, limits.preRollIntervalMs)
        assertEquals(18, limits.feedCardEveryPosters)
        assertEquals(360L * 60_000L, limits.appOpenIntervalMs)
        assertEquals("a skip ceiling is not a cadence field, so ads still owns it", 5_000L, limits.skippableAfterMs)
    }

    @Test
    fun `an ads-only app-open interval is converted from hours to the same minutes scale`() {
        val fromAds = AdCadenceLimits.from(VipRemoteAds(appOpenIntervalHours = 6))
        val fromServer = AdCadenceLimits.from(
            VipRemoteAds(appOpenIntervalHours = 1),
            VipRemoteEngagement(VipRemoteAdCadence(appOpenGapMinutes = 360)),
        )
        assertEquals(6L * 3_600_000L, fromAds.appOpenIntervalMs)
        assertEquals(fromAds.appOpenIntervalMs, fromServer.appOpenIntervalMs)
    }
}
