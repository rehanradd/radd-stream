package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The first-run gesture coach (plan §5 step 7): teach once on first open, once again
 * after a major version change, never for a minor update. These are the policy's own
 * boundaries — no player, no DataStore, no device.
 */
class CoachPolicyTest {

    @Test
    fun `never shown means show`() {
        assertTrue(shouldShowCoach(null, "1.0.4"))
    }

    @Test
    fun `same major means already taught`() {
        assertFalse(shouldShowCoach("1", "1.0.4"))
        assertFalse(shouldShowCoach("1", "1.9.9"))
        // A stored full version still compares by its major.
        assertFalse(shouldShowCoach("1.2.3", "1.0.4"))
    }

    @Test
    fun `a new major means show again`() {
        assertTrue(shouldShowCoach("1", "2.0.0"))
        assertTrue(shouldShowCoach("1", "2.0.1"))
    }

    @Test
    fun `major version is the first component`() {
        assertEquals("1", majorVersionOf("1.2.3"))
        assertEquals("2", majorVersionOf("2"))
        assertEquals("", majorVersionOf(""))
        assertEquals("3", majorVersionOf(" 3.0 "))
    }
}
