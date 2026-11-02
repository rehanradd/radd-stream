package com.raddstream.app.player

import com.raddstream.app.player.PlayerChromePlan.Control
import com.raddstream.app.player.PlayerChromePlan.Inputs
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The player chrome table. Two things are pinned here that no screen can show on a phone in a
 * review: that every advanced control still EXISTS on the surface it was moved to, and that the
 * conditional buttons appear for exactly the titles they can act on.
 */
class PlayerChromePlanTest {

    private val full = Inputs(
        subtitleCount = 2,
        audioTrackCount = 2,
        qualityCount = 3,
        hasNextEpisode = true,
        canEnterPictureInPicture = true,
    )

    private fun bare(subtitleCount: Int = 0, audioTrackCount: Int = 1, qualityCount: Int = 1) =
        Inputs(subtitleCount, audioTrackCount, qualityCount, hasNextEpisode = false, canEnterPictureInPicture = false)

    @Test
    fun `the simple surface is the players surface`() {
        assertEquals(
            listOf(
                Control.BACK,
                Control.TITLE,
                Control.PLAY_PAUSE,
                Control.SEEK,
                Control.ELAPSED,
                Control.SKIP_BACK,
                Control.SKIP_FORWARD,
                Control.FULLSCREEN,
                Control.QUALITY,
                Control.SUBTITLES,
                Control.AUDIO_TRACKS,
                Control.MORE,
            ),
            PlayerChromePlan.plan(full).bar,
        )
    }

    @Test
    fun `nothing was deleted — every control appears exactly once`() {
        // The spec's word for the advanced set is MOVED. This is that promise: with everything this
        // title can do available, the two lists together are the whole vocabulary, with no control
        // painted twice for one action.
        val plan = PlayerChromePlan.plan(full)
        val shown = plan.bar + plan.more
        assertEquals("a control went missing from the surface", Control.values().size, shown.size)
        assertEquals("a control is on both halves", shown.distinct().size, shown.size)
    }

    @Test
    fun `an advanced control is never on the simple bar`() {
        val plan = PlayerChromePlan.plan(full)
        for (control in plan.more) {
            assertFalse("$control cannot be on the bar and behind More at once", control in plan.bar)
        }
        for (control in listOf(Control.SPEED, Control.SLEEP_TIMER, Control.ASPECT, Control.CINEMA_MODE, Control.SOURCE_LOG)) {
            assertTrue("$control belongs behind More", control in plan.more)
        }
    }

    @Test
    fun `subtitles appear only when the title has subtitles`() {
        assertFalse(Control.SUBTITLES in PlayerChromePlan.plan(bare(subtitleCount = 0)).bar)
        assertTrue(Control.SUBTITLES in PlayerChromePlan.plan(bare(subtitleCount = 1)).bar)
    }

    @Test
    fun `audio tracks appear only when there is more than one`() {
        assertFalse(Control.AUDIO_TRACKS in PlayerChromePlan.plan(bare(audioTrackCount = 1)).bar)
        assertTrue(Control.AUDIO_TRACKS in PlayerChromePlan.plan(bare(audioTrackCount = 2)).bar)
    }

    @Test
    fun `quality appears only when there is a band to switch to`() {
        assertFalse(Control.QUALITY in PlayerChromePlan.plan(bare(qualityCount = 1)).bar)
        assertTrue(Control.QUALITY in PlayerChromePlan.plan(bare(qualityCount = 2)).bar)
    }

    @Test
    fun `More is always there, because the advanced set is always reachable`() {
        assertTrue(Control.MORE in PlayerChromePlan.plan(bare()).bar)
    }

    @Test
    fun `next episode and picture-in-picture are advanced, and conditional`() {
        assertTrue(Control.NEXT_EPISODE in PlayerChromePlan.plan(full).more)
        assertTrue(Control.PICTURE_IN_PICTURE in PlayerChromePlan.plan(full).more)
        assertFalse(Control.NEXT_EPISODE in PlayerChromePlan.plan(bare()).more)
        assertFalse(Control.PICTURE_IN_PICTURE in PlayerChromePlan.plan(bare()).more)
    }

    @Test
    fun `the bar leaves after three seconds`() {
        assertEquals(3000L, PlayerChromePlan.AUTO_HIDE_MS)
        assertEquals(3000L, PlayerChromePlan.plan(full).autoHideMs)
    }

    @Test
    fun `a locked title is a prompt, not a bar of controls that all answer no`() {
        val plan = PlayerChromePlan.plan(full.copy(isLockedOutByEntitlement = true))
        assertEquals(listOf(Control.TITLE, Control.PLAY_PAUSE, Control.FULLSCREEN), plan.bar)
        assertTrue(plan.more.isEmpty())
    }
}
