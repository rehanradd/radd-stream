package com.raddstream.app.viewmodel

import com.raddstream.app.network.models.CoverageType
import com.raddstream.app.network.models.LinkClassification
import com.raddstream.app.network.models.Playability
import com.raddstream.app.network.models.ReleaseDetail
import com.raddstream.app.network.models.SourceDetail
import com.raddstream.app.player.NOT_PLAYABLE_HERE
import com.raddstream.app.player.PLAYABLE_HERE

/**
 * Honest, presentation-ready domain model derived from the backend's *unstructured*
 * v1 release rows.
 *
 * WHY THIS EXISTS
 * ---------------
 * `GET /api/v1/posts/{id}` returns releases ordered only by `id ASC` (viewer.py:1942)
 * with free-text `season` / `episode` / `release_title` / `quality` / `languages`
 * columns, and it does NOT expose the structured `cat_releases` projection that
 * `Fast_Fetch/API_V2.md` §2.3/§3 describes. The Android `ReleaseDetail` model
 * (network/models/Models.kt — owned by another agent) currently maps
 * `season_number` / `episode_number` / `episode_title` / `resolution` / `audio`,
 * none of which the v1 response actually sends (see App/AGENTS.md §6), so they are
 * `null`. This file reconstructs the useful structure client-side by parsing the
 * descriptive text fields that *do* arrive, so the Detail UI can be honest today
 * and gets even better once the network agent maps the real columns (see
 * docs/HANDOFF_appui.md request #1). Everything here is pure Kotlin: no Android,
 * no coroutines — it is unit-tested on the JVM.
 *
 * NEVER fabricate: if a field cannot be parsed it stays `null`/`UNKNOWN` and the UI
 * degrades (shows "—" or hides the badge) rather than inventing a value.
 */

/** Case-insensitive whole-word match, mirroring `\bword\b` (ripgrep-safe on plain text). */
internal fun wordMatch(text: String, word: String): Boolean =
    Regex("""(?i)\b${Regex.escape(word)}\b""").containsMatchIn(text)

enum class V1Resolution(val label: String, val tier: Int) {
    R2160("4K", 4),
    R1080("1080p", 3),
    R720("720p", 2),
    R480("480p", 1),
    UNKNOWN("HD", 0);

    companion object {
        fun fromText(text: String?): V1Resolution? {
            val t = text?.lowercase() ?: return null
            return when {
                "2160" in t || "4k" in t || "uhd" in t -> R2160
                "1080" in t || "fhd" in t || "full hd" in t -> R1080
                "720" in t || wordMatch(t, "hd") -> R720
                "480" in t || "576" in t || wordMatch(t, "sd") -> R480
                else -> null
            }
        }
    }
}

/**
 * Where the print came from. `official` prints are genuine distribution releases;
 * `CAM`-class tags are bootlegs. Higher tier is a better source.
 */
enum class V1SourceTag(val label: String, val official: Boolean, val tier: Int, val cam: Boolean) {
    UHD_BLURAY("UHD BluRay", true, 12, false),
    BLURAY("BluRay", true, 11, false),
    WEB_DL("WEB-DL", true, 10, false),
    WEBRIP("WEBRip", true, 9, false),
    HDTV("HDTV", true, 8, false),
    DVD("DVD", true, 7, false),
    VHSRip("VHSRip", true, 6, false),
    TELECINE("Telecine", false, 2, true),
    CAM("CAM", false, 1, true),
    UNKNOWN("Release", false, 4, false);

    companion object {
        fun fromText(text: String?): V1SourceTag? {
            val t = text?.lowercase() ?: return null
            return when {
                "uhd bluray" in t || "4k bluray" in t || "2160 bluray" in t -> UHD_BLURAY
                wordMatch(t, "bluray") || wordMatch(t, "bdrip") || wordMatch(t, "brrip") -> BLURAY
                "web-dl" in t || "webdl" in t -> WEB_DL
                "webrip" in t || "web-rip" in t -> WEBRIP
                "hdtv" in t -> HDTV
                wordMatch(t, "dvdrip") || wordMatch(t, "dvd") -> DVD
                "vhs" in t -> VHSRip
                "telecine" in t || wordMatch(t, "tc") -> TELECINE
                "telesync" in t || "hdts" in t || "camrip" in t || wordMatch(t, "cam") -> CAM
                else -> null
            }
        }
    }
}

enum class V1HdrFormat(val label: String) {
    DOLBY_VISION("Dolby Vision"),
    HDR10_PLUS("HDR10+"),
    HDR10("HDR10"),
    HLG("HLG");

    companion object {
        fun fromText(text: String?): List<V1HdrFormat> {
            val t = text?.lowercase() ?: return emptyList()
            val out = mutableListOf<V1HdrFormat>()
            if ("dolby vision" in t || "dovi" in t || wordMatch(t, "dv")) out.add(DOLBY_VISION)
            if ("hdr10+" in t) out.add(HDR10_PLUS)
            if ("hdr10" in t || "hdr" in t) out.add(HDR10)
            if ("hlg" in t) out.add(HLG)
            // HDR10+ subsumes plain HDR10 — keep only the most specific.
            return if (out.contains(HDR10_PLUS)) out.filter { it != HDR10 } else out.distinct()
        }
    }
}

enum class V1Codec(val label: String) {
    H264("H.264"),
    H265("H.265"),
    AV1("AV1");

    companion object {
        fun fromText(text: String?): V1Codec? {
            val t = text?.lowercase() ?: return null
            return when {
                wordMatch(t, "av1") -> AV1
                "h265" in t || "hevc" in t || "x265" in t -> H265
                "h264" in t || "x264" in t || "avc" in t -> H264
                else -> null
            }
        }
    }
}

enum class V1Edition(val label: String) {
    DIRECTORS_CUT("Director's Cut"),
    EXTENDED("Extended"),
    UNRATED("Unrated"),
    IMAX("IMAX"),
    REMASTERED("Remastered"),
    THEATRICAL("Theatrical");

    companion object {
        fun fromText(text: String?): V1Edition? {
            val t = text?.lowercase() ?: return null
            return when {
                "director's cut" in t || "directors cut" in t -> DIRECTORS_CUT
                wordMatch(t, "extended") -> EXTENDED
                wordMatch(t, "unrated") -> UNRATED
                wordMatch(t, "imax") -> IMAX
                "remaster" in t || "restored" in t || "uncut" in t -> REMASTERED
                else -> null
            }
        }
    }
}


/**
 * Link health as far as the client can *honestly* know from v1.
 * v1 ships a scrape-time `status` string and boolean-ish
 * `is_temporary` / `is_resumable` flags. There is no measured latency/speed yet,
 * so we must NOT claim "⚡ Fast" (the old DetailScreen did). Real measured health
 * comes from v2 `cat_link_evidence` (see HANDOFF request #4).
 */
enum class LinkHealth { ACTIVE, DEAD, UNKNOWN }

/**
 * One link of one print, as the detail screen holds it.
 *
 * There is no `name` field any more, on purpose: the row used to print the hoster's own name
 * (`sourceName` / `service`), and that is exactly the surface the public edge stopped serving.
 * What a link IS comes from [kind]/[label]/[playability], which our server writes in the
 * viewer's language, and what it can DO comes from [playableHere]/[keepable].
 */
data class RankedLink(
    /** The opaque handle of ours this link is reachable by — its only identity. */
    val streamId: String,
    /** `link_id` when the server publishes one; never used for addressing. */
    val linkId: Int?,
    val health: LinkHealth,
    val ephemeral: Boolean,
    val resumable: Boolean,
    /** OUR OWN `/api/v1/stream?id=<handle>` redirector. Null when there is no address of ours. */
    val playUrl: String?,
    /** Our server's own words: `Fast direct` | `Standard`. Never a hoster or site name. */
    val label: String?,
    /** `direct | resolve | download | external`, copied from the served verdict. */
    val kind: String?,
    /** Derived from the served verdict only — no hostname lookup exists in this app. */
    val playability: Playability,
    val score: Int,
) {
    /** Presentable by our one player: our handle, our address, and the server says it streams. */
    val playableHere: Boolean
        get() = streamId.isNotBlank() && !playUrl.isNullOrBlank() &&
            playability.isDirectlyPlayable && health != LinkHealth.DEAD

    /** Addressable at all — the minimum a keep (download) request needs. */
    val keepable: Boolean get() = streamId.isNotBlank() && !playUrl.isNullOrBlank()

    /** The row's own sentence: behaviour words, never a name of somebody else. */
    fun displayLabel(): String = listOfNotNull(
        label?.takeIf { it.isNotBlank() },
        if (playableHere) PLAYABLE_HERE else NOT_PLAYABLE_HERE,
    ).distinct().joinToString(" · ").ifBlank { "Link" }
}

/**
 * One print of one coverage scope (API_V2.md §3). Carries BOTH quality axes the
 * brief demands: the print-quality badge (resolution + source + HDR + edition) and
 * the link health / ephemerality of its underlying links.
 */
data class RankedPrint(
    val releaseId: Int,
    val rawTitle: String?,
    val resolution: V1Resolution,
    val sourceTag: V1SourceTag,
    val hdr: List<V1HdrFormat>,
    val codec: V1Codec?,
    val edition: V1Edition?,
    val languages: List<String>,
    val sizeBytes: Long?,
    val coverage: CoverageType,
    val season: Int?,
    val episodeFrom: Int?,
    val episodeTo: Int?,
    val links: List<RankedLink>,
) {
    val isCam: Boolean get() = sourceTag.cam
    val isOfficialPrint: Boolean get() = sourceTag.official
    val hasHdr: Boolean get() = hdr.isNotEmpty()

    /** Number of working links on this print — the "print-first" count. */
    val availableLinks: Int get() = links.count { it.health != LinkHealth.DEAD }

    /** The one link this print is presented by: the server already ranked them. */
    val bestLink: RankedLink?
        get() = links.filter { it.playableHere }.maxByOrNull { it.score }
            ?: links.maxByOrNull { it.score }

    /** Whether the detail screen's Play button can do anything at all. */
    val playableHere: Boolean get() = bestLink?.playableHere == true

    /** What the row says beside the badge: behaviour words, never somebody else's name. */
    val bestOptionLabel: String? get() = bestLink?.displayLabel()

    /**
     * Best-first ordering score mirroring API_V2.md §3: a CAM can never outrank a
     * distribution print, then resolution, then source tag, then HDR, then health.
     */
    val rankKey: Int
        get() {
            val base = resolution.tier * 1000 +
                sourceTag.tier * 100 +
                (if (hasHdr) 40 else 0) +
                (if (codec == V1Codec.H265 || codec == V1Codec.AV1) 10 else 0) +
                availableLinks.coerceAtMost(9)
            return if (isCam) base else base + 1_000_000
        }

    /** Human label for the print-quality badge, e.g. "4K · DV · BluRay · Extended". */
    val qualityLabel: String
        get() {
            val parts = mutableListOf<String>()
            if (resolution != V1Resolution.UNKNOWN) parts.add(resolution.label)
            if (hasHdr) parts.add(hdr.first().label.replace("Dolby Vision", "DV"))
            if (sourceTag != V1SourceTag.UNKNOWN) parts.add(sourceTag.label)
            edition?.let { parts.add(it.label) }
            return if (parts.isEmpty()) rawTitle?.takeIf { it.isNotBlank() } ?: "RankedPrint" else parts.joinToString(" · ")
        }

    /** A compact secondary line (codec · size · languages) — only real values. */
    val detailLine: String
        get() {
            val bits = mutableListOf<String>()
            codec?.let { bits.add(it.label) }
            sizeBytes?.let { bits.add(formatBytes(it)) }
            if (languages.isNotEmpty()) bits.add(languages.joinToString("/"))
            return bits.joinToString(" · ")
        }

    val isPacked: Boolean get() = coverage == CoverageType.SEASON_PACK || coverage == CoverageType.WHOLE_WORK
}

private fun formatBytes(bytes: Long): String = when {
    bytes >= 1_000_000_000_000 -> "%.1f TB".format(bytes / 1_000_000_000_000.0)
    bytes >= 1_000_000_000 -> "%.1f GB".format(bytes / 1_000_000_000.0)
    bytes >= 1_000_000 -> "%.0f MB".format(bytes / 1_000_000.0)
    bytes >= 1_000 -> "%.0f KB".format(bytes / 1_000.0)
    else -> "$bytes B"
}

/** A single episode with its ranked prints. Packed seasons attach their pack here. */
data class EpisodeGroup(
    val season: Int,
    val numberWithinSeason: Int,
    val absoluteNumber: Int,
    val title: String?,
    val prints: List<RankedPrint>,
) {
    val bestPrint: RankedPrint? get() = prints.maxByOrNull { it.rankKey }
    val onlyPacked: Boolean
        get() = prints.isNotEmpty() && prints.all { it.isPacked }
}

data class SeasonGroup(
    val number: Int,
    val episodes: List<EpisodeGroup>,
    /** Prints that are one file for the whole season ("Complete"/Batch). */
    val packedPrints: List<RankedPrint>,
) {
    val episodeCount: Int get() = episodes.size
    val hasAnyPackedOnly: Boolean get() = episodes.isNotEmpty() && episodes.all { it.onlyPacked }
}

/** Everything the Detail screen can show honestly about a title's releases. */
data class ReleaseLayout(
    val isSeriesLike: Boolean,
    val seasons: List<SeasonGroup>,
    /** Movie / whole-work prints (empty for series with per-episode files). */
    val workPrints: List<RankedPrint>,
    /** Aggregate capability chips derived from real prints. */
    val capabilities: List<String>,
    val officialPrintCount: Int,
    val camPrintCount: Int,
    val totalPrints: Int,
) {
    val hasAnyPrint: Boolean get() = totalPrints > 0
}

object ReleaseParser {

    private val SEASON_RE = Regex("""(?i)\b(?:s|season[\s.]*)(\d{1,3})\b""")
    private val EPISODE_RE = Regex("""(?i)\b(?:e|episode|ep)[\s.]*(\d{1,4})\b""")
    private val EP_RANGE_RE = Regex("""(?i)ep(?:isode)?\s*\(?\s*(\d{1,3})\s*[-–]\s*(\d{1,3})""")
    private val S_EX_EY_RE = Regex("""(?i)\bs(\d{1,3})[\s._-]*e(\d{1,3})\b""")
    private val PACK_RE = Regex("""(?i)(complete|full)\s+season|season\s+\d+\s+(complete|full)|\bbatch\b|\ball\s+(episodes|ep)\b|\(\s*\d{1,3}\s*ep""")

    /** Parse bytes from a size string like "2.4GB", "1.5 GB", "800MB". */
    fun parseSizeBytes(size: String?): Long? {
        if (size.isNullOrBlank()) return null
        val m = Regex("""(?i)(\d+(?:[.,]\d+)?)\s*(tb|gb|mb|kb|b)\b""").find(size) ?: return null
        val value = m.groupValues[1].replace(',', '.').toDoubleOrNull() ?: return null
        val mult = when (m.groupValues[2].lowercase()) {
            "tb" -> 1_000_000_000_000.0
            "gb" -> 1_000_000_000.0
            "mb" -> 1_000_000.0
            "kb" -> 1_000.0
            else -> 1.0
        }
        return (value * mult).toLong().takeIf { it > 0 }
    }

    fun parseLanguages(text: String?): List<String> {
        if (text.isNullOrBlank()) return emptyList()
        val lower = text.lowercase()
        val known = listOf(
            "Hindi", "English", "Tamil", "Telugu", "Malayalam", "Kannada", "Bengali",
            "Punjabi", "Marathi", "Gujarati", "Japanese", "Korean", "Chinese", "Spanish",
            "French", "German", "Italian", "Russian", "Turkish", "Portuguese",
        )
        val found = known.filter { it.lowercase() in lower }
        return if (found.isEmpty() && ("dual audio" in lower || "multi audio" in lower)) {
            listOf("Multi-audio")
        } else {
            found.distinct()
        }
    }

    fun build(contentType: String?, releases: List<ReleaseDetail>): ReleaseLayout {
        val prints = releases.map { toPrint(it) }
        val isSeries = looksLikeSeries(contentType, prints)
        val officialCount = prints.count { it.isOfficialPrint }
        val camCount = prints.count { it.isCam }
        val capabilities = deriveCapabilities(prints)

        if (!isSeries) {
            return ReleaseLayout(
                isSeriesLike = false,
                seasons = emptyList(),
                workPrints = prints.sortedByDescending { it.rankKey },
                capabilities = capabilities,
                officialPrintCount = officialCount,
                camPrintCount = camCount,
                totalPrints = prints.size,
            )
        }

        val bySeason = prints.groupBy { it.season ?: 1 }
        val seasons = bySeason.toSortedMap().map { (seasonNum, seasonPrints) ->
            val packed = seasonPrints.filter { it.isPacked }
            val perEpisode = seasonPrints.filterNot { it.isPacked }
            val epNumbers = sortedSetOf<Int>()
            perEpisode.forEach { p ->
                val from = p.episodeFrom ?: return@forEach
                val to = (p.episodeTo ?: from).coerceAtLeast(from).coerceAtMost(from + 500)
                var n = from
                while (n <= to) { epNumbers.add(n); n++ }
            }
            val episodes = epNumbers.map { num ->
                val covering = perEpisode.filter { p ->
                    val from = p.episodeFrom ?: return@filter false
                    val to = (p.episodeTo ?: from).coerceAtLeast(from)
                    num in from..to
                }
                EpisodeGroup(
                    season = seasonNum,
                    numberWithinSeason = num,
                    absoluteNumber = num,
                    title = covering.firstNotNullOfOrNull { it.rawTitle?.takeIf(String::isNotBlank) },
                    prints = (covering + packed).sortedByDescending { it.rankKey },
                )
            }
            SeasonGroup(number = seasonNum, episodes = episodes, packedPrints = packed)
        }
        // Recompute show-wide absolute numbering across seasons.
        var running = 0
        val numbered = seasons.map { sg ->
            sg.copy(episodes = sg.episodes.map { e -> e.copy(absoluteNumber = ++running) })
        }

        return ReleaseLayout(
            isSeriesLike = true,
            seasons = numbered,
            workPrints = emptyList(),
            capabilities = capabilities,
            officialPrintCount = officialCount,
            camPrintCount = camCount,
            totalPrints = prints.size,
        )
    }

    private fun looksLikeSeries(contentType: String?, prints: List<RankedPrint>): Boolean {
        val ct = contentType?.lowercase().orEmpty()
        if ("series" in ct || "season" in ct) return true
        return prints.any { it.season != null || it.episodeFrom != null || it.isPacked }
    }

    private fun deriveCapabilities(prints: List<RankedPrint>): List<String> {
        val out = LinkedHashSet<String>()
        if (prints.any { it.resolution == V1Resolution.R2160 }) out.add("4K")
        if (prints.any { it.hasHdr }) out.add("HDR")
        if (prints.any { it.resolution == V1Resolution.R1080 }) out.add("1080p")
        if (prints.any { it.isOfficialPrint }) out.add("Official prints")
        if (prints.any { p -> p.links.any { it.resumable } }) out.add("Resumable")
        if (prints.any { p -> p.links.any { it.playableHere } }) out.add("Streamable")
        if (prints.any { p -> p.links.any { it.keepable } }) out.add("Downloadable")
        val langs = prints.flatMap { it.languages }.distinct().filterNot { it == "Multi-audio" }
        if (langs.isNotEmpty()) out.add(langs.joinToString("/") + " audio")
        return out.toList()
    }

    private fun toPrint(release: ReleaseDetail): RankedPrint {
        val blob = listOfNotNull(release.releaseTitle, release.quality, release.resolution, release.audio, release.codec)
            .joinToString(" ")
        val resolution = V1Resolution.fromText(release.resolution) ?: V1Resolution.fromText(blob) ?: V1Resolution.UNKNOWN
        val sourceTag = V1SourceTag.fromText(release.quality) ?: V1SourceTag.fromText(blob) ?: V1SourceTag.UNKNOWN
        val hdr = V1HdrFormat.fromText(blob)
        val codec = V1Codec.fromText(release.codec) ?: V1Codec.fromText(blob)
        val edition = V1Edition.fromText(blob)
        val languages = parseLanguages(release.audio)
        val scope = parseScope(blob, release.seasonNumber, release.episodeNumber)

        return RankedPrint(
            releaseId = release.id,
            rawTitle = release.releaseTitle?.takeIf { it.isNotBlank() } ?: release.quality,
            resolution = resolution,
            sourceTag = sourceTag,
            hdr = hdr,
            codec = codec,
            edition = edition,
            languages = languages,
            sizeBytes = parseSizeBytes(release.size),
            coverage = scope.coverage,
            season = scope.season,
            episodeFrom = scope.epFrom,
            episodeTo = scope.epTo,
            links = release.sources.map { toLink(it) },
        )
    }

    private data class Scope(val season: Int?, val epFrom: Int?, val epTo: Int?, val coverage: CoverageType)

    private fun parseScope(blob: String, seasonNumber: Int?, episodeNumber: Int?): Scope {
        val isPack = PACK_RE.containsMatchIn(blob)
        S_EX_EY_RE.find(blob)?.let { m ->
            val s = m.groupValues[1].toIntOrNull()
            val e = m.groupValues[2].toIntOrNull()
            return Scope(s, e, e, if (isPack) CoverageType.SEASON_PACK else CoverageType.SINGLE_EPISODE)
        }
        EP_RANGE_RE.find(blob)?.let { m ->
            val a = m.groupValues[1].toIntOrNull()
            val b = m.groupValues[2].toIntOrNull()
            val season = seasonNumber ?: SEASON_RE.find(blob)?.groupValues?.getOrNull(1)?.toIntOrNull()
            return Scope(season, a, b, CoverageType.EPISODE_RANGE)
        }
        val season = seasonNumber ?: SEASON_RE.find(blob)?.groupValues?.getOrNull(1)?.toIntOrNull()
        val episode = episodeNumber ?: EPISODE_RE.find(blob)?.groupValues?.getOrNull(1)?.toIntOrNull()
        val coverage = when {
            isPack && season != null -> CoverageType.SEASON_PACK
            episode != null -> CoverageType.SINGLE_EPISODE
            season != null -> CoverageType.SEASON_PACK
            else -> CoverageType.UNKNOWN
        }
        return Scope(season, episode, episode, coverage)
    }

    private fun toLink(source: SourceDetail): RankedLink {
        val assessment = source.classification
        return RankedLink(
            streamId = source.streamId,
            linkId = source.linkId,
            health = toHealth(source.status ?: source.state),
            ephemeral = source.isEphemeral,
            resumable = source.isResumableLink,
            playUrl = source.bestUrl,
            label = source.label,
            kind = source.kind,
            playability = assessment.playability,
            score = LinkClassification.rankOf(source),
        )
    }

    private fun toHealth(status: String?): LinkHealth = when (status?.lowercase()?.trim()) {
        null, "" -> LinkHealth.UNKNOWN
        "active", "ok", "alive", "working", "live" -> LinkHealth.ACTIVE
        "dead", "down", "broken", "offline", "fail", "failed", "unavailable" -> LinkHealth.DEAD
        else -> LinkHealth.UNKNOWN
    }
}
