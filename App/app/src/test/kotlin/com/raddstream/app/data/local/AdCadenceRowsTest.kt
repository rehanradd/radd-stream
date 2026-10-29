package com.raddstream.app.data.local

import com.raddstream.app.player.AdCadenceState
import com.raddstream.app.player.AdSurface
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The persistence contract of the ad cadence, proved without opening Room.
 *
 * This bridge is worth pinning precisely because a device cannot be driven from here: Robolectric
 * has no native runtime on aarch64, so an in-memory database test would be a test that never runs.
 * A state that quietly lost its stamps on the way to disk would look identical on screen and only
 * differ after a process death — which is the one behaviour the cadence exists to guarantee.
 */
class AdCadenceRowsTest {

    @Test
    fun `a fresh state writes three rows and reads back as fresh`() {
        val rows = AdCadenceRows.toRows(AdCadenceState())
        assertEquals(
            setOf("PRE_ROLL", "FEED_CARD", "APP_OPEN"),
            rows.map { it.surface }.toSet(),
        )
        assertEquals(3, rows.size)
        assertEquals(AdCadenceState(), AdCadenceRows.toState(rows, enabled = false))
    }

    @Test
    fun `every field survives the round trip`() {
        val state = AdCadenceState(
            enabled = true,
            preRollShownAtMs = 1_730_000_000_000L,
            feedCardShownAtMs = 1_730_000_060_000L,
            postersSinceFeedCard = 7,
            appOpenShownAtMs = 1_730_000_120_000L,
        )
        assertEquals(state, AdCadenceRows.toState(AdCadenceRows.toRows(state), enabled = true))
    }

    @Test
    fun `only the feed card carries a poster count`() {
        val rows = AdCadenceRows.toRows(AdCadenceState(postersSinceFeedCard = 11))
        assertEquals(11, rows.single { it.surface == "FEED_CARD" }.postersScrolled)
        assertEquals(0, rows.single { it.surface == "PRE_ROLL" }.postersScrolled)
        assertEquals(0, rows.single { it.surface == "APP_OPEN" }.postersScrolled)
    }

    @Test
    fun `an absent row reads as never shown rather than as a zero that means something else`() {
        // A database that predates the table, or a poll that cleared it, must not look like an
        // impression taken at the epoch.
        val empty = AdCadenceRows.toState(emptyList(), enabled = true)
        assertEquals(0L, empty.preRollShownAtMs)
        assertEquals(0, empty.postersSinceFeedCard)
        assertTrue("never-shown is what makes a fresh install eligible", empty.preRollShownAtMs <= 0L)
    }

    @Test
    fun `a partial table still reads the surfaces it has`() {
        val rows = listOf(AdCadenceEntity("PRE_ROLL", 1_730_000_000_000L, 0))
        val state = AdCadenceRows.toState(rows, enabled = true)
        assertEquals(1_730_000_000_000L, state.preRollShownAtMs)
        assertEquals(0L, state.appOpenShownAtMs)
        assertEquals(0, state.postersSinceFeedCard)
    }

    @Test
    fun `the switch is the readers answer and never a stored column`() {
        val rows = AdCadenceRows.toRows(AdCadenceState(enabled = true))
        // Nothing in a row says "ads on": the switch lives on the server, so a stale table cannot
        // claim the feature is enabled after the operator turned it off.
        assertTrue(rows.none { "true" in it.toString() })
        assertFalse(AdCadenceRows.toState(rows, enabled = false).enabled)
        assertTrue(AdCadenceRows.toState(rows, enabled = true).enabled)
    }

    /**
     * A renamed surface enum would otherwise silently change the primary keys on disk: the old rows
     * would keep sitting there unread and every viewer would look brand new. This pins the keys to
     * the enum's own names so the two cannot drift apart without one of them failing to compile.
     */
    @Test
    fun `the row keys are the surface names and cover all three`() {
        val keys = AdCadenceRows.toRows(AdCadenceState()).map { it.surface }
        assertEquals(AdSurface.entries.map { it.name }.toSet(), keys.toSet())
    }
}
