package com.raddstream.app.player

import com.raddstream.app.player.PlayerChromePlan.Control
import com.raddstream.app.player.PlayerChromePlan.Inputs
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Where the simple bar paints what [PlayerChromePlan] put on it.
 *
 * The plan says ON THE BAR; the owner's spec says where on the bar — back, title and picture at
 * the top, play/pause in the middle, position, the two skips, fullscreen, the two conditional
 * track buttons and the one More button at the bottom. That second decision is what this pins,
 * because a screen that gets it wrong is not red in a review: the buttons all still exist and all
 * still work, they are just in the wrong place on a surface nobody can look at from here.
 */
class PlayerChromeZonesTest {

    private val full = Inputs(
        subtitleCount = 2,
        audioTrackCount = 2,
        qualityCount = 3,
        hasNextEpisode = true,
        canEnterPictureInPicture = true,
    )

    private val bare = Inputs(
        subtitleCount = 0,
        audioTrackCount = 1,
        qualityCount = 1,
        hasNextEpisode = false,
        canEnterPictureInPicture = false,
    )

    @Test
    fun `the top row is leave, title and picture`() {
        assertEquals(
            listOf(Control.BACK, Control.TITLE, Control.QUALITY),
            PlayerChromeZones.onBar(PlayerChromePlan.plan(full), ChromeZone.TOP),
        )
    }

    @Test
    fun `the centre is the one big transport button`() {
        assertEquals(
            listOf(Control.PLAY_PAUSE),
            PlayerChromeZones.onBar(PlayerChromePlan.plan(full), ChromeZone.CENTRE),
        )
    }

    @Test
    fun `the bottom row is position, skips, fullscreen, the tracks and More`() {
        assertEquals(
            listOf(
                Control.SEEK,
                Control.ELAPSED,
                Control.SKIP_BACK,
                Control.SKIP_FORWARD,
                Control.FULLSCREEN,
                Control.SUBTITLES,
                Control.AUDIO_TRACKS,
                Control.MORE,
            ),
            PlayerChromeZones.onBar(PlayerChromePlan.plan(full), ChromeZone.BOTTOM),
        )
    }

    @Test
    fun `a title with no extra tracks still gets the whole bottom row it can use`() {
        // The conditional buttons are the plan's business; the mandatory set is this file's, and a
        // screen that painted them from a hardcoded list would ignore the plan entirely.
        assertEquals(
            listOf(
                Control.SEEK,
                Control.ELAPSED,
                Control.SKIP_BACK,
                Control.SKIP_FORWARD,
                Control.FULLSCREEN,
                Control.MORE,
            ),
            PlayerChromeZones.onBar(PlayerChromePlan.plan(bare), ChromeZone.BOTTOM),
        )
        assertFalse(
            "one band is not a choice, so the top row is leave and title only",
            Control.QUALITY in PlayerChromeZones.onBar(PlayerChromePlan.plan(bare), ChromeZone.TOP),
        )
    }

    @Test
    fun `the zone split drops nothing and repeats nothing`() {
        // A bar control that maps to no zone is a control the screen silently never paints, which is
        // the deletion the spec forbids; a control that lands in two zones is a button painted twice
        // for one action. Both are invisible in a review, so they are arithmetic here.
        val plan = PlayerChromePlan.plan(full)
        val placed = PlayerChromeZones.onBar(plan, ChromeZone.TOP) +
            PlayerChromeZones.onBar(plan, ChromeZone.CENTRE) +
            PlayerChromeZones.onBar(plan, ChromeZone.BOTTOM)
        assertEquals("a control was placed in two zones", plan.bar.size, placed.distinct().size)
        assertEquals("a control on the bar went to no zone at all", plan.bar.toSet(), placed.toSet())
        assertEquals(
            "a control behind More went to a bar zone",
            plan.more.size,
            PlayerChromeZones.menu(plan).count { PlayerChromeZones.zoneOf(it) == ChromeZone.MENU },
        )
        assertEquals(
            "the surface has four places and every one of them holds something",
            4,
            Control.values().map { PlayerChromeZones.zoneOf(it) }.distinct().size,
        )
    }

    @Test
    fun `the advanced set the owner named is behind More, not on the bar`() {
        listOf(
            Control.SPEED,
            Control.SLEEP_TIMER,
            Control.LOCK,
            Control.ASPECT,
            Control.SUBTITLE_DELAY,
            Control.FRAME_BACK,
            Control.FRAME_FORWARD,
            Control.OPEN_EXTERNALLY,
            Control.ORIENTATION,
            Control.AUDIO_ONLY,
            Control.STEREO_ONLY,
            Control.CINEMA_MODE,
            Control.PICTURE_IN_PICTURE,
            Control.SOURCE_LOG,
            Control.NEXT_EPISODE,
        ).forEach { control ->
            assertEquals("$control must live in the More menu", ChromeZone.MENU, PlayerChromeZones.zoneOf(control))
        }
    }

    @Test
    fun `a plan from the table is fully covered, in every shape the table can answer with`() {
        listOf(
            full,
            bare,
            full.copy(isLockedOutByEntitlement = true),
            bare.copy(subtitleCount = 1, audioTrackCount = 2),
        ).forEach { inputs ->
            val plan = PlayerChromePlan.plan(inputs)
            assertTrue("nothing dropped: $plan", PlayerChromeZones.covers(plan))
        }
    }

    @Test
    fun `the locked-out surface has a place for each of its three controls and no menu`() {
        val plan = PlayerChromePlan.plan(full.copy(isLockedOutByEntitlement = true))
        assertEquals(listOf(Control.TITLE), PlayerChromeZones.onBar(plan, ChromeZone.TOP))
        assertEquals(listOf(Control.PLAY_PAUSE), PlayerChromeZones.onBar(plan, ChromeZone.CENTRE))
        assertEquals(listOf(Control.FULLSCREEN), PlayerChromeZones.onBar(plan, ChromeZone.BOTTOM))
        assertTrue(plan.more.isEmpty())
    }

    @Test
    fun `More is a bar button, never a row of its own menu`() {
        val plan = PlayerChromePlan.plan(full)
        assertTrue(Control.MORE in plan.bar)
        assertFalse(
            "a menu item that opens the menu it is standing in is a loop",
            Control.MORE in PlayerChromeZones.menu(plan),
        )
        assertEquals("every advanced control is still reachable", plan.more, PlayerChromeZones.menu(plan))
    }
}
