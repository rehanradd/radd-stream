package com.raddstream.app.ui.navigation

import org.junit.Assert.assertEquals
import org.junit.Test

class StartupRoutingTest {

    @Test
    fun `no saved url and no shipped default goes to Setup`() {
        assertEquals(
            StartDestination.Setup,
            resolveStartDestination(
                savedUrl = null,
                hasSavedServerUrl = false,
                defaultServerReachable = null,
                regionUnanswered = true,
            ),
        )
    }

    @Test
    fun `blank saved url goes to Setup`() {
        assertEquals(
            StartDestination.Setup,
            resolveStartDestination(
                savedUrl = "   ",
                hasSavedServerUrl = false,
                defaultServerReachable = true,
                regionUnanswered = false,
            ),
        )
    }

    @Test
    fun `fresh install whose shipped server did not answer goes to Setup`() {
        assertEquals(
            StartDestination.Setup,
            resolveStartDestination(
                savedUrl = "http://92.4.95.252",
                hasSavedServerUrl = false,
                defaultServerReachable = false,
                regionUnanswered = true,
            ),
        )
    }

    @Test
    fun `fresh install whose shipped server was never probed goes to Setup`() {
        assertEquals(
            StartDestination.Setup,
            resolveStartDestination(
                savedUrl = "http://92.4.95.252",
                hasSavedServerUrl = false,
                defaultServerReachable = null,
                regionUnanswered = false,
            ),
        )
    }

    @Test
    fun `fresh install whose shipped server answered goes to Region when unanswered`() {
        assertEquals(
            StartDestination.Region,
            resolveStartDestination(
                savedUrl = "http://92.4.95.252",
                hasSavedServerUrl = false,
                defaultServerReachable = true,
                regionUnanswered = true,
            ),
        )
    }

    @Test
    fun `fresh install whose shipped server answered goes to Home when region answered`() {
        assertEquals(
            StartDestination.Home,
            resolveStartDestination(
                savedUrl = "http://92.4.95.252",
                hasSavedServerUrl = false,
                defaultServerReachable = true,
                regionUnanswered = false,
            ),
        )
    }

    @Test
    fun `returning install skips the probe and goes to Region when unanswered`() {
        assertEquals(
            StartDestination.Region,
            resolveStartDestination(
                savedUrl = "http://92.4.95.252",
                hasSavedServerUrl = true,
                defaultServerReachable = null,
                regionUnanswered = true,
            ),
        )
    }

    @Test
    fun `returning install skips the probe and goes to Home when region answered`() {
        assertEquals(
            StartDestination.Home,
            resolveStartDestination(
                savedUrl = "http://92.4.95.252",
                hasSavedServerUrl = true,
                defaultServerReachable = null,
                regionUnanswered = false,
            ),
        )
    }
}
