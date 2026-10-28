package com.raddstream.app.ui

import com.raddstream.app.player.PlayerUiState
import com.raddstream.app.ui.screens.subtitleStatusLabel
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * The player control lane names every one of its buttons — and used to throw every name away:
 * the composable took a `contentDescription` it never read, each Icon inside passed `null`, and
 * the slots were forced to 42 dp and 38 dp. Nothing about that fails a compile, so this is a
 * drift test over the source itself, in the `BrandDriftTest` pattern, plus the one rule that IS
 * ordinary logic: what the subtitles button says.
 */
class PlayerControlSemanticsTest {

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

    /**
     * The body of one top-level function, from its signature to the end of its declaration —
     * whichever comes first: a closing brace at column 0 (a block body) or the next blank line
     * (an expression body like the press helper's).
     */
    private fun functionBody(signature: String): String {
        val start = source.indexOf(signature)
        assertTrue("PlayerScreen.kt no longer declares $signature", start >= 0)
        val close = source.indexOf("\n}\n", start)
        val blank = source.indexOf("\n\n", start)
        val end = when {
            close < 0 && blank < 0 -> source.length
            close < 0 -> blank
            blank < 0 -> close
            else -> minOf(close, blank)
        }
        return source.substring(start, end)
    }

    @Test
    fun `the minimum touch target is the Android minimum`() {
        assertTrue(
            "every player press must be at least 48 dp",
            source.contains("private val MinControlTarget = 48.dp"),
        )
    }

    @Test
    fun `no control keeps a slot smaller than the minimum`() {
        listOf("Modifier.size(38.dp)", "Modifier.size(42.dp)").forEach { retired ->
            assertFalse(
                "PlayerScreen still forces a control into $retired — that is under the " +
                    "48 dp a fingertip is entitled to",
                source.contains(retired),
            )
        }
    }

    @Test
    fun `the press a control uses gives its label to a screen reader`() {
        val body = functionBody("private fun ControlTarget(")
        assertTrue(
            "ControlTarget declares a label and never publishes it, which is how sixteen " +
                "named controls became invisible",
            body.contains("contentDescription ="),
        )
        assertTrue("ControlTarget must be a real press", body.contains(".clickable("))
        assertTrue("ControlTarget must be announced as a button", body.contains("role = Role.Button"))
        assertTrue(
            "ControlTarget must be at least the minimum target",
            body.contains(".size(MinControlTarget)"),
        )
    }

    @Test
    fun `the lane button hands its label down instead of dropping it`() {
        val body = functionBody("private fun PlayerControlButton(")
        assertTrue(
            "a contentDescription parameter nobody reads is the bug this test exists for",
            !body.contains("contentDescription: String"),
        )
        assertTrue("PlayerControlButton must route through ControlTarget", body.contains("ControlTarget("))
        assertTrue("PlayerControlButton must pass its label on", body.contains("label = label"))
    }

    @Test
    fun `a borderless press is still a press an accessibility service can take`() {
        val body = functionBody("private fun Modifier.clickableNoRipple(")
        assertTrue(
            "a raw tap detector publishes no click action, so sheet rows and chips cannot be " +
                "activated by a screen reader",
            body.contains("Modifier.clickable("),
        )
        assertTrue("the press must be announced as a button", body.contains("role = Role.Button"))
        assertFalse("the borderless chrome look must stay borderless", body.contains("detectTapGestures"))
    }

    @Test
    fun `nothing is announced while no text track is loaded`() {
        assertEquals("off", subtitleStatusLabel(PlayerUiState()))
    }

    @Test
    fun `an external file is named by its own label`() {
        val state = PlayerUiState(customSubtitleLoaded = "subtitles.srt")
        assertEquals("subtitles.srt", subtitleStatusLabel(state))
    }

    @Test
    fun `a selected track the player no longer reports is not claimed as loaded`() {
        // The handle survives a rendition swap while the track list does not, and saying
        // "English [CC]" about a track that is gone would be the button lying. Building a real
        // Media3 TrackUiOption needs a device-side class, so this covers the empty-report case,
        // which is the one that can strand a stale id.
        assertEquals("off", subtitleStatusLabel(PlayerUiState(selectedSubtitleId = "9")))
    }
}
