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

    /**
     * A word the helper has never heard of. `subtitleStatusLabel` takes the off-word as a
     * parameter instead of owning it, so the screen can speak the resource value while this test
     * proves the helper hardcodes nothing: a sentinel the helper could not possibly invent, echoed
     * back, is the whole assertion.
     */
    private val OFF_WORD = "no text track"

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
    fun `volume and fullscreen are real buttons, not gestures alone`() {
        assertTrue("the bottom row needs a Volume button", source.contains("vm.toggleMute()"))
        assertTrue("the bottom row needs a Fullscreen button", source.contains("vm.toggleFullscreen()"))
        assertTrue("the Volume button must say its level", source.contains("R.string.player_volume"))
        assertTrue("a muted player must say it is muted", source.contains("R.string.player_volume_muted"))
        assertTrue("the Fullscreen button must be named", source.contains("R.string.player_fullscreen"))
        assertTrue("leaving fullscreen must be named too", source.contains("R.string.player_exit_fullscreen"))
    }

    @Test
    fun `a long press on volume opens the level slider`() {
        assertTrue(
            "the Volume button must offer its level on a long press",
            source.contains("onLongClick = { showVolumeDialog = true }"),
        )
        assertTrue(
            "the slider must write the same volume the gesture writes",
            source.contains("onValueChange = { vm.setUserVolume(it) }"),
        )
    }

    /**
     * The bottom row, from its signature to the next top-level function — the shared
     * `functionBody` helper would stop at the first blank line inside this long body.
     */
    private fun bottomControlsBody(): String {
        val start = source.indexOf("private fun BottomControls(")
        assertTrue("PlayerScreen.kt no longer declares BottomControls", start >= 0)
        val end = source.indexOf("\nprivate fun subtitleActive(", start)
        assertTrue("cannot find the end of BottomControls", end >= 0)
        return source.substring(start, end)
    }

    /** The More sheet, from its signature to the next sheet's opt-in annotation. */
    private fun moreSheetBody(): String {
        val start = source.indexOf("private fun MoreSheet(")
        assertTrue("PlayerScreen.kt no longer declares MoreSheet", start >= 0)
        // The next sheet is PrintLogSheet, whose opt-in also covers the
        // ExperimentalFoundationApi its long-press title needs — the marker
        // tracks the real annotation, not a shorter one.
        val end = source.indexOf("\n@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)", start)
        assertTrue("cannot find the end of MoreSheet", end >= 0)
        return source.substring(start, end)
    }

    @Test
    fun `the bottom row is exactly the six primaries`() {
        val row = bottomControlsBody()
        listOf(
            "vm.togglePlayPause()" to "Play/Pause",
            "vm.toggleMute()" to "Volume",
            "vm.showSubtitleSheet()" to "Subtitles",
            "vm.showQualitySheet()" to "Quality",
            "vm.toggleFullscreen()" to "Fullscreen",
            "vm.showMoreSheet()" to "More",
        ).forEach { (call, name) ->
            assertTrue("the bottom row lost its $name primary", row.contains(call))
        }
        assertTrue("the More button must be named", row.contains("R.string.player_more"))
        assertFalse(
            "the bottom row must not scroll — six buttons fit every phone, and a " +
                "hidden seventh would be a button that lies",
            row.contains("horizontalScroll"),
        )
    }

    @Test
    fun `nothing else lives in the bottom row`() {
        val row = bottomControlsBody()
        listOf(
            "vm.showSubtitleOffsetSheet()", "vm.showTracksSheet()", "vm.showSpeedSheet()",
            "vm.setLocked(true)", "vm.seekBy(", "vm.stepFrame(", "vm.requestNextEpisode()",
            "vm.showSleepSheet()", "vm.cycleAspect()", "vm.toggleOrientation()",
            "vm.toggleAudioOnly()", "vm.toggleStereoOnly()", "vm.toggleViewMode()",
            "PlayerControlButton(onEnterPip",
        ).forEach { moved ->
            assertFalse(
                "the bottom row still carries $moved — it belongs in the More sheet",
                row.contains(moved),
            )
        }
    }

    @Test
    fun `the More sheet carries every moved control, grouped`() {
        val sheet = moreSheetBody()
        listOf(
            // Playback
            "vm.showSpeedSheet()", "vm.showSleepSheet()", "vm.stepFrame(-1)", "vm.stepFrame(1)",
            "vm.seekBy(-10_000)", "vm.seekBy(10_000)", "vm.cycleAspect()", "vm.toggleOrientation()",
            "vm.toggleViewMode()",
            // Subtitle
            "vm.showSubtitleSheet()", "vm.showSubtitleOffsetSheet()",
            // Audio
            "vm.showTracksSheet()", "vm.cycleAudioTrack()", "vm.toggleAudioOnly()", "vm.toggleStereoOnly()",
            // Tools
            "vm.requestNextEpisode()", "vm.showPlayFromDialog()", "vm.openCalibration()",
            "vm.showPrintSheet()", "vm.retryCurrentCandidates()", "vm.openWithExternalPlayer()",
            "onEnterPip()",
        ).forEach { moved ->
            assertTrue("the More sheet lost $moved", sheet.contains(moved))
        }
        listOf(
            "R.string.player_more_playback", "R.string.player_subtitles_title",
            "R.string.player_audio_title", "R.string.player_more_tools",
        ).forEach { title ->
            assertTrue("the More sheet lost its $title group", sheet.contains(title))
        }
    }

    @Test
    fun `a slow start earns a hint and, later, actions`() {
        val card = functionBody("private fun StartNoticeCard(")
        assertTrue(
            "the notice must say the wait is normal once it passes two seconds",
            card.contains("R.string.player_start_slow"),
        )
        assertTrue(
            "the notice must name the rung being found",
            card.contains("R.string.player_quality_label"),
        )
        assertTrue(
            "the notice must offer a retry once it passes eight seconds",
            card.contains("R.string.player_retry"),
        )
        assertTrue(
            "the notice must offer another print once it passes eight seconds",
            card.contains("R.string.player_start_try_another"),
        )
        assertTrue(
            "the notice must be driven by the deadline stage, not a fixed timer",
            source.contains("state.startDeadlineStage"),
        )
        assertTrue(
            "the actions must call the manual failover, not just a retry",
            source.contains("vm.tryNextPrint()"),
        )
    }

    @Test
    fun `the thirty-second give-up is its own reason`() {
        val card = functionBody("private fun GiveUpCard(")
        assertTrue(
            "the give-up card must know the timeout reason",
            card.contains("HandoffWhy.START_TIMEOUT"),
        )
        assertTrue(
            "the timeout must have its own title, not the no-candidate one",
            card.contains("R.string.player_giveup_timeout"),
        )
        assertTrue(
            "the timeout must have its own body, not the no-candidate one",
            card.contains("R.string.player_giveup_timeout_body"),
        )
        assertTrue(
            "the timeout card must offer another print",
            card.contains("R.string.player_start_try_another"),
        )
        assertTrue(
            "the deadline card must dismiss into a fresh thirty seconds",
            source.contains("vm.dismissDeadlineGiveUp()"),
        )
    }

    @Test
    fun `the print sheet shows how fast the start was`() {
        val start = source.indexOf("private fun PrintLogSheet(")
        assertTrue("PlayerScreen.kt no longer declares PrintLogSheet", start >= 0)
        val end = source.indexOf("\n@Composable", start)
        assertTrue("cannot find the end of PrintLogSheet", end >= 0)
        val sheet = source.substring(start, end)
        assertTrue(
            "the print sheet must show the measured first-frame time",
            sheet.contains("R.string.player_first_frame"),
        )
        assertTrue(
            "the timing must come from the ViewModel's measurement, not a guess",
            sheet.contains("state.lastFirstFrameMs"),
        )
    }

    @Test
    fun `nothing is announced while no text track is loaded`() {
        assertEquals(OFF_WORD, subtitleStatusLabel(PlayerUiState(), OFF_WORD))
    }

    @Test
    fun `an external file is named by its own label`() {
        val state = PlayerUiState(customSubtitleLoaded = "subtitles.srt")
        assertEquals("subtitles.srt", subtitleStatusLabel(state, OFF_WORD))
    }

    @Test
    fun `a selected track the player no longer reports is not claimed as loaded`() {
        // The handle survives a rendition swap while the track list does not, and saying
        // "English [CC]" about a track that is gone would be the button lying. Building a real
        // Media3 TrackUiOption needs a device-side class, so this covers the empty-report case,
        // which is the one that can strand a stale id.
        assertEquals(OFF_WORD, subtitleStatusLabel(PlayerUiState(selectedSubtitleId = "9"), OFF_WORD))
    }
}
