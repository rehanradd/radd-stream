package com.raddstream.app.player.subtitle

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SubtitleParsersTest {

    // ── SRT ──────────────────────────────────────────────────────────────────────

    @Test
    fun srtParsesCuesWithIndexTimingAndText() {
        val file = SubtitleParser.parseSrt(
            """
            1
            00:00:01,000 --> 00:00:03,500
            Hello there

            2
            00:00:04,000 --> 00:00:06,000
            General Kenobi

            """.trimIndent(),
        )
        assertEquals(2, file.cues.size)
        assertEquals(SubtitleCue(1_000, 3_500, "Hello there"), file.cues[0])
        assertEquals(SubtitleCue(4_000, 6_000, "General Kenobi"), file.cues[1])
    }

    @Test
    fun srtAcceptsMissingIndexAndCrlfAndMultilineText() {
        val body = "00:00:01,000 --> 00:00:02,000\r\nFirst line\r\nSecond line\r\n\r\n"
        val file = SubtitleParser.parseSrt(body)
        assertEquals(1, file.cues.size)
        assertEquals("First line\nSecond line", file.cues[0].text)
    }

    @Test
    fun srtStripsInlineTagsAndDropsEmptyTextCues() {
        val body = """
            1
            00:00:01,000 --> 00:00:02,000
            <i>Italic</i> and {\an8}positioned

            2
            00:00:03,000 --> 00:00:04,000


            3
            00:00:05,000 --> 00:00:06,000
            <font color="red">Red</font>
        """.trimIndent()
        val file = SubtitleParser.parseSrt(body)
        assertEquals(2, file.cues.size)
        assertEquals("Italic and positioned", file.cues[0].text)
        assertEquals("Red", file.cues[1].text)
    }

    @Test
    fun srtSortsOutOfOrderCuesByStartTime() {
        val body = """
            1
            00:00:10,000 --> 00:00:11,000
            Later

            2
            00:00:01,000 --> 00:00:02,000
            Earlier
        """.trimIndent()
        val file = SubtitleParser.parseSrt(body)
        assertEquals(listOf("Earlier", "Later"), file.cues.map { it.text })
    }

    // ── WebVTT ───────────────────────────────────────────────────────────────────

    @Test
    fun vttSkipsHeaderCueSettingsAndNoteBlocks() {
        val body = """
            WEBVTT
            Kind: captions

            NOTE this is a comment

            1
            00:00:01.000 --> 00:00:02.500 align:start position:10%
            <v Speaker>Hello</v>

            00:03.000 --> 00:04.000
            Short form timing
        """.trimIndent()
        val file = SubtitleParser.parseWebVtt(body)
        assertEquals(2, file.cues.size)
        assertEquals(SubtitleCue(1_000, 2_500, "Hello"), file.cues[0])
        assertEquals(SubtitleCue(3_000, 4_000, "Short form timing"), file.cues[1])
    }

    @Test
    fun vttWithoutHeaderStillParses() {
        val body = "00:00:01.000 --> 00:00:02.000\nBare cue"
        val file = SubtitleParser.parseWebVtt(body)
        assertEquals(1, file.cues.size)
        assertEquals("Bare cue", file.cues[0].text)
    }

    @Test
    fun unknownFormatSniffsTheWebVttHeader() {
        val vtt = SubtitleParser.parse("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nTip\n", SubtitleFormat.Unknown)
        assertEquals(1, vtt.cues.size)
        val srt = SubtitleParser.parse("1\n00:00:01,000 --> 00:00:02,000\nTip\n", SubtitleFormat.Unknown)
        assertEquals(1, srt.cues.size)
    }

    // ── empty and malformed input ────────────────────────────────────────────────

    @Test
    fun emptyAndWhitespaceInputsProduceNoCues() {
        for (blank in listOf("", "   ", "\n\n\n", "\r\n\r\n")) {
            assertTrue(SubtitleParser.parse(blank, SubtitleFormat.SubRip).cues.isEmpty())
            assertTrue(SubtitleParser.parse(blank, SubtitleFormat.WebVtt).cues.isEmpty())
        }
    }

    @Test
    fun malformedTimingLinesAreSkippedWithoutThrowing() {
        val body = """
            1
            not-a-timestamp --> 00:00:02,000
            Broken start

            2
            00:00:01,000 --> junk
            Broken end

            3
            00:00:02,000 --> 00:00:01,000
            Ends before it starts

            4
            no arrow here
            Nothing to time

            5
            00:00:05,000 --> 00:00:06,000
            Survives
        """.trimIndent()
        val file = SubtitleParser.parseSrt(body)
        assertEquals(1, file.cues.size)
        assertEquals("Survives", file.cues[0].text)
    }

    @Test
    fun timestampsRejectBadShapesAndAcceptCommaOrDot() {
        assertNull(SubtitleParser.parseTimestamp(""))
        assertNull(SubtitleParser.parseTimestamp("abc"))
        assertNull(SubtitleParser.parseTimestamp("1:xx:03.000"))
        assertNull(SubtitleParser.parseTimestamp("1::3"))
        assertNull(SubtitleParser.parseTimestamp("00:00:01:02"))
        assertEquals(62_345L, SubtitleParser.parseTimestamp("00:01:02,345"))
        assertEquals(62_345L, SubtitleParser.parseTimestamp("00:01:02.345"))
        assertEquals(3_500L, SubtitleParser.parseTimestamp("00:03.500"))
        // A colon-less token is not a time: the parser wants MM:SS or HH:MM:SS.
        assertNull(SubtitleParser.parseTimestamp("05"))
        assertNull(SubtitleParser.parseTimestamp("1.5"))
    }

    @Test
    fun timingLineRequiresExactlyOneArrow() {
        assertNull(SubtitleParser.parseTimingLine("00:00:01,000 --> 00:00:02,000 --> 00:00:03,000"))
        assertNull(SubtitleParser.parseTimingLine("00:00:01,000"))
        assertEquals(1_000L to 2_500L, SubtitleParser.parseTimingLine("00:00:01,000 --> 00:00:02.500 align:start"))
    }

    // ── very large files ─────────────────────────────────────────────────────────

    @Test
    fun veryLargeSrtParsesEveryCueInStartOrder() {
        val cueCount = 20_000
        val builder = StringBuilder(cueCount * 48)
        for (i in 1..cueCount) {
            val start = i * 1_000L
            builder.append(i).append('\n')
                .append(stamp(start)).append(" --> ").append(stamp(start + 900)).append('\n')
                .append("Line ").append(i).append("\n\n")
        }
        val file = SubtitleParser.parseSrt(builder.toString())
        assertEquals(cueCount, file.cues.size)
        assertEquals(1_000L, file.cues.first().startMs)
        assertEquals(cueCount * 1_000L, file.cues.last().startMs)
        assertTrue(file.cues.zipWithNext().all { (a, b) -> a.startMs <= b.startMs })
    }

    @Test
    fun veryLargeVttParsesEveryCue() {
        val cueCount = 10_000
        val builder = StringBuilder("WEBVTT\n\n")
        for (i in 1..cueCount) {
            val start = i * 500L
            builder.append(stamp(start)).append(" --> ").append(stamp(start + 400)).append('\n')
                .append("Caption ").append(i).append("\n\n")
        }
        val file = SubtitleParser.parseWebVtt(builder.toString())
        assertEquals(cueCount, file.cues.size)
        assertEquals("Caption 1", file.cues.first().text)
        assertEquals("Caption $cueCount", file.cues.last().text)
    }

    // ── lookup behaviour that rides on the parsed file ───────────────────────────

    @Test
    fun activeCuesApplyPositiveDelayAsLaterSubtitles() {
        val file = SubtitleFile(listOf(SubtitleCue(1_000, 2_000, "on time")))
        assertEquals(1, file.activeCues(1_500).size)
        assertTrue(file.activeCues(1_500, delayMs = 1_000).isEmpty())
        assertEquals(1, file.activeCues(2_500, delayMs = 1_000).size)
    }

    @Test
    fun formatDetectionReadsExtensionOrMime() {
        assertEquals(SubtitleFormat.SubRip, SubtitleFormat.fromFileNameOrMime("movie.en.srt"))
        assertEquals(SubtitleFormat.WebVtt, SubtitleFormat.fromFileNameOrMime("MOVIE.VTT"))
        assertEquals(SubtitleFormat.SubRip, SubtitleFormat.fromFileNameOrMime("text/x-subrip"))
        assertEquals(SubtitleFormat.WebVtt, SubtitleFormat.fromFileNameOrMime("text/vtt"))
        assertEquals(SubtitleFormat.Unknown, SubtitleFormat.fromFileNameOrMime("movie.ass"))
        assertEquals(SubtitleFormat.Unknown, SubtitleFormat.fromFileNameOrMime(null))
    }

    private fun stamp(ms: Long): String {
        val h = ms / 3_600_000
        val m = (ms / 60_000) % 60
        val s = (ms / 1_000) % 60
        val milli = ms % 1_000
        return "%02d:%02d:%02d,%03d".format(h, m, s, milli)
    }
}
