package com.raddstream.app.player.subtitle

/**
 * Minimal, honest external-subtitle loader for the player's custom overlay path
 * (PLAYER_SPEC.md §2.3): SRT and WebVTT are parsed here so the app can offer full MX-style
 * delay/size/position control for *external* files. Embedded tracks and exotic formats
 * (.ass/.ssa/.ttml) go through Media3's native `SubtitleConfiguration` instead
 * (`DefaultSubtitleParserFactory` in 1.3.1 parses SSA/ASS, VTT, SRT, TX3G, PGS, DVB, TTML —
 * verified) — for those, cue-level delay is not available in 1.3.1 and the UI says so.
 *
 * Pure Kotlin: no android.* imports; `SubtitleParserTest` covers it on the JVM.
 */

data class SubtitleCue(val startMs: Long, val endMs: Long, val text: String)

class SubtitleFile(val cues: List<SubtitleCue>) {

    /**
     * Cues visible at [positionMs] with [delayMs] applied. MX convention: positive delay
     * shows subtitles LATER (we look at an earlier virtual position).
     */
    fun activeCues(positionMs: Long, delayMs: Long = 0): List<SubtitleCue> {
        val virtual = positionMs - delayMs
        return cues.filter { it.startMs <= virtual && virtual < it.endMs }
    }
}

sealed class SubtitleFormat(val mime: String) {
    object SubRip : SubtitleFormat("text/x-subrip")
    object WebVtt : SubtitleFormat("text/vtt")
    object Unknown : SubtitleFormat("application/octet-stream")

    companion object {
        fun fromFileNameOrMime(nameOrMime: String?): SubtitleFormat {
            val lower = nameOrMime?.lowercase().orEmpty()
            return when {
                lower.endsWith(".srt") || lower.contains("subrip") || lower.contains("srt") -> SubRip
                lower.endsWith(".vtt") || lower.contains("vtt") -> WebVtt
                else -> Unknown
            }
        }
    }
}

object SubtitleParser {

    fun parse(content: String, format: SubtitleFormat): SubtitleFile = when (format) {
        SubtitleFormat.SubRip -> parseSrt(content)
        SubtitleFormat.WebVtt -> parseWebVtt(content)
        SubtitleFormat.Unknown -> if (content.trimStart().startsWith("WEBVTT")) {
            parseWebVtt(content)
        } else {
            parseSrt(content)
        }
    }

    /** RFC-style block parsing: index line (optional), `HH:MM:SS,mmm --> ...`, text lines. */
    fun parseSrt(content: String): SubtitleFile {
        val cues = ArrayList<SubtitleCue>()
        val blocks = content.replace("\r\n", "\n").replace("\r", "\n").split("\n\n")
        for (raw in blocks) {
            val block = raw.trim()
            if (block.isEmpty()) continue
            val lines = block.split("\n").toMutableList()
            val arrowIndex = lines.indexOfFirst { it.contains("-->") }
            if (arrowIndex < 0) continue
            val timing = parseTimingLine(lines[arrowIndex]) ?: continue
            val textLines = lines.drop(arrowIndex + 1)
                .map { stripTags(it) }
                .filter { it.isNotBlank() }
            val text = textLines.joinToString("\n").trim()
            if (text.isNotEmpty()) cues.add(SubtitleCue(timing.first, timing.second, text))
        }
        return SubtitleFile(cues.sortedBy { it.startMs })
    }

    /** WebVTT: skip up to the blank line after the WEBVTT header, then cue blocks. */
    fun parseWebVtt(content: String): SubtitleFile {
        val normalized = content.replace("\r\n", "\n").replace("\r", "\n")
        val body = if (normalized.trimStart().startsWith("WEBVTT")) {
            normalized.substringAfter("\n\n", normalized)
        } else {
            normalized
        }
        val cues = ArrayList<SubtitleCue>()
        for (raw in body.split("\n\n")) {
            val lines = raw.trim().split("\n")
            val arrowIndex = lines.indexOfFirst { it.contains("-->") }
            if (arrowIndex < 0) continue
            val timing = parseTimingLine(lines[arrowIndex]) ?: continue
            val text = lines.drop(arrowIndex + 1)
                .map { stripTags(it) }
                .filter { it.isNotBlank() && !it.startsWith("NOTE") }
                .joinToString("\n")
            if (text.isNotEmpty()) cues.add(SubtitleCue(timing.first, timing.second, text))
        }
        return SubtitleFile(cues.sortedBy { it.startMs })
    }

    /**
     * `00:01:02,345 --> 00:01:05,000` (SRT) or `00:01:02.345 --> 00:01:05.000 align:start` (VTT).
     * Returns (startMs, endMs) or null when malformed — a broken line must never throw.
     */
    internal fun parseTimingLine(line: String): Pair<Long, Long>? {
        val parts = line.split("-->")
        if (parts.size != 2) return null
        val start = parseTimestamp(parts[0].trim()) ?: return null
        // VTT may carry cue settings after the end timestamp — cut at first whitespace.
        val endToken = parts[1].trim().split(Regex("\\s+")).firstOrNull().orEmpty()
        val end = parseTimestamp(endToken) ?: return null
        if (end <= start) return null
        return start to end
    }

    internal fun parseTimestamp(token: String): Long? {
        // Accept H:MM:SS,mmm / HH:MM:SS.mmm / MM:SS.mmm
        val cleaned = token.trim().replace(',', '.')
        val groups = cleaned.split(":")
        if (groups.isEmpty()) return null
        return try {
            val secondsParts = groups.last().split(".")
            val secs = secondsParts[0].toLong()
            val millis = if (secondsParts.size > 1) {
                secondsParts[1].padEnd(3, '0').take(3).toLong()
            } else 0L
            var totalMillis = secs * 1000 + millis
            when (groups.size) {
                2 -> totalMillis += groups[0].toLong() * 60_000
                3 -> totalMillis += groups[0].toLong() * 3_600_000 + groups[1].toLong() * 60_000
                else -> return null
            }
            if (totalMillis < 0) null else totalMillis
        } catch (_: NumberFormatException) {
            null
        }
    }

    /** Strip VTT/ASS inline tags: `<c.xxx>`, `<v Name>`, `</b>`, `{\an8}`, `<00:00:01.000>`. */
    internal fun stripTags(line: String): String = line
        .replace(Regex("""\{[^}]*\}"""), "")
        .replace(Regex("""<[^>]*>"""), "")
        .trim()
}
