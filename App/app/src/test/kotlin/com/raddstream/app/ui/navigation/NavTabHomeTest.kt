package com.raddstream.app.ui.navigation

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * Samsung RTL retest (Issue 8): the bottom-nav Home tab did not switch
 * the app from Search to Home on three attempts after failed playback
 * cycles.
 *
 * The tap was gated on the composition-time route snapshot
 * (`currentRoute`, read when the bar last recomposed). After failed
 * playback cycles — rapid push/pop sequences through the player, with
 * the main thread busy on resolve retries — that snapshot can lag the
 * back stack, and a stale read turns every tap on the tab into a silent
 * no-op until something else recomposes the bar. The tap must read the
 * controller's live destination at tap time instead.
 *
 * Drift tests over the source in the `PlayerBackExitTest` pattern: the
 * graph needs Hilt screens to compose, so the wiring is pinned here.
 */
class NavTabHomeTest {

    private val navGraph: File by lazy {
        var dir: File? = File("").absoluteFile
        while (dir != null) {
            if (File(dir, "brand.properties").isFile) {
                return@lazy File(
                    dir,
                    "App/app/src/main/kotlin/com/raddstream/app/ui/navigation/NavGraph.kt",
                )
            }
            dir = dir.parentFile
        }
        error("brand.properties not found above ${File("").absolutePath}")
    }

    private val source: String by lazy {
        assertTrue("NavGraph.kt is missing at ${navGraph.path}", navGraph.isFile)
        navGraph.readText()
    }

    /** The bottom-bar block: from the tab loop to the Scaffold's content lambda. */
    private val bottomBarBody: String by lazy {
        val start = source.indexOf("bottomNavItems.forEach")
        assertTrue("NavGraph.kt no longer loops over bottomNavItems", start >= 0)
        val end = source.indexOf(") { innerPadding ->", start)
        assertTrue("NavGraph.kt no longer has the content lambda after the bottom bar", end > start)
        source.substring(start, end)
    }

    @Test
    fun `tab taps read the live destination, not the composition snapshot`() {
        assertTrue(
            "A tab tap must read navController.currentDestination at tap time — " +
                "the composition-time currentRoute snapshot can lag the back stack " +
                "after failed playback cycles and silently swallow the tap",
            bottomBarBody.contains("navController.currentDestination?.route != item.route"),
        )
        assertFalse(
            "No tab tap may be gated on the captured currentRoute snapshot",
            bottomBarBody.contains("if (currentRoute != item.route)"),
        )
    }

    @Test
    fun `home tab navigation still pops to home with state saved and restored`() {
        assertTrue(
            "Tapping Home must pop back to Home so the player/detail entries " +
                "above it leave the stack",
            bottomBarBody.contains("popUpTo(Screen.Home.route)"),
        )
        assertTrue(
            "The pop must save the popped entries' state, so returning to " +
                "Search restores it",
            bottomBarBody.contains("saveState = true"),
        )
        assertTrue(
            "A same-tab tap must stay a no-op at the controller level",
            bottomBarBody.contains("launchSingleTop = true"),
        )
        assertTrue(
            "Tapping Home must restore Home's saved state",
            bottomBarBody.contains("restoreState = true"),
        )
    }

    @Test
    fun `the bar still marks the selected tab from the current route`() {
        // The live read is for the tap only: the selected highlight and
        // the bar's own visibility keep reading the composed route, which
        // is all a visual needs.
        assertTrue(
            "The selected tab must still be derived from the current route",
            bottomBarBody.contains("val selected = currentRoute == item.route"),
        )
    }
}
