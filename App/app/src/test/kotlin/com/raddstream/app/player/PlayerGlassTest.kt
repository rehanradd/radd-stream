package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** JVM tests for [PlayerGlass] (BM rule 9): glass where it is cheap, solid where it is not. */
class PlayerGlassTest {

    @Test
    fun `a normal device gets frosted chrome`() {
        val spec = PlayerGlass.spec(isLowRamDevice = false)
        assertTrue(spec.useGlass)
        assertEquals(0.55f, spec.tintAlpha, 0f)
        assertEquals(0.18f, spec.borderAlpha, 0f)
    }

    @Test
    fun `a low-RAM device gets solid chrome, never translucency to composite`() {
        val spec = PlayerGlass.spec(isLowRamDevice = true)
        assertFalse(spec.useGlass)
        assertEquals(1f, spec.tintAlpha, 0f)
        assertEquals(0f, spec.borderAlpha, 0f)
    }
}
