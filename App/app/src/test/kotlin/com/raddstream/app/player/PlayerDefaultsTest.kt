package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Player defaults in Settings (plan §5 step 10, P36): the autoplay-next switch
 * gates the auto-advance, and the default-quality band is a standing decision
 * that outranks Auto's pick but never an explicit tap.
 */
class PlayerDefaultsTest {

    private val nextBundle = NextEpisodeAction.NextBundleRequest(
        workKey = "w1",
        postId = 1,
        season = 1,
        nextEpisode = 2,
        episodeId = null,
    )
    private val inFile = NextEpisodeAction.InFileSeek(
        positionMs = 60_000L,
        nextEpisode = 2,
        fromLearned = false,
    )
    private val rungs = listOf("1080p", "720p", "480p")

    @Test
    fun `autoplay on advances to the next bundle`() {
        assertTrue(shouldAutoAdvance(true, nextBundle))
    }

    @Test
    fun `autoplay off ends on the Next Episode button, no auto-advance`() {
        assertFalse(shouldAutoAdvance(false, nextBundle))
    }

    @Test
    fun `an in-file seek never auto-advances, switch or no switch`() {
        assertFalse(shouldAutoAdvance(true, inFile))
        assertFalse(shouldAutoAdvance(false, inFile))
    }

    @Test
    fun `a movie ending advances nowhere`() {
        assertFalse(shouldAutoAdvance(true, NextEpisodeAction.StopHere))
        assertFalse(shouldAutoAdvance(true, NextEpisodeAction.Unknown))
    }

    @Test
    fun `default band applies when Play was Auto`() {
        assertEquals("720p" to false, resolveStartBand("1080p", true, "720p", rungs))
    }

    @Test
    fun `an explicit tap outranks the default band`() {
        assertEquals("1080p" to false, resolveStartBand("1080p", false, "720p", rungs))
    }

    @Test
    fun `no default means Auto keeps its pick`() {
        assertEquals("1080p" to true, resolveStartBand("1080p", true, "auto", rungs))
    }

    @Test
    fun `a default band missing from this ladder is ignored`() {
        assertEquals("1080p" to true, resolveStartBand("1080p", true, "2160p", rungs))
    }

    @Test
    fun `no staged band falls back to the default, then the first rung`() {
        assertEquals("720p" to false, resolveStartBand(null, true, "720p", rungs))
        assertEquals("1080p" to true, resolveStartBand(null, true, "auto", rungs))
    }
}
