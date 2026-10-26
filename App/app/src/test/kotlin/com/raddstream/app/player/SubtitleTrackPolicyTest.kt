package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * JVM tests for the subtitle-language preference — the chip row on Settings that used to be
 * a decoration. The three outcomes are the whole contract, so all three are covered here:
 * the name the viewer typed reaching a track whose atom spells it differently, no match
 * leaving the player's own choice untouched, and `Off` actually meaning off instead of
 * quietly doing nothing. The name-to-tag matching itself is [AudioTrackMatcher]'s, tested in
 * its own suite; these rows prove the subtitle path goes through it rather than around it.
 */
class SubtitleTrackPolicyTest {

    private fun textTrack(
        id: String,
        language: String? = null,
        label: String? = null,
        selected: Boolean = false,
        supported: Boolean = true,
    ) = AudioTrackRow(id = id, language = language, label = label, selected = selected, supported = supported)

    private val dualSubtitles = listOf(
        textTrack("g0-t0", language = "en", label = "English"),
        textTrack("g0-t1", language = "hin", label = "Hindi"),
    )

    // ── a preference that matches ───────────────────────────────────────────────

    @Test
    fun `a name typed on the chip row finds the track whose atom spells it as a code`() {
        // The viewer words "Hindi"; whoever muxed the file wrote "hin", "hi" or both.
        assertEquals(SubtitleTrackDecision.Select("g0-t1"), SubtitleTrackPolicy.decide(dualSubtitles, "Hindi"))
        assertEquals(SubtitleTrackDecision.Select("g0-t1"), SubtitleTrackPolicy.decide(dualSubtitles, "hi"))
        assertEquals(SubtitleTrackDecision.Select("g0-t1"), SubtitleTrackPolicy.decide(dualSubtitles, "hin"))
        assertEquals(SubtitleTrackDecision.Select("g0-t0"), SubtitleTrackPolicy.decide(dualSubtitles, "English"))
        // Case and stray spaces are the viewer's, not the policy's problem.
        assertEquals(
            SubtitleTrackDecision.Select("g0-t1"),
            SubtitleTrackPolicy.decide(dualSubtitles, "  hindi "),
        )
    }

    @Test
    fun `a subtitle track whose only clue is a human label still counts`() {
        // Fansub packs declare no language at all; the label is the whole record.
        val labelOnly = listOf(
            textTrack("g0-t0", label = "Comments"),
            textTrack("g1-t0", label = "English [CC]"),
        )
        assertEquals(SubtitleTrackDecision.Select("g1-t0"), SubtitleTrackPolicy.decide(labelOnly, "English"))
    }

    @Test
    fun `a preference already satisfied is not a re-selection`() {
        // Rewriting a working override restarts the renderer for no benefit to the viewer.
        val already = listOf(
            textTrack("g0-t0", language = "eng"),
            textTrack("g0-t1", language = "hin", selected = true),
        )
        assertEquals(
            SubtitleTrackDecision.LeaveAlone,
            SubtitleTrackPolicy.decide(already, "Hindi"),
        )
    }

    // ── a preference that does not match ────────────────────────────────────────

    @Test
    fun `an unmatched preference leaves the default alone`() {
        assertEquals(SubtitleTrackDecision.LeaveAlone, SubtitleTrackPolicy.decide(dualSubtitles, "Tamil"))
        assertEquals(SubtitleTrackDecision.LeaveAlone, SubtitleTrackPolicy.decide(dualSubtitles, "Telugu"))
        assertEquals(SubtitleTrackDecision.LeaveAlone, SubtitleTrackPolicy.decide(emptyList(), "English"))
    }

    @Test
    fun `a matching track the renderer cannot decode is not offered`() {
        val undecodable = listOf(
            textTrack("g0-t0", language = "eng"),
            textTrack("g0-t1", language = "hin", supported = false),
        )
        assertEquals(SubtitleTrackDecision.LeaveAlone, SubtitleTrackPolicy.decide(undecodable, "Hindi"))
    }

    // ── off is a wish, not an absence ───────────────────────────────────────────

    @Test
    fun `off turns text tracks off instead of doing nothing`() {
        // The Settings row stores nothing for "Off", so null IS the off signal — and the
        // literal is honoured too, because this function does not assume which caller
        // spelled it which way.
        assertEquals(SubtitleTrackDecision.TurnOff, SubtitleTrackPolicy.decide(dualSubtitles, null))
        assertEquals(SubtitleTrackDecision.TurnOff, SubtitleTrackPolicy.decide(dualSubtitles, "Off"))
        assertEquals(SubtitleTrackDecision.TurnOff, SubtitleTrackPolicy.decide(dualSubtitles, "off"))
        assertEquals(SubtitleTrackDecision.TurnOff, SubtitleTrackPolicy.decide(dualSubtitles, "   "))
        // Off with no tracks is still off: the file simply has nothing for it to act on.
        assertEquals(SubtitleTrackDecision.TurnOff, SubtitleTrackPolicy.decide(emptyList(), null))
    }
}
