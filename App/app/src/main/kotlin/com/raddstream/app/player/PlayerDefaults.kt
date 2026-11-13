package com.raddstream.app.player

/**
 * Player defaults (plan §5 step 10, P36): the two decisions the player must make
 * from the viewer's Settings switches, as pure functions so a JVM test can prove
 * them without a player, a service, or a DataStore.
 */

/**
 * Whether the END that just happened advances on its own. Only a
 * [NextEpisodeAction.NextBundleRequest] ever auto-advances, and only while the
 * autoplay-next switch is on: an in-file seek is the service's own work, a
 * calibration prompt is a question, and anything else is the file ending. With the
 * switch off, the episode ends on the Next Episode button instead — no countdown
 * ambush, no "Are you still watching?".
 */
fun shouldAutoAdvance(autoplayNext: Boolean, action: NextEpisodeAction): Boolean =
    autoplayNext && action is NextEpisodeAction.NextBundleRequest

/** Seconds of warning before an auto-advance fires: long enough to read and cancel, short enough not to stall a binge. */
const val AUTOPLAY_COUNTDOWN_SECONDS = 10

/**
 * Session 153 — the HTTP timeouts on the player's own data source.
 *
 * The redirector's live resolve takes 6–12 s measured (Salaar's 720p
 * handle: 6.1–12.0 s per press, and the press is not cached — a repeat
 * press of the same handle costs the same again), so the old 10 s read
 * timeout fired while the 302 was still being minted, before Media3 ever
 * touched the file. Five 302s in the device log and no frame is that
 * timeout, not a dead link. The read timeout is now above the measured
 * resolve ceiling; the 20 s start watchdog still bounds each handle and
 * fails it over, and the 30 s give-up still bounds the attempt — these
 * timeouts are the backstop that turns a hung socket into a player error,
 * not the wait itself. Connect stays short: a host that will not connect
 * at all is not worth the start budget.
 */
const val MEDIA_CONNECT_TIMEOUT_MS: Int = 15_000
const val MEDIA_READ_TIMEOUT_MS: Int = 25_000

/**
 * One autoplay-next countdown, as pure state: the seconds left, and the tick
 * that moves it. [tick] returns null at zero — the moment the advance fires —
 * so the caller never has to compare against a magic number, and a JVM test
 * can run the whole countdown without a clock. A cancelled countdown is
 * simply dropped, never ticked.
 */
data class AutoplayCountdown(val secondsLeft: Int) {
    fun tick(): AutoplayCountdown? =
        if (secondsLeft > 1) copy(secondsLeft = secondsLeft - 1) else null

    companion object {
        fun start(): AutoplayCountdown = AutoplayCountdown(AUTOPLAY_COUNTDOWN_SECONDS)
    }
}

/**
 * The rung playback starts on, and whether Auto may still move it.
 *
 * Precedence, in order: (1) a rung the viewer tapped on the detail screen — a
 * decision outranks everything; (2) the standing default band from Settings, but
 * only when this staging is Auto (the viewer tapped Play, not a rung) and the band
 * is actually on this ladder; (3) the staged band Auto resolved; (4) the first
 * rung, when nothing else named one. A default band that is not on this ladder is
 * ignored rather than guessed at, and "auto" (or blank) means no default at all.
 * Applying the default turns Auto off for this title: a fixed band is a decision,
 * and the director never moves a decision.
 */
fun resolveStartBand(
    stagedStartBand: String?,
    stagedAuto: Boolean,
    defaultBand: String,
    rungBands: List<String>,
): Pair<String, Boolean> {
    val default = defaultBand.trim().takeIf {
        it.isNotBlank() && !it.equals(LadderForScope.AUTO, ignoreCase = true)
    }?.takeIf { it in rungBands }
    return when {
        stagedAuto && default != null -> default to false
        stagedStartBand != null && stagedStartBand in rungBands -> stagedStartBand to stagedAuto
        default != null -> default to false
        rungBands.isNotEmpty() -> rungBands.first() to stagedAuto
        else -> (stagedStartBand ?: defaultBand) to stagedAuto
    }
}
