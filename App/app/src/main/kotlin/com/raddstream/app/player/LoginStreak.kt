package com.raddstream.app.player

import java.util.TimeZone

/**
 * The login streak (plan §5 step 19): consecutive days this device opened the app.
 *
 * The server publishes only the PLAN — [com.raddstream.app.network.models.VipRemoteStreak]
 * (enabled, days, reward coins) — and no route carries a per-user progress count, nor is there a
 * claim/grant route for the coins. So the progress is counted here, on the device, and the reward
 * is never granted here: the card shows the operator's promise, and only the operator's wallet can
 * pay it. A streak the server never verified must not be presented as one it did.
 *
 * A "day" is the device's own calendar day, not a UTC day: a viewer opening the app at 23:00 and
 * again at 01:00 the next night has opened it on two days, and a UTC boundary at 05:00 PKT would
 * call that one. The day math takes the timezone offset as a parameter so the JVM test can pin it
 * with fixed offsets instead of depending on the machine it runs on.
 */
const val MILLIS_PER_DAY = 86_400_000L

/** The last day this device opened the app (a local epoch day), and how many in a row that is. */
data class LoginStreak(
    val lastDay: Long? = null,
    val count: Int = 0,
)

/** The local calendar day [nowMs] falls on, given the timezone offset in force at that moment. */
fun localEpochDay(nowMs: Long, offsetMs: Long): Long =
    Math.floorDiv(nowMs + offsetMs, MILLIS_PER_DAY)

/** The local calendar day right now, on this device. */
fun loginStreakDay(nowMs: Long): Long =
    localEpochDay(nowMs, TimeZone.getDefault().getOffset(nowMs))

/**
 * The streak after an open on [todayDay].
 *
 * Same day again: unchanged — one open a day is the whole streak, a second open is not a second
 * day. The next day: one more. A missed day restarts at one. A clock moved backwards never
 * shortens a streak the viewer already earned; it simply does not count.
 */
fun nextLoginStreak(streak: LoginStreak, todayDay: Long): LoginStreak {
    val last = streak.lastDay ?: return LoginStreak(lastDay = todayDay, count = 1)
    return when {
        todayDay == last -> streak
        todayDay == last + 1 -> streak.copy(lastDay = todayDay, count = streak.count + 1)
        todayDay < last -> streak
        else -> LoginStreak(lastDay = todayDay, count = 1)
    }
}
