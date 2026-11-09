package com.raddstream.app.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
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

    /**
     * Session 120: the give-up card's five actions sat in two side-by-side
     * Rows inside AlertDialog's single button row, and on a 360 dp phone
     * "Open with another player" wrapped onto four lines while "Close"
     * printed over its final letter. The actions stack vertically now, each
     * full width, so every one is fully visible and tappable.
     */
    private val giveUpCardBody: String by lazy {
        val start = source.indexOf("private fun GiveUpCard(")
        assertTrue("PlayerScreen.kt no longer declares GiveUpCard", start >= 0)
        val end = source.indexOf("Subtitle overlay", start)
        assertTrue("PlayerScreen.kt no longer has the subtitle overlay after GiveUpCard", end > start)
        source.substring(start, end)
    }

    @Test
    fun `give-up card stacks its actions vertically`() {
        assertTrue(
            "GiveUpCard must lay its actions in a full-width Column, not a Row — " +
                "five actions in one horizontal row overflow a phone dialog",
            giveUpCardBody.contains("Column(Modifier.fillMaxWidth())"),
        )
        assertFalse(
            "GiveUpCard must not lay actions out in a Row — that is the layout " +
                "that wrapped 'Open with another player' onto four lines",
            giveUpCardBody.contains("Row {"),
        )
    }

    @Test
    fun `give-up card offers all five actions`() {
        listOf(
            "player_retry",
            "player_start_try_another",
            "player_open_external",
            "player_back_to_details",
            "player_keep_waiting",
        ).forEach { action ->
            assertTrue("GiveUpCard must offer $action", giveUpCardBody.contains(action))
        }
    }

    @Test
    fun `handoff card offers try another print when one exists`() {
        // Session 120: only the deadline card offered it, so after every
        // candidate failed the viewer could only retry the same dead ladder.
        val start = source.indexOf("state.giveUp?.let")
        assertTrue("PlayerScreen.kt no longer shows the handoff GiveUpCard", start >= 0)
        val end = source.indexOf("} ?: if (state.deadlineGiveUp)", start)
        assertTrue("PlayerScreen.kt no longer has the deadline branch after the handoff card", end > start)
        val handoff = source.substring(start, end)
        assertTrue(
            "the handoff GiveUpCard must offer onTryAnother when canTryAnotherPrint — " +
                "tryNextPrint moves to a different print, never the same URL again",
            handoff.contains("onTryAnother"),
        )
    }
}
