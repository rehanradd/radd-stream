package com.raddstream.app.player

import com.raddstream.app.player.PlayerChromePlan.Control
import com.raddstream.app.player.PlayerChromePlan.Plan

/**
 * WHERE on the simple surface each control the [PlayerChromePlan] put on the bar actually sits.
 *
 * [PlayerChromePlan] answers "on the bar, or behind More" and hands back one flat list. A bar is
 * not a list: the owner's spec names three places on it — back and title and quality at the TOP,
 * play/pause in the CENTRE, and the seek bar with the time, the two ten-second jumps, fullscreen,
 * the two conditional track buttons and the one More button along the BOTTOM. The screen therefore
 * needs a second decision the plan does not carry, and a second decision is exactly what must not
 * live as three `if`s copied between three composables — that is how one branch gets updated and a
 * button ends up in the wrong zone.
 *
 * So the placement is here, as a total function over [Control]: every control the table knows has
 * exactly one zone, the advanced set maps to [ChromeZone.MENU] (which is why moving a control
 * behind More changes only its zone, never its existence), and [PlayerChromeZonesTest] walks the
 * real plans from the real table to prove nothing is dropped and nothing is painted twice.
 */
enum class ChromeZone {
    /** Top row: leave, what is playing, and the picture. */
    TOP,

    /** Centre: the one big transport button. */
    CENTRE,

    /** Bottom row: position, the two skips, fullscreen, the conditional track buttons, More. */
    BOTTOM,

    /** Behind the single More button — moved here, never deleted. */
    MENU,
}

object PlayerChromeZones {

    /**
     * The zone one control paints in. Exhaustive on purpose — there is no `else`: the compiler
     * then refuses a build where the table has grown a control this file has not placed, which
     * is the only guarantee that a new control cannot silently never be painted.
     */
    fun zoneOf(control: Control): ChromeZone = when (control) {
        Control.BACK,
        Control.TITLE,
        Control.QUALITY,
        -> ChromeZone.TOP

        Control.PLAY_PAUSE -> ChromeZone.CENTRE

        Control.SEEK,
        Control.ELAPSED,
        Control.SKIP_BACK,
        Control.SKIP_FORWARD,
        Control.FULLSCREEN,
        Control.SUBTITLES,
        Control.AUDIO_TRACKS,
        Control.MORE,
        -> ChromeZone.BOTTOM

        Control.NEXT_EPISODE,
        Control.SPEED,
        Control.SUBTITLE_DELAY,
        Control.LOCK,
        Control.FRAME_BACK,
        Control.FRAME_FORWARD,
        Control.SLEEP_TIMER,
        Control.ASPECT,
        Control.ORIENTATION,
        Control.AUDIO_ONLY,
        Control.STEREO_ONLY,
        Control.CINEMA_MODE,
        Control.PICTURE_IN_PICTURE,
        Control.SOURCE_LOG,
        Control.OPEN_EXTERNALLY,
        -> ChromeZone.MENU
    }

    /** The bar's controls for one zone, in the order the plan listed them. */
    fun onBar(plan: Plan, zone: ChromeZone): List<Control> =
        plan.bar.filter { zoneOf(it) == zone }

    /**
     * What the More button opens: the whole advanced set, in the plan's order, minus nothing.
     *
     * [Control.MORE] itself is never a row of its own menu — a menu item that opens the menu it is
     * already in is a loop, and the bar owns that button.
     */
    fun menu(plan: Plan): List<Control> = plan.more.filter { it != Control.MORE }

    /**
     * True when every control on this plan's bar has a real place on the surface and every control
     * behind More maps to [ChromeZone.MENU]. The screen asserts nothing about this at runtime; the
     * test does, so a table edit that forgets a zone fails there rather than on a phone.
     */
    fun covers(plan: Plan): Boolean =
        plan.bar.all { zoneOf(it) != ChromeZone.MENU } &&
            menu(plan).all { zoneOf(it) == ChromeZone.MENU }
}
