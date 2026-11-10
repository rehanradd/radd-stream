package com.raddstream.app.ui.navigation

import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Tv
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Text
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.dp
import com.raddstream.app.ui.theme.RaddStreamTheme
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * UI-layer half of the Robo run-4 a11y fix (Session 132): the bottom-nav items
 * still measured 32dp tall in Robo run 4 — under the 48dp touch-target floor —
 * even after run 3 added heightIn(min = 48.dp) to the item. The M3 source
 * (1.3.0, the version this app's compose-bom pins) shows why: the item's Box
 * already defaults to the 80dp bar height, and 32dp is the active-indicator
 * pill inside it — so the heightIn never reached the measured node. The item
 * now fills the bar's full height, and this test pins the rendered result: it
 * builds the bar exactly the way NavGraph does (NavigationBarItem, icon +
 * label, fillMaxHeight) and asserts every item's clickable node is at least
 * 48dp tall. Runs on the JVM under Robolectric because this project has no
 * emulator image.
 *
 * Requires an x86_64 runner. Robolectric's native runtime has no Linux/aarch64
 * build (robolectric/robolectric#9166) and it fails while the runner boots, so
 * the exclusion for ARM hosts lives in app/build.gradle.kts rather than here.
 */
@RunWith(RobolectricTestRunner::class)
class BottomNavTouchTargetTest {

    @get:Rule
    val compose = createComposeRule()

    private val items: List<Pair<String, ImageVector>> = listOf(
        "Home" to Icons.Default.Home,
        "Search" to Icons.Default.Search,
        "Live TV" to Icons.Default.Tv,
        "My List" to Icons.Default.Favorite,
        "Settings" to Icons.Default.Settings,
    )

    private fun showBar() {
        compose.setContent {
            RaddStreamTheme {
                NavigationBar {
                    items.forEach { (label, icon) ->
                        NavigationBarItem(
                            icon = { Icon(icon, contentDescription = label) },
                            label = { Text(label) },
                            selected = label == "Home",
                            onClick = {},
                            modifier = Modifier.fillMaxHeight(),
                        )
                    }
                }
            }
        }
    }

    @Test
    fun bottomNavItemsAreAtLeast48dpTall() {
        showBar()
        // The bar's only clickable nodes are its five items — one per tab.
        val clickable = compose.onAllNodes(hasClickAction())
        clickable.assertCountEquals(items.size)
        for (node in clickable.fetchSemanticsNodes()) {
            val height = with(compose.density) { node.boundsInRoot.height.toDp() }
            assertTrue(
                "bottom-nav item is only $height tall, under the 48dp floor",
                height >= 48.dp,
            )
        }
    }

    @Test
    fun bottomNavItemsAreTheFullBarHeight() {
        showBar()
        // The bar is 80dp by the M3 spec, and the item fills it — so the
        // clickable is the whole bar, not the 32dp indicator pill inside it.
        // This is the number Robo run 4 measured (32dp); if it ever drops
        // back to 32dp here, the indicator is the measured node again.
        val clickable = compose.onAllNodes(hasClickAction())
        clickable.assertCountEquals(items.size)
        for (node in clickable.fetchSemanticsNodes()) {
            val height = with(compose.density) { node.boundsInRoot.height.toDp() }
            assertTrue(
                "bottom-nav item is $height tall, expected the full 80dp bar height",
                height in 79.dp..81.dp,
            )
        }
    }
}
