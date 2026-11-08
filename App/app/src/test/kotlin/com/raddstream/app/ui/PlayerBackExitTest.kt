package com.raddstream.app.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * System Back must leave the player (Session 117): the 114 device retest
 * pressed it while the give-up card was up and three times during playback,
 * and the player never exited — the only BackHandler in the app lived in
 * EmbedWebViewScreen, and the player relied on the nav stack's implicit
 * handling plus the give-up dialog's own dismiss. Nothing about that fails
 * a compile, so this is a drift test over the source itself, in the
 * `PlayerControlSemanticsTest` pattern: the wiring must stay in the file,
 * in the player content, calling the same back callback the top-left arrow
 * and the "Back to details" button already use.
 */
class PlayerBackExitTest {

    private val playerScreen: File by lazy {
        var dir: File? = File("").absoluteFile
        while (dir != null) {
            if (File(dir, "brand.properties").isFile) {
                return@lazy File(
                    dir,
                    "App/app/src/main/kotlin/com/raddstream/app/ui/screens/PlayerScreen.kt",
                )
            }
            dir = dir.parentFile
        }
        error("brand.properties not found above ${File("").absolutePath}")
    }

    private val source: String by lazy {
        assertTrue("PlayerScreen.kt is missing at ${playerScreen.path}", playerScreen.isFile)
        playerScreen.readText()
    }

    @Test
    fun `the player imports the activity back handler`() {
        assertTrue(
            "PlayerScreen must import androidx.activity.compose.BackHandler",
            source.contains("import androidx.activity.compose.BackHandler"),
        )
    }

    @Test
    fun `system back in the player content exits to details`() {
        val contentStart = source.indexOf("private fun PlayerScreenContent(")
        assertTrue("PlayerScreen.kt no longer declares PlayerScreenContent", contentStart >= 0)
        val contentEnd = source.indexOf("private fun PlayerSurface(", contentStart)
        assertTrue("PlayerScreen.kt no longer declares PlayerSurface after the content", contentEnd > contentStart)
        val body = source.substring(contentStart, contentEnd)
        assertTrue(
            "PlayerScreenContent must register BackHandler { onBackClick() } — " +
                "without it, system Back during playback has no handler of its own",
            body.contains("BackHandler { onBackClick() }"),
        )
    }

    @Test
    fun `the give-up card still exits on dismiss request`() {
        // The dialog's own Back and outside-tap path (Session 114): dismiss
        // must leave the player, never just hide the card — "Close" is the
        // only button that means keep waiting.
        assertTrue(
            "GiveUpCard must keep onDismissRequest = onBackToDetails",
            source.contains("onDismissRequest = onBackToDetails"),
        )
    }

    @Test
    fun `exactly one screen-level back handler in the player`() {
        // Two would fight over the press; the dialog's own handler (registered
        // later, while the card shows) is the only other one allowed, and it
        // lives inside GiveUpCard's AlertDialog, not here.
        val count = "BackHandler".toRegex().findAll(source).count()
        assertEquals(
            "PlayerScreen.kt should mention BackHandler exactly twice — " +
                "the import and the one call in PlayerScreenContent",
            2,
            count,
        )
    }
}
