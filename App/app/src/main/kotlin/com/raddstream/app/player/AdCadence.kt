package com.raddstream.app.player

import com.raddstream.app.network.models.VipRemoteAds
import com.raddstream.app.network.models.VipRemoteEngagement

/**
 * The three surfaces the owner's monetization plan names, and the only three this app will fill.
 *
 * Each has one cap, and the cap is a *count of viewer experience*, not a revenue target: one
 * pre-roll per 25 minutes of wall clock, one native card per 12 posters the viewer scrolled past,
 * one app-open ad per 4 hours. Nothing here decides *what* is shown — there is no creative in this
 * build — only whether a surface is even allowed to ask.
 */
enum class AdSurface {
    PRE_ROLL,
    FEED_CARD,
    APP_OPEN,
}

/**
 * Wall-clock source, injectable so a test can move four hours without sleeping.
 *
 * Wall clock and not [com.raddstream.app.data.cache.UptimeClock] on purpose: the timestamps this
 * feeds live in Room across process death, and an `elapsedRealtime()` value from a previous boot
 * is meaningless after a reboot — it restarts at zero, which would make every viewer eligible
 * again the moment their device restarted. A device clock can be wrong; the rules below are
 * written so a wrong clock can only ever *refuse* an ad, never grant an extra one.
 */
fun interface AdWallClock {
    fun nowMs(): Long
}

/** The production clock. */
class SystemAdWallClock : AdWallClock {
    override fun nowMs(): Long = System.currentTimeMillis()
}

/** Drives the cadence from a test; the app wires [SystemAdWallClock]. */
class FixedAdWallClock(startMillis: Long = 0L) : AdWallClock {
    private var now = startMillis
    override fun nowMs(): Long = now
    fun advanceTo(millis: Long) { now = millis }
    fun advance(deltaMillis: Long) { now += deltaMillis }
}

/**
 * The caps, already resolved.
 *
 * [from] is the only place the shipped numbers appear, which is what makes "an older deployment
 * must not fall back to unlimited ads" a property of the type rather than of every caller: a
 * missing or nonsense value becomes the cap, and there is no value the server can send that means
 * "no limit". `0` minutes is not "an ad every minute" — it is "the operator never said", and the
 * same is true of a negative.
 */
data class AdCadenceLimits(
    val preRollIntervalMs: Long,
    val feedCardEveryPosters: Int,
    val appOpenIntervalMs: Long,
    /** Never larger than [MAX_SKIP_MS], whatever the body asked for. */
    val skippableAfterMs: Long,
) {
    companion object {
        const val PRE_ROLL_MINUTES = 25L
        const val FEED_CARD_POSTERS = 12
        const val APP_OPEN_HOURS = 4L
        const val SKIP_SECONDS = 5L

        /**
         * The owner's words: no ad that cannot be skipped after the first 5 seconds. This is a
         * ceiling, not a default — a server that publishes 30 s is answered with 5 s, because the
         * alternative lets a body edit undo a rule the owner called non-negotiable.
         */
        const val MAX_SKIP_MS = 5_000L

        /** What this build enforces before any remote config has been read. */
        val SHIPPED = AdCadenceLimits(
            preRollIntervalMs = PRE_ROLL_MINUTES * 60_000L,
            feedCardEveryPosters = FEED_CARD_POSTERS,
            appOpenIntervalMs = APP_OPEN_HOURS * 3_600_000L,
            skippableAfterMs = SKIP_SECONDS * 1_000L,
        )

        /**
         * The caps as this deployment means them, with the server's own cadence block first.
         *
         * [engagement] outranks [ads] because it is the body the enforcing side computes from:
         * `Fast_Fetch/engagement.py:ad_grant()` compares its own `CAPS_DEFAULT` against its own
         * stamps, so a phone obeying a different pair of numbers would either show an ad the server
         * had already refused or withhold one it had granted. Both blocks are read tolerantly, so a
         * deployment that publishes only the older `ads` keys still gets the caps it named, and one
         * that names none gets [SHIPPED] rather than no limit.
         */
        fun from(ads: VipRemoteAds, engagement: VipRemoteEngagement = VipRemoteEngagement()): AdCadenceLimits {
            val server = engagement.cadence
            // The `ads` block states app-open in HOURS and the engagement block states it in
            // MINUTES, so the conversion happens here and nowhere else, and the two are never
            // alternates of one key: the server's `240` read as hours would be a ten-day window.
            val appOpenMinutesFromAds =
                if (ads.appOpenIntervalHours > 0) ads.appOpenIntervalHours.toLong() * 60L else 0L
            return AdCadenceLimits(
                preRollIntervalMs =
                    gapMinutes(server.prerollGapMinutes.toLong(), ads.prerollIntervalMinutes.toLong(), PRE_ROLL_MINUTES) * 60_000L,
                feedCardEveryPosters = positiveOr(
                    if (server.feedCardEveryPosters > 0) server.feedCardEveryPosters else ads.feedCardEveryPosters,
                    FEED_CARD_POSTERS,
                ),
                appOpenIntervalMs =
                    gapMinutes(server.appOpenGapMinutes.toLong(), appOpenMinutesFromAds, APP_OPEN_HOURS * 60L) * 60_000L,
                // The ceiling is applied at the answer as well, so no path can hand back a
                // non-skippable ad even if this construction is ever bypassed.
                skippableAfterMs = (secondsOr(ads.skippableAfterSeconds) * 1_000L).coerceAtMost(MAX_SKIP_MS),
            )
        }

        /** The first block that actually named a gap, in minutes; neither speaking, the shipped one. */
        private fun gapMinutes(serverMinutes: Long, adsMinutes: Long, shippedMinutes: Long): Long = when {
            serverMinutes > 0L -> serverMinutes
            adsMinutes > 0L -> adsMinutes
            else -> shippedMinutes
        }

        private fun secondsOr(raw: Int): Long = if (raw <= 0) SKIP_SECONDS else raw.toLong()

        private fun positiveOr(raw: Int, fallback: Int): Int = if (raw <= 0) fallback else raw
    }
}

/**
 * The cadence facts, exactly as they are persisted.
 *
 * `0` for a `…ShownAtMs` means "never shown", which is what makes a fresh install eligible at once
 * without a special case: the elapsed test below compares against the epoch, and any real clock is
 * past it.
 */
data class AdCadenceState(
    /** The operator's switch. Off is the default, and off answers every surface with nothing. */
    val enabled: Boolean = false,
    val preRollShownAtMs: Long = 0L,
    val feedCardShownAtMs: Long = 0L,
    val postersSinceFeedCard: Int = 0,
    val appOpenShownAtMs: Long = 0L,
)

/**
 * Pure cadence. Every function takes `nowMs` so the whole rule set runs on the JVM with a clock
 * the test turns, and no test sleeps.
 *
 * Two properties the owner's directive forces, and they are structural rather than a matter of
 * callers behaving:
 *  - **Refusal is the only failure mode.** Every branch that cannot prove a surface is due returns
 *    false. A rolled-back device clock, a torn row, an interval of zero — all of them refuse, and
 *    nothing here can produce a second ad by being confused.
 *  - **A surface that is not due shows nothing.** [due] returns false; there is no third state in
 *    which an ad "loads", so a spinner has no representation to render.
 */
object AdCadence {

    /**
     * Whether the *interval* part of the rule is satisfied. The feed card is the odd one: its cap
     * is a count of posters, not a span of time, so it never reads a clock and cannot be granted
     * early or late by a wrong one.
     */
    fun due(state: AdCadenceState, surface: AdSurface, limits: AdCadenceLimits, nowMs: Long): Boolean {
        if (!state.enabled) return false
        return when (surface) {
            AdSurface.PRE_ROLL -> intervalElapsed(state.preRollShownAtMs, limits.preRollIntervalMs, nowMs)
            AdSurface.APP_OPEN -> intervalElapsed(state.appOpenShownAtMs, limits.appOpenIntervalMs, nowMs)
            // A cap of zero would otherwise read as "due immediately, forever", which is the one
            // answer this file is not allowed to give. [AdCadenceLimits.from] cannot produce it;
            // this refuses it anyway, for a limits value assembled by anyone else.
            AdSurface.FEED_CARD ->
                limits.feedCardEveryPosters > 0 && state.postersSinceFeedCard >= limits.feedCardEveryPosters
        }
    }

    /** A never-shown surface is due; a clock behind its own stamp is not, and never will be. */
    private fun intervalElapsed(shownAtMs: Long, intervalMs: Long, nowMs: Long): Boolean {
        if (shownAtMs <= 0L) return true
        if (intervalMs <= 0L) return false
        return nowMs - shownAtMs >= intervalMs
    }

    /**
     * The post at which a creative may answer to a skip control. Capped twice — once by
     * [AdCadenceLimits.from] when the body is read, once here at the answer — so no path through
     * this file can hand a caller a number above five seconds.
     */
    fun skippableAtMs(limits: AdCadenceLimits): Long = limits.skippableAfterMs.coerceAtMost(AdCadenceLimits.MAX_SKIP_MS)

    /** The state after [surface] was actually shown at [nowMs]. */
    fun shown(
        state: AdCadenceState,
        surface: AdSurface,
        nowMs: Long,
    ): AdCadenceState = when (surface) {
        AdSurface.PRE_ROLL -> state.copy(preRollShownAtMs = nowMs)
        AdSurface.APP_OPEN -> state.copy(appOpenShownAtMs = nowMs)
        // Showing a card is also the answer to "12 more posters", so the count restarts here.
        AdSurface.FEED_CARD -> state.copy(
            feedCardShownAtMs = nowMs,
            postersSinceFeedCard = 0,
        )
    }

    /**
     * Record that the viewer passed [count] more posters. The counter saturates at the cap rather
     * than growing: nothing needs to know that 4,000 posters went by, and an unbounded int is one
     * overflow away from reading as "no posters yet".
     */
    fun scrolled(state: AdCadenceState, count: Int, limits: AdCadenceLimits): AdCadenceState {
        if (count <= 0) return state
        val next = state.postersSinceFeedCard + count
        return state.copy(
            postersSinceFeedCard = if (next < 0) limits.feedCardEveryPosters else next.coerceAtMost(limits.feedCardEveryPosters),
        )
    }

    /**
     * The operator turned the surfaces off. Every stamp and counter goes with the switch, which is
     * what the directive asks for: a viewer who was throttled by an ad they will never see again
     * should not stay throttled, and a deployment that re-enables later starts clean rather than
     * inheriting a window computed under a policy nobody is enforcing any more.
     */
    fun cleared(): AdCadenceState = AdCadenceState()
}

/**
 * What a surface is allowed to do, once.
 *
 * [None] is not a state that waits, retries, or spins: it is the absence of an ad, and it is the
 * only value this build can produce, because no ad SDK exists to fill anything. [Serve] carries the
 * skip deadline with the slot precisely so that a creative cannot arrive without one.
 */
sealed interface AdDecision {
    data object None : AdDecision

    data class Serve(
        val surface: AdSurface,
        /** When the viewer may dismiss it. Always <= 5 s after the first frame. */
        val skippableAtMs: Long,
    ) : AdDecision
}

/**
 * Whether the network can actually fill [surface].
 *
 * This build ships no SDK, so the single production binding answers false everywhere and every ask
 * ends as [AdDecision.None]. That is the deliberate form of "if an ad cannot be filled, show
 * nothing": the alternative — a placeholder, a shimmer, a spinner held while a zone is queried —
 * is the gate the owner ruled out, and it would be indistinguishable from one to a viewer on a
 * dead network. Wiring a real network replaces this binding and inherits every cadence rule above
 * rather than re-deciding them.
 */
interface AdInventory {
    fun canFill(surface: AdSurface): Boolean
}

/** The production binding until an SDK exists. */
class NoAdInventory : AdInventory {
    override fun canFill(surface: AdSurface): Boolean = false
}
