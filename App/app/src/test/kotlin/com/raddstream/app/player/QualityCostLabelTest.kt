package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Quality sheet MB/hour labels (plan §5 step 9, §1.7 guide): each rung shows its
 * plain-words data cost before the tap — nobody else does this, and it is exactly
 * what a viewer on mobile data needs. The cost comes from the band alone, never
 * from the file's size: a download's size is not an hour of watching.
 */
class QualityCostLabelTest {

    @Test
    fun `every known band has a cost`() {
        assertEquals("≈ 7–11 GB/hour", qualityCostPerHour("2160p"))
        assertEquals("≈ 3 GB/hour", qualityCostPerHour("1080p"))
        assertEquals("≈ 1.5 GB/hour", qualityCostPerHour("720p"))
        assertEquals("≈ 700 MB/hour", qualityCostPerHour("480p"))
        assertEquals("≈ 300 MB/hour", qualityCostPerHour("sd"))
    }

    @Test
    fun `unknown or unbanded rungs show no cost rather than a guess`() {
        assertNull(qualityCostPerHour("unspecified"))
        assertNull(qualityCostPerHour("144p"))
        assertNull(qualityCostPerHour(""))
    }

    @Test
    fun `band matching ignores case and surrounding space`() {
        assertEquals("≈ 1.5 GB/hour", qualityCostPerHour(" 720P "))
        assertEquals("≈ 300 MB/hour", qualityCostPerHour("SD"))
    }
}
