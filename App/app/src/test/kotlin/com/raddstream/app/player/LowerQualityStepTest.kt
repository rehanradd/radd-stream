package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The "Try lower quality" step. Two rules, both invisible on a JVM run of the screen and both
 * cheap to get wrong: the step must land on the band immediately below, and it must refuse when
 * there is nothing below — rather than doing what [QualityChoice.fallbackFrom] does when handed a
 * band it cannot step down from, which is offer the nearest HIGHER one.
 */
class LowerQualityStepTest {

    private val ladder = listOf("360p", "480p", "720p", "1080p")

    @Test
    fun `one step down, and only one`() {
        assertEquals("720p", LowerQualityStep.nextLower("1080p", ladder))
        assertEquals("480p", LowerQualityStep.nextLower("720p", ladder))
        assertEquals("360p", LowerQualityStep.nextLower("480p", ladder))
    }

    @Test
    fun `the bottom band has nowhere lower to go`() {
        // The button must not be painted here: a "Try lower quality" press that did nothing would
        // be the fake affordance the spec bans, and a press that stepped UP would be a lie.
        assertNull(LowerQualityStep.nextLower("360p", ladder))
        assertFalse(LowerQualityStep.available("360p", ladder))
    }

    @Test
    fun `a higher neighbour is never taken for a lower one`() {
        // This is the whole reason the rule is not a bare fallbackFrom call: with 360p removed from
        // the list the same call answers 480p, which is the opposite of what the button says.
        assertNull(LowerQualityStep.nextLower("360p", listOf("360p", "480p", "720p")))
        assertFalse(LowerQualityStep.available("720p", listOf("720p")))
    }

    @Test
    fun `no band on screen means no step down from it`() {
        assertNull(LowerQualityStep.nextLower(null, ladder))
        assertNull(LowerQualityStep.nextLower("  ", ladder))
        assertFalse(LowerQualityStep.available(null, ladder))
    }

    @Test
    fun `two spellings of one picture are one band, not a step`() {
        // A saved "4K" on a ladder that says "2160p" must not step to itself. QualityChoice folds
        // the synonym, so the only candidate left is 1080p — and the word handed back is the
        // ladder's own spelling, which is what a rung lookup matches on.
        assertEquals("1080p", LowerQualityStep.nextLower("4K", listOf("1080p", "2160p")))
        assertEquals("1080p", LowerQualityStep.nextLower("2160p", listOf("1080p", "4K")))
        assertEquals("1080p", LowerQualityStep.nextLower("2160p", listOf("4K", "1080p")))
        // The spelling case the rule exists for: a ladder whose lower rung reads FHD must be handed
        // back as FHD, because that is the word a rung lookup matches on. 4K is the CURRENT band
        // folded away, never the answer — stepping down to the picture you are already on.
        assertEquals("FHD", LowerQualityStep.nextLower("2160p", listOf("4K", "FHD")))
    }

    @Test
    fun `a band word this app cannot rank never buys a guess`() {
        // An unplaceable word has no measured lower neighbour. Offering the ladder's middle rung
        // would be inventing a step down from a picture this file has never seen.
        assertNull(LowerQualityStep.nextLower("hd-direct", ladder))
    }

    @Test
    fun `only the rungs this scope has are candidates`() {
        // A sparse ladder — the common case for an older catalogue row — still steps down by one.
        assertEquals("480p", LowerQualityStep.nextLower("1080p", listOf("480p", "1080p")))
        assertNull(LowerQualityStep.nextLower("480p", listOf("480p", "1080p")))
        assertTrue(LowerQualityStep.available("1080p", listOf("480p", "1080p")))
    }
}
