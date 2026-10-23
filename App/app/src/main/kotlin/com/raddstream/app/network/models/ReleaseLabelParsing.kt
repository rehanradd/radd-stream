package com.raddstream.app.network.models

import java.math.BigDecimal
import java.math.RoundingMode

/*
 * ─────────────────────────────────────────────────────────────────────────────
 *  AXIS 1 — PRINT QUALITY (how good the picture/sound actually is)
 * ─────────────────────────────────────────────────────────────────────────────
 * WHY THIS EXISTS AT ALL: the v1 API serves a release as free TEXT
 * (`release_title`, `quality`, `codec`, `size`, `season`, `episode`, `languages`) and
 * nothing structured. The v2 contract has all of it as real columns
 * (`cat_releases.resolution`, `source_tag`, `hdr`, `quality_score`, `coverage_type`, …)
 * but they are only written by the projector, and no v2 endpoint is served yet — so today
 * the app must derive them locally to rank prints at all.
 *
 * THIS IS A PORT, NOT AN OPINION. Every rule, pattern and weight below mirrors
 * `Fast_Fetch/release_descriptor.py` (the single source of truth), including the
 * explicit-column-first precedence and the cam-family cap, and
 * `catalog_v2._release_coverage()` / `_flags_of()`. The golden-vector test
 * `ReleaseLabelParsingTest` asserts the Kotlin output against vectors GENERATED FROM the
 * Python function over real ledger labels, so the port cannot silently drift.
 *
 * WHEN THE BACKEND SERVES `/api/v2` PRINTS, DELETE THIS FILE — the server's own numbers
 * are authoritative and a client re-deriving them is a second, divergent parser
 * (see docs/HANDOFF_appnet.md).
 *
 * NOT PORTED, on purpose: `title_stub` (`_clean_fragment`) — nothing in the app displays
 * it (the UI shows `posts.title`), and it is the only part of the descriptor with no
 * downstream contract. Everything that feeds ranking IS ported.
 */

/** How one print relates to the episode tree (`release_descriptor._detect_scope` output). */
enum class PrintScope(val wire: String) {
    MOVIE("movie"),
    EPISODE("episode"),
    EPISODE_RANGE("episode_range"),
    SEASON_PACK("season_pack"),
    MULTI_SEASON("multi_season"),
    MINISERIES("miniseries"),
    UNKNOWN("unknown");

    companion object {
        fun fromWire(raw: String?): PrintScope =
            values().firstOrNull { it.wire == raw?.trim()?.lowercase() } ?: UNKNOWN
    }
}

/**
 * The structured print of one release. Immutable, and every field has a server
 * counterpart in `cat_releases` — no invented keys.
 * `qualityScore` is on the 0..1000 PRINT scale and is never comparable with a link score.
 */
data class PrintDescriptor(
    val resolution: Resolution,
    val qualityLabel: String,
    val sourceTag: SourceTag,
    val codec: Codec,
    val bitDepth: Int,
    val hdr: List<HdrFormat>,
    val container: Container,
    val edition: Edition,
    val version: Int,
    val isPack: Boolean,
    val episodeRange: String,
    val season: Int,
    val episode: Int,
    val scope: PrintScope,
    val sizeBytes: Long,
    val sizePerEpisodeBytes: Long,
    val audioLanguages: List<String>,
    val audioCodecs: List<String>,
    val channelLayout: String,
    val dualAudio: Boolean,
    val subtitlesAvailable: Boolean,
    val subtitlesExternal: Boolean,
    val subtitlesHardcoded: Boolean,
    val subtitleLangs: List<String>,
    val watermarked: Boolean,
    val officialPrint: Boolean,
    val qualityScore: Int,
    val coverageType: CoverageType,
    val coverageSeason: Int,
    val episodeCountCovered: Int,
    val flags: List<PrintFlag>,
) {
    /** True when this print can stand alone for one episode without an offset. */
    val isPerEpisodeFile: Boolean
        get() = coverageType == CoverageType.SINGLE_EPISODE || coverageType == CoverageType.EPISODE_RANGE
}

object ReleaseLabelParsing {

    // ── text normalisation (`_tidy`, `_squash`, `_compact`, `_mask`) ────────────────

    /** Unicode dash/space variants folded by `_tidy`. Escapes, not literals, on purpose. */
    private val DASHES: List<Pair<String, String>> = listOf(
        "\u2010" to "-", "\u2011" to "-", "\u2012" to "-", "\u2013" to "-",
        "\u2014" to "-", "\u2015" to "-", "\u2212" to "-", "\u00ad" to "-",
        "\u00a0" to " ", "\u200b" to "",
    )

    internal fun tidy(value: String?): String {
        val text = value.orEmpty().take(4000)
        var out = text
        for ((src, dst) in DASHES) out = out.replace(src, dst)
        return WS_RE.replace(out, " ").trim()
    }

    internal fun squash(value: String?): String = tidy(value).lowercase()

    internal fun compact(value: String?): String = NON_ALNUM_RE.replace(squash(value), "")

    private fun mask(text: String, spans: List<IntRange>): String {
        val out = StringBuilder(text)
        // Applied in order like the Python list assignment; spans never overlap in practice.
        for (span in spans) {
            val start = span.first.coerceAtLeast(0)
            val end = (span.last + 1).coerceAtMost(out.length)
            if (end > start) out.replace(start, end, " ".repeat(end - start))
        }
        return out.toString()
    }

    // ── tables, verbatim from release_descriptor.py ─────────────────────────────────

    private const val RESOLUTION_UNKNOWN_WEIGHT = 50
    private const val CAM_FAMILY_CEILING = 250
    private val CAM_FAMILY = setOf("cam", "telesync", "telecine")
    private val OFFICIAL_SOURCE_TAGS = setOf("bluray", "uhd_bluray", "web_dl", "webrip", "hdtv", "dvdrip")
    private val QUALITY_LABELS = mapOf(
        "2160p" to "4K UHD", "1080p" to "Full HD", "720p" to "HD", "480p" to "SD",
        "480p_or_lower" to "SD",
    )
    private val WATERMARK_MARKERS = listOf(
        "watermark", "watermarked", "hdhub4u wm", "x265 webdl wm", "webdl wm",
        "i60x", "etlb", "etleb", "psa",
    )

    /** `LANGUAGE_ALIASES`. */
    private val LANGUAGE_ALIASES: Map<String, String> = mapOf(
        "hindi" to "Hindi", "hin" to "Hindi", "english" to "English", "eng" to "English",
        "tamil" to "Tamil", "tam" to "Tamil", "telugu" to "Telugu", "tel" to "Telugu",
        "telegu" to "Telugu", "kannada" to "Kannada", "kan" to "Kannada",
        "malayalam" to "Malayalam", "mal" to "Malayalam", "mallu" to "Malayalam",
        "punjabi" to "Punjabi", "pun" to "Punjabi", "marathi" to "Marathi",
        "bengali" to "Bengali", "ben" to "Bengali", "bangla" to "Bengali",
        "bhojpuri" to "Bhojpuri", "bhojp" to "Bhojpuri", "korean" to "Korean", "kor" to "Korean",
        "japanese" to "Japanese", "jap" to "Japanese", "chinese" to "Chinese", "mandarin" to "Chinese",
    )

    private val AUDIO_CODEC_PATTERNS: List<Pair<String, Regex>> = listOf(
        "ddp" to Regex("""\bddp\b|\bddplus\b|\bdd\+\b"""),
        "dts-hd" to Regex("""\bdts[\s\-\.]*hd\b"""),
        "truehd" to Regex("""\btrue[\s\-]?hd\b"""),
        "eac3" to Regex("""\beac\s*3\b"""),
        "ac3" to Regex("""\bac\s*3\b"""),
        "atmos" to Regex("""\batmos\b"""),
        "dts" to Regex("""\bdts\b|\bhdts\b"""),
        "aac" to Regex("""\baac\b"""),
        "flac" to Regex("""\bflac\b"""),
        "opus" to Regex("""\bopus\b"""),
        "mp2" to Regex("""\bmp\s*2\b"""),
        "dd" to Regex("""\bdd\b"""),
    )

    private val SUBTITLE_EXTERNAL_PATTERNS: List<Pair<Regex, List<String>>> = listOf(
        Regex("""\be[\s\-]?subs?\b""") to listOf("English"),
        Regex("""\beng(?:lish)?[\s\-\.]*subs?\b""") to listOf("English"),
        Regex("""\bsubtitles?\b|\bsub\b""") to emptyList(),
        Regex("""\bmulti[\s\-]?subs?\b""") to emptyList(),
    )
    private val SUBTITLE_HARDCODED_PATTERNS = listOf(
        Regex("""\bhard[\s\-]?subs?\b|\bh[\s\-]?subs?\b|\bhardcoded[\s\-]?subs?\b"""),
        Regex("""\bburn(?:ed|ing)?[\s\-]?subs?\b"""),
        Regex("""\bon[\s\-]?screen[\s\-]?subs?\b"""),
    )

    private val EDITION_PATTERNS: List<Pair<String, Regex>> = listOf(
        "director_cut" to Regex("directorscut|directorcut"),
        "extended" to Regex("extendedcut|extendededition|extended"),
        "imax" to Regex("imaxedition|imax"),
        "unrated" to Regex("unrated"),
        "remastered" to Regex("remastered|remaster"),
        "restored" to Regex("restored|4krestoration"),
        "uncut" to Regex("uncut"),
        "fan_edit" to Regex("fanedit"),
        "theatrical" to Regex("theatricalcut|theatrical|originalcut"),
    )

    private val PACK_PATTERNS = listOf(
        Regex("""\bbatch(?:es)?\b"""), Regex("""\bcomplet(?:e|ed)\b"""),
        Regex("""\ball episodes?\b"""), Regex("""\bfull movies?\b"""),
        Regex("""\bzip\b"""), Regex("""\bpack\b"""), Regex("""\bmulti[\s\-]?eps?\b"""),
    )
    private val MULTI_SEASON_PATTERNS = listOf(
        Regex("""\ball seasons\b"""), Regex("""\bseasons?\s*\d+\s*-\s*\d+\b"""),
        Regex("""\bdual\s*seasons?\b"""), Regex("""\bcollection\b"""),
    )
    private val MINISERIES_RE = Regex("""\bmini[\s\-]?series\b""")
    private val SERIES_WORD_RE = Regex("""\b(?:web[\s\-]?series|series|season|saga)\b""")
    private val EPISODIC_HINTS_RE =
        Regex("""\b(?:grand\s+)?premieres?\b|\bfinale\b|\bweeklies\b|\blive show\b""")

    private val RESOLUTION_PATTERNS: List<Pair<String, Regex>> = listOf(
        "2160p" to Regex("""\b(?:2160p?|uhd|4k)\b"""),
        "1080p" to Regex("""\b(?:1080p?|fhd|full\s?hd)\b"""),
        "720p" to Regex("""\b720p?\b"""),
        "480p" to Regex("""\b480p?\b"""),
        "480p_or_lower" to Regex("""\b(?:360p|240p|144p|480p_or_lower)\b"""),
    )
    private val SOURCE_PATTERNS: List<Pair<String, Regex>> = listOf(
        "bluray" to Regex("""\bblu[\s\-]?ray\b|\bbdrip\b|\bdemux\b|\bdvd\s?9\b"""),
        "web_dl" to Regex("""\bweb[\s\-]?dl\b|\bwebdl\b|\bweb[\s\-]?download\b"""),
        "webrip" to Regex("""\bweb[\s\-]?rip\b|\bwebrip\b|\bnfweb\b|\bamzn[\s\-]?web\b|\bdsny[\s\-]?web\b"""),
        "hdtv" to Regex("""\bhd\s?tv\b|\bhdtv\b|\bdvb[\s\-]?rip\b|\bdtv\b"""),
        "dvdrip" to Regex("""\bdvd[\s\-]?rip\b|\bdvdrip\b|\bhdrip\b|\bhddvd\b|\bvhsrip\b"""),
        "ppv" to Regex("""\bppv\b|\bpay[\s\-]?per[\s\-]?view\b"""),
        "telesync" to Regex("""\btelesync\b|\btsrip\b|\bhdts\b|\bts\b"""),
        "telecine" to Regex("""\btelecine\b|\btc\b|\bscr\b|\bscreener\b"""),
        "cam" to Regex("""\bhq[\s\-]?cam\b|\bcam[\s\-]?rip\b|\bcam\b|\bmdf\b|\bcamera\b"""),
    )
    private val CODEC_PATTERNS: List<Pair<String, Regex>> = listOf(
        "h265" to Regex("""\bx[\s\-\.]*265\b|\bh[\s\-\.]*265\b|\bhevc\b|\b265\b"""),
        "h264" to Regex("""\bx[\s\-\.]*264\b|\bh[\s\-\.]*264\b|\bavc\b|\b264\b"""),
        "av1" to Regex("""\bav1\b|\bav01\b"""),
        "xvid" to Regex("""\bxvid\b"""),
        "mpeg2" to Regex("""\bmpeg[\s\-]?2\b|\bmpeg\b|\bmpgv\b|\bdvdvideo\b"""),
    )
    private val CONTAINER_PATTERNS: List<Pair<String, Regex>> = listOf(
        "mkv" to Regex("""\.mkv\b|\bmkv\b"""),
        "mp4" to Regex("""\.mp4\b|\bmp4\b"""),
        "avi" to Regex("""\.avi\b|\bavi\b"""),
        "mov" to Regex("""\.mov\b|\bmov\b"""),
        "ts" to Regex("""\.ts\b"""),
        "m4a" to Regex("""\.m4a\b|\bm4a\b"""),
    )

    private val HDR10_PLUS_RE = Regex("""\bhdr[\s.\-]*10[\s.\-]*\+|\bhdr\s*\+\s*10\b|\bhdr\s?plus\b""")
    private val BIT_DEPTH_RE = Regex("""\b(12|10|8)\s?[\s\-\.]?bits?\b""")
    private val VERSION_RE = Regex("""\bv(\d{1,3})\b""")
    private val TOKEN_RE = Regex("""\b[a-z]{2,12}\b""")
    private val WS_RE = Regex("""\s+""")
    private val NON_ALNUM_RE = Regex("""[^a-z0-9]+""")
    private val FIRST_DIGITS_RE = Regex("""\d+""")

    private val RANGE_PATTERNS = listOf(
        Regex("""\bs\d{1,3}e(\d{1,3})\s*(?:-|to|thru|through)\s*(?:s\d{1,3}e?|e)?(\d{1,3})\b"""),
        Regex("""\b(?:ep(?:isode)?s?|e)\s*[\(\[\{]?\s*(\d{1,3})\s*(?:-|to|thru|through)\s*[\)\]\}]?\s*(?:e?\.?\s*)(\d{1,3})\s*[\)\]\}]?"""),
        Regex("""[\(\[\{]\s*(\d{1,3})\s*(?:-|to|thru|through)\s*(\d{1,3})\s*[\)\]\}]"""),
    )
    private val SEASON_PATTERNS = listOf(
        Regex("""^(?:s\s*)?(\d{1,3})\b"""),
        Regex("""\bseason\s*(\d{1,3})\b"""),
        Regex("""\bs(\d{1,3})(?=e(?:p|\d))"""),
        Regex("""\bs(\d{1,3})\b"""),
    )
    private val EPISODE_PATTERNS = listOf(
        Regex("""^(?:e\s*)?(\d{1,3})\b"""),
        Regex("""\bs\d{1,3}e(\d{1,3})\b"""),
        Regex("""\bep(?:isode)?\s*\.?\s*(\d{1,3})\b"""),
    )

    private val UNITS: Map<String, Long> = mapOf("kb" to 1024L, "mb" to 1024L * 1024, "gb" to 1024L * 1024 * 1024, "tb" to 1024L * 1024 * 1024 * 1024)
    private val SIZE_RE = Regex(
        """(\d+(?:\.\d+)?)\s?(kb|mb|gb|tb)\b(\s*/\s*(?:e|ep|eps|episode|episodes?)\b|\s+per\s+(?:ep|episode|eps)\b)?""",
        RegexOption.IGNORE_CASE,
    )

    // ── primitives ─────────────────────────────────────────────────────────────────

    private fun number(pattern: Regex, text: String): Int =
        pattern.find(text)?.groupValues?.getOrNull(1)?.toIntOrNull() ?: 0

    private fun firstOf(table: List<Pair<String, Regex>>, text: String): String {
        for ((name, pattern) in table) if (pattern.containsMatchIn(text)) return name
        return "unknown"
    }

    /** `resolution_rank()`: an unrecognised rung is the unknown rung (50), never a guess. */
    fun resolutionRank(wire: String?): Int =
        Resolution.fromWire(wire).takeIf { it != Resolution.UNKNOWN }?.weight ?: RESOLUTION_UNKNOWN_WEIGHT

    /** `source_rank()`: every tag earns its weight; unknown (and unranked hdtc) earns 60. */
    fun sourceRank(wire: String?): Int {
        val tag = SourceTag.fromWire(wire)
        return if (tag == SourceTag.UNKNOWN || tag == SourceTag.HDT_C) SOURCE_TAG_WEIGHTS_UNKNOWN
        else tag.weight
    }

    private const val SOURCE_TAG_WEIGHTS_UNKNOWN = 60

    // ── detectors ──────────────────────────────────────────────────────────────────

    private fun detectResolution(quality: String, title: String): String {
        for (field in listOf(quality, title)) {
            val found = RESOLUTION_PATTERNS.filter { it.second.containsMatchIn(field) }.map { it.first }
            if (found.isNotEmpty()) return found.maxByOrNull { resolutionRank(it) }!!
        }
        return "unknown"
    }

    private fun detectCodec(codec: String, quality: String, title: String): String {
        for (field in listOf(codec, quality, title)) {
            val found = firstOf(CODEC_PATTERNS, field)
            if (found != "unknown") return found
        }
        return "unknown"
    }

    private fun detectHdr(text: String): List<String> {
        val out = mutableListOf<String>()
        if (Regex("""\bdolby\s?vision\b|\bdv\b|\bdovi\b""").containsMatchIn(text)) out.add("dolby_vision")
        val plusSpans = HDR10_PLUS_RE.findAll(text).map { it.range.first until it.range.last + 1 }.toList()
        if (plusSpans.isNotEmpty()) out.add("hdr10_plus")
        val rest = mask(text, plusSpans)
        if (Regex("""\bhdr\s?10\b|\bhdr\b""").containsMatchIn(rest)) out.add("hdr10")
        if (Regex("""\bhlg\b""").containsMatchIn(rest)) out.add("hlg")
        return out
    }

    private fun detectLanguages(vararg fields: String): List<String> {
        val found = mutableListOf<String>()
        for (field in fields) {
            for (match in TOKEN_RE.findAll(field)) {
                val name = LANGUAGE_ALIASES[match.value]
                if (name != null && name !in found) found.add(name)
            }
        }
        return found
    }

    private fun detectAudio(text: String, extraLanguages: String): AudioInfo {
        val languages = detectLanguages(extraLanguages, text)
        val codecs = mutableListOf<String>()
        var rest = text
        for ((name, pattern) in AUDIO_CODEC_PATTERNS) {
            val match = pattern.find(rest)
            if (match != null) {
                codecs.add(name)
                rest = mask(rest, listOf(match.range.first until match.range.last + 1))
            }
        }
        val layout = when {
            Regex("""\b[57]\s?\.\s?1\b""").containsMatchIn(text) -> "5.1"
            Regex("""\b2\s?\.\s?0\b|\bstereo\b""").containsMatchIn(text) -> "2.0"
            else -> "unknown"
        }
        val dual = Regex("""\bdual[\s\-]?audi[oa]?\b|\bmulti[\s\-]?audi[oa]\b""").containsMatchIn(text)
        return AudioInfo(languages, layout, codecs, dual || languages.size >= 2)
    }

    private fun detectSubtitles(text: String): SubtitleInfo {
        val langs = mutableListOf<String>()
        var external = false
        for ((pattern, names) in SUBTITLE_EXTERNAL_PATTERNS) {
            if (pattern.containsMatchIn(text)) {
                external = true
                for (name in names) if (name !in langs) langs.add(name)
            }
        }
        val hardcoded = SUBTITLE_HARDCODED_PATTERNS.any { it.containsMatchIn(text) }
        return SubtitleInfo(external || hardcoded || langs.isNotEmpty(), hardcoded, external, langs)
    }

    private fun detectEpisodeRange(text: String): String {
        for (pattern in RANGE_PATTERNS) {
            for (match in pattern.findAll(text)) {
                val lo = match.groupValues[1].toIntOrNull() ?: continue
                val hi = match.groupValues[2].toIntOrNull() ?: continue
                if (lo in 1..999 && hi in 1..999) return "${minOf(lo, hi)}-${maxOf(lo, hi)}"
            }
        }
        return ""
    }

    /** `_detect_index()`: the explicit column first, then three label patterns. */
    private fun detectIndex(column: String, text: String, patterns: List<Regex>, limit: Int): Int {
        val fields = listOf(column, text, text, text)
        val count = minOf(fields.size, patterns.size)
        for (i in 0 until count) {
            val value = number(patterns[i], fields[i])
            if (value in 1..limit) return value
        }
        return 0
    }

    private fun detectScope(text: String, season: Int, episode: Int, isPack: Boolean, hasRange: Boolean): String {
        val seriesNamed = SERIES_WORD_RE.containsMatchIn(text)
        if (MULTI_SEASON_PATTERNS.any { it.containsMatchIn(text) }) return "multi_season"
        if (MINISERIES_RE.containsMatchIn(text)) return "miniseries"
        if (hasRange || episode != 0 || season != 0 || (isPack && seriesNamed)) {
            return when {
                hasRange -> "episode_range"
                episode != 0 -> "episode"
                else -> "season_pack"
            }
        }
        return if (seriesNamed || EPISODIC_HINTS_RE.containsMatchIn(text)) "unknown" else "movie"
    }

    private fun detectSize(size: String, title: String): Pair<Long, Long> {
        for (field in listOf(size, title)) {
            for (match in SIZE_RE.findAll(field)) {
                val amount = match.groupValues[1].toDecimalOrNull() ?: continue
                val unit = UNITS[match.groupValues[2].lowercase()] ?: continue
                val perEpisode = !match.groupValues[3].isNullOrBlank()
                val bytes = amount.multiply(BigDecimal(unit)).setScale(0, RoundingMode.HALF_EVEN).toLong()
                if (bytes > 0) return if (perEpisode) 0L to bytes else bytes to 0L
            }
        }
        return 0L to 0L
    }

    private fun String.toDecimalOrNull(): BigDecimal? = try {
        BigDecimal(this)
    } catch (e: NumberFormatException) {
        null
    }

    private fun isOfficialPrint(sourceTag: String, watermarked: Boolean, edition: String, resolution: String): Boolean {
        if (watermarked || edition == "fan_edit") return false
        return sourceTag in OFFICIAL_SOURCE_TAGS || (sourceTag == "unknown" && resolution != "unknown")
    }

    private fun qualityLabelOf(resolution: String, sourceTag: String, quality: String, title: String): String {
        if (sourceTag in CAM_FAMILY || sourceTag == "ppv") return "CAM"
        QUALITY_LABELS[resolution]?.let { return it }
        return if (Regex("""\bhd\b|fhd|full\s?hd""").containsMatchIn("$quality $title")) "HD" else ""
    }

    /** `combined_quality_score()` — the documented total order, clamped 0..1000. */
    fun combinedQualityScore(
        resolution: String,
        sourceTag: String,
        hdr: List<String>,
        bitDepth: Int,
        codec: String,
        officialPrint: Boolean,
        subtitles: SubtitleInfo,
        audio: AudioInfo,
        edition: String,
        watermarked: Boolean,
    ): Int {
        var score = resolutionRank(resolution) + sourceRank(sourceTag)
        if (hdr.any { it == "dolby_vision" || it == "hdr10" || it == "hdr10_plus" } &&
            (resolution == "1080p" || resolution == "2160p")
        ) score += 60
        score += when (bitDepth) {
            12 -> 30
            10 -> 20
            else -> 0
        }
        if (codec == "h265" || codec == "av1") score += 30
        if (officialPrint) score += 40
        score += when {
            subtitles.external -> 20
            subtitles.hardcoded -> 5
            else -> 0
        }
        if (audio.dualAudio) score += 25
        if (audio.channelLayout == "5.1") score += 15
        if (edition in setOf("director_cut", "extended", "remastered", "restored")) score += 15
        if (watermarked) score -= 60
        if (sourceTag in CAM_FAMILY) score = minOf(score, CAM_FAMILY_CEILING)
        return score.coerceIn(0, 1000)
    }

    // ── coverage (`catalog_v2._release_coverage`) ───────────────────────────────────

    /** `_hint_int()`: scrapers write "S01", "Season 2", "1", "Batch", "" into one column. */
    internal fun hintInt(value: String?): Int {
        if (value.isNullOrBlank()) return 0
        return FIRST_DIGITS_RE.find(value)?.value?.toIntOrNull() ?: 0
    }

    /** `_parse_range()`: (lo, hi); "3-1" and "7" both collapse to a single number. */
    internal fun parseRange(text: String?): Pair<Int, Int> {
        val m = Regex("""(\d+)\s*-\s*(\d+)""").find(text.orEmpty()) ?: return 0 to 0
        val lo = m.groupValues[1].toIntOrNull() ?: return 0 to 0
        val hi = m.groupValues[2].toIntOrNull() ?: return 0 to 0
        if (hi < lo || hi - lo > 500) return lo to lo
        return lo to hi
    }

    /**
     * `_release_coverage(desc, season_hint, work_family)` → (coverage_type, season_number,
     * episode_count_covered). `seasonHint` is the RAW `releases.season` column, because a
     * label that names no season may still have one in the column ("Batch", "S02").
     */
    internal fun releaseCoverage(
        scope: String,
        season: Int,
        episode: Int,
        episodeRange: String,
        isPack: Boolean,
        seasonHint: String?,
        family: String,
    ): Triple<CoverageType, Int, Int> {
        val effectiveSeason = if (season != 0) season else hintInt(seasonHint)
        val (lo, hi) = parseRange(episodeRange)
        return when {
            family == "movie" && episode == 0 && season == 0 -> Triple(CoverageType.WHOLE_WORK, 0, 0)
            episode != 0 && lo == 0 -> Triple(CoverageType.SINGLE_EPISODE, effectiveSeason, 1)
            lo != 0 && hi > lo -> Triple(CoverageType.EPISODE_RANGE, effectiveSeason, hi - lo + 1)
            isPack || scope in setOf("season_pack", "miniseries", "multi_season") ->
                Triple(CoverageType.SEASON_PACK, effectiveSeason, 0)
            scope == "episode" -> Triple(CoverageType.SINGLE_EPISODE, effectiveSeason, if (episode != 0) episode else 1)
            effectiveSeason != 0 && episode == 0 -> Triple(CoverageType.SEASON_PACK, effectiveSeason, 0)
            else -> Triple(CoverageType.WHOLE_WORK, effectiveSeason, 0)
        }
    }

    // ── the entry points ────────────────────────────────────────────────────────────

    /**
     * `release_descriptor.describe()` minus `title_stub`, then `catalog_v2`'s coverage pass.
     * `workType` is the PARENT work's type when known (from `posts.content_type` +
     * `is_animated`); when it is null the family is inferred from this print alone, which
     * only matters for a print that names a season — see [familyOf].
     */
    fun describe(
        releaseTitle: String?,
        quality: String? = null,
        codec: String? = null,
        size: String? = null,
        season: String? = null,
        episode: String? = null,
        languages: String? = null,
        workType: WorkType? = null,
    ): PrintDescriptor {
        val qText = squash(quality)
        val cText = squash(codec)
        val tText = squash(releaseTitle)
        val langText = squash(languages)
        val sText = squash(season)
        val eText = squash(episode)
        val allText = listOf(qText, cText, tText, langText).filter { it.isNotEmpty() }.joinToString(" ")

        val resolution = detectResolution(qText, tText)
        var sourceTag = firstOf(SOURCE_PATTERNS, allText)
        if (sourceTag == "bluray" && resolution == "2160p") sourceTag = "uhd_bluray"
        val detectedCodec = detectCodec(cText, qText, tText)
        val bitDepth = number(BIT_DEPTH_RE, allText)
        val container = firstOf(CONTAINER_PATTERNS, allText)
        val edition = firstOf(EDITION_PATTERNS, compact(allText))
        val version = number(VERSION_RE, allText)
        val hdr = detectHdr(allText)
        val audio = detectAudio(allText, langText)
        val subtitles = detectSubtitles(allText)
        val episodeRange = detectEpisodeRange(allText)
        val hasRange = episodeRange.isNotEmpty()
        val seasonNo = detectIndex(sText, allText, SEASON_PATTERNS, 99)
        // A range or a pack yields 0: that file covers many episodes, not one.
        val episodeNo = if (hasRange) 0 else detectIndex(eText, allText, EPISODE_PATTERNS, 999)
        val isPack = hasRange || PACK_PATTERNS.any { it.containsMatchIn(allText) }
        val scope = detectScope(allText, seasonNo, episodeNo, isPack, hasRange)
        val (sizeBytes, perEpisode) = detectSize(squash(size), tText)
        // Only the print's own published text: a watermark is something the label says.
        // `source_site` is not on the wire any more, and never was a watermark signal.
        val labelBlob = listOfNotNull(releaseTitle, quality, codec, size)
            .joinToString(" ") { squash(it) }
        val watermarked = WATERMARK_MARKERS.any { labelBlob.contains(it) }
        val official = isOfficialPrint(sourceTag, watermarked, edition, resolution)
        val score = combinedQualityScore(
            resolution, sourceTag, hdr, bitDepth, detectedCodec, official, subtitles, audio, edition,
            watermarked,
        )

        val family = workType?.let { if (it.isServerSeriesType) "series" else "movie" } ?: familyOf(
            scope, seasonNo, episodeNo, sText, eText,
        )
        val (coverage, coverageSeason, epCount) = releaseCoverage(
            scope = scope,
            season = seasonNo,
            episode = episodeNo,
            episodeRange = episodeRange,
            isPack = isPack,
            seasonHint = season,
            family = family,
        )

        val flags = buildList {
            if (watermarked) add(PrintFlag.WATERMARKED)
            if (!official) add(PrintFlag.UNOFFICIAL)
            if (isPack) add(PrintFlag.PACK)
            if (edition in setOf("director_cut", "extended", "unrated", "remastered", "restored")) {
                add(PrintFlag.ALTERNATE_EDITION)
            }
        }

        return PrintDescriptor(
            resolution = Resolution.fromWire(resolution),
            qualityLabel = qualityLabelOf(resolution, sourceTag, qText, tText),
            sourceTag = SourceTag.fromWire(sourceTag),
            codec = Codec.fromWire(detectedCodec),
            bitDepth = bitDepth,
            hdr = hdr.map { HdrFormat.fromWire(it) },
            container = Container.fromWire(container),
            edition = Edition.fromWire(edition),
            version = version,
            isPack = isPack,
            episodeRange = episodeRange,
            season = seasonNo,
            episode = episodeNo,
            scope = PrintScope.fromWire(scope),
            sizeBytes = sizeBytes,
            sizePerEpisodeBytes = perEpisode,
            audioLanguages = audio.languages,
            audioCodecs = audio.codecs,
            channelLayout = audio.channelLayout,
            dualAudio = audio.dualAudio,
            subtitlesAvailable = subtitles.available,
            subtitlesExternal = subtitles.external,
            subtitlesHardcoded = subtitles.hardcoded,
            subtitleLangs = subtitles.langs,
            watermarked = watermarked,
            officialPrint = official,
            qualityScore = score,
            coverageType = coverage,
            coverageSeason = coverageSeason,
            episodeCountCovered = epCount,
            flags = flags,
        )
    }

    /**
     * Family inference for the standalone (no parent context) call. A print that names a
     * season/episode, or whose scope is episodic, is treated as series so the movie
     * short-circuit in [releaseCoverage] cannot erase it; a print that names neither is
     * identical on both paths (`whole_work`), so this inference never changes a movie.
     */
    private fun familyOf(scope: String, season: Int, episode: Int, seasonColumn: String, episodeColumn: String): String =
        if (scope in setOf("episode", "episode_range", "season_pack", "multi_season", "miniseries", "unknown") ||
            season != 0 || episode != 0 || hintInt(seasonColumn) != 0 || hintInt(episodeColumn) != 0
        ) "series" else "movie"

    /** The v1 release row, with the parent work type applied. */
    fun describe(release: ReleaseDetail, workType: WorkType? = null): PrintDescriptor = describe(
        releaseTitle = release.releaseTitle,
        quality = release.quality,
        codec = release.codec,
        size = release.size,
        season = release.season,
        episode = release.episode,
        languages = release.languages,
        workType = workType,
    )

    /** `describe()` of the empty print: what the server's `_fallback_print()` returns. */
    fun fallback(): PrintDescriptor = describe(releaseTitle = null)

    data class AudioInfo(
        val languages: List<String>,
        val channelLayout: String,
        val codecs: List<String>,
        val dualAudio: Boolean,
    )

    data class SubtitleInfo(
        val available: Boolean,
        val hardcoded: Boolean,
        val external: Boolean,
        val langs: List<String>,
    )

    // ── the narrow accessors Models.kt exposes as derived fields ────────────────────
    //
    // They take the already-parsed [PrintDescriptor] rather than the row, so a UI list that
    // reads season, episode and resolution does not run the regex tables three times.

    /** `cat_releases.season_number`: 0 means the server never said, so this is null. */
    fun seasonOf(print: PrintDescriptor): Int? = print.coverageSeason.takeIf { it != 0 }

    /** `cat_releases.episode_number`: null for a pack/range/whole-work file (which is honest). */
    fun episodeOf(print: PrintDescriptor): Int? = print.episode.takeIf { it != 0 }

    /** The rung NAME the server would put in `cat_releases.resolution`, or null. */
    fun resolutionOf(print: PrintDescriptor): String? =
        print.resolution.takeIf { it != Resolution.UNKNOWN }?.wire

    /**
     * `_detect_size(size, release_title)` — the `size` column first, then the label, so a
     * release whose scraper left `size` empty still reports the bytes named in its title.
     * A `/E` figure is PER episode and the total stays unknown (0), exactly as the server
     * records it in `cat_releases.size_per_episode_bytes`.
     */
    fun sizeBytesOf(print: PrintDescriptor): Long? = print.sizeBytes.takeIf { it > 0L }
}
