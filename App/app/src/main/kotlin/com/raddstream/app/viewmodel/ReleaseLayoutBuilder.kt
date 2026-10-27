package com.raddstream.app.viewmodel

import com.raddstream.app.data.UserRegion
import com.raddstream.app.network.models.Codec
import com.raddstream.app.network.models.CoverageType
import com.raddstream.app.network.models.Edition
import com.raddstream.app.network.models.HdrFormat
import com.raddstream.app.network.models.LinkClassification
import com.raddstream.app.network.models.LinkState
import com.raddstream.app.network.models.Playability
import com.raddstream.app.network.models.ReleaseDetail
import com.raddstream.app.network.models.ReleaseLabelParsing
import com.raddstream.app.network.models.Resolution
import com.raddstream.app.network.models.SeasonArtwork
import com.raddstream.app.network.models.SourceDetail
import com.raddstream.app.network.models.SourceTag
import com.raddstream.app.network.models.WorkType
import com.raddstream.app.player.NOT_PLAYABLE_HERE
import com.raddstream.app.player.PLAYABLE_HERE

/*
 * PRESENTATION VIEW STATE — collapses the raw v1 release rows into what the detail screen
 * shows: ranked prints, grouped episodes/seasons, aggregate capability chips.
 *
 * WHY IT LIVES HERE AND NOT IN `network.models`: it is pure view state (`EpisodeGroup`,
 * `SeasonGroup`, ranked rows for the detail UI), not part of the server contract. Everything
 * server-facing — the ladder wire types and the release-label GRAMMAR (resolution/source/
 * hdr/codec/edition/coverage/scope/size/languages) — has exactly one home in
 * `network/models/`, and this file holds none of that grammar.
 *
 * It owns NO grammar. The label parsing lives only in [ReleaseLabelParsing]; every field on a
 * [RankedPrint] is read off the [com.raddstream.app.network.models.PrintDescriptor] the model
 * layer already computes. The presentation helpers here — the enum→string display maps,
 * `qualityLabel`/`detailLine`, byte formatting and the season/episode grouping — are the only
 * things that are app-local.
 *
 * GRAMMAR RULES THE DELETED `viewmodel/ReleaseParser.kt` USED TO OWN, AND WHERE THEY WENT:
 *   V1Resolution.fromText       → Resolution.fromWire + `release_descriptor` patterns  (network/models)
 *   V1SourceTag.fromText        → SourceTag.fromWire + `SOURCE_PATTERNS`               (network/models)
 *   V1HdrFormat.fromText        → HdrFormat.fromWire + `detectHdr`                     (network/models)
 *   V1Codec.fromText            → Codec.fromWire + `detectCodec`                       (network/models)
 *   V1Edition.fromText          → Edition.fromWire + `EDITION_PATTERNS`                (network/models)
 *   LinkHealth (ACTIVE/DEAD/UNKNOWN) → the richer enum LinkState (adds EXPIRED/UNCHECKED)
 *   parseScope                  → `detectScope` + `_release_coverage`                  (network/models)
 *   parseSizeBytes (DECIMAL 1000) → `detectSize` (BINARY 1024, server-faithful)        (network/models)
 *   parseLanguages (synth "Multi-audio") → `detectAudio().languages` + a real `dualAudio`
 *                                          flag; no invented language word             (network/models)
 *   wordMatch / regexes         → gone; the surviving grammar in `network/models` owns them.
 *
 * BEHAVIOUR deltas that are INTENTIONAL (all server-faithful, asserted in the tests):
 *   - size is BINARY (1024) not DECIMAL — `release_descriptor` is binary and `sizeBytes` feeds
 *     the download card; matching the server beats matching the old client guess.
 *   - a bare-word quality ("HD", "576", "sd") no longer fabricates a resolution rung: the
 *     server's own rules only recognise an explicit rung. A bare "HD" survives honestly as the
 *     quality LABEL ("HD") with resolution [Resolution.UNKNOWN]; its RANK and work-level scope
 *     are preserved (see the collapse-parity test).
 *   - no synthetic "Multi-audio" language: dual/multi audio is carried by [dualAudio].
 *   - ranking is the surviving `qualityScore` (0..1000 print scale × 10 + available links) — the
 *     server-faithful print scale replaces the old client tier sum, so a CAM still cannot
 *     outrank any official print.
 */

/** One link of one print, as the detail screen holds it: health and what we can do with it. */
data class RankedLink(
    /** The opaque handle of ours this link is reachable by — its only identity. */
    val streamId: String,
    /** `link_id` when the server publishes one; never used for addressing. */
    val linkId: Int?,
    val health: LinkState,
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
            playability.isDirectlyPlayable && !health.isDead

    /** Addressable at all — the minimum a keep (download) request needs. */
    val keepable: Boolean get() = streamId.isNotBlank() && !playUrl.isNullOrBlank()

    /** The row's own sentence: behaviour words, never a name of somebody else. */
    fun displayLabel(): String = listOfNotNull(
        label?.takeIf { it.isNotBlank() },
        if (playableHere) PLAYABLE_HERE else NOT_PLAYABLE_HERE,
    ).distinct().joinToString(" · ").ifBlank { "Link" }
}

/**
 * One release print as the detail screen holds it. Wraps the [com.raddstream.app.network.models.PrintDescriptor]
 * and adds only the typed getters and the display strings the UI needs. No grammar lives here.
 */
data class RankedPrint(
    val releaseId: Int,
    /** The print's own sentence; [rawTitle] fallback only, never a site or hoster name. */
    val rawTitle: String?,
    /** The surviving server-facing print — the single source of every parsed field. */
    val descriptor: com.raddstream.app.network.models.PrintDescriptor,
    val languages: List<String>,
    val sizeBytes: Long?,
    val coverage: CoverageType,
    val season: Int?,
    val episodeFrom: Int?,
    val episodeTo: Int?,
    val links: List<RankedLink>,
) {
    val resolution: Resolution get() = descriptor.resolution
    val sourceTag: SourceTag get() = descriptor.sourceTag
    val hdr: List<HdrFormat> get() = descriptor.hdr.filterNotNull()
    val codec: Codec? get() = descriptor.codec.takeIf { it != Codec.UNKNOWN }
    val edition: Edition? get() = descriptor.edition.takeIf { it != Edition.UNKNOWN }

    val isCam: Boolean get() = descriptor.sourceTag.camFamily
    val isOfficialPrint: Boolean get() = descriptor.officialPrint
    val hasHdr: Boolean get() = hdr.isNotEmpty()
    val isPacked: Boolean get() = coverage.isPacked
    val dualAudio: Boolean get() = descriptor.dualAudio

    /**
     * True when this print carries a Hindi or Urdu track, or is labelled dual/multi audio.
     * Presentation only: it decides where the row sits in the selector for a
     * [UserRegion.DESI_DUBS] viewer, never what the viewer may play.
     */
    val isDesiDub: Boolean
        get() = dualAudio || languages.any { it.equals("Hindi", ignoreCase = true) || it.equals("Urdu", ignoreCase = true) }

    /** Subtitle facts, read straight off the descriptor so the badge layer adds no grammar. */
    val subtitlesAvailable: Boolean get() = descriptor.subtitlesAvailable
    val subtitlesExternal: Boolean get() = descriptor.subtitlesExternal
    val subtitlesHardcoded: Boolean get() = descriptor.subtitlesHardcoded
    val subtitleLangs: List<String> get() = descriptor.subtitleLangs

    /** The surviving print-quality axis (0..1000); never comparable with a link score. */
    val qualityScore: Int get() = descriptor.qualityScore

    /** Number of working links on this print — the "print-first" count the row leads with. */
    val availableLinks: Int get() = links.count { !it.health.isDead }

    /** The one link this print is presented by: the server already ranked them. */
    val bestLink: RankedLink?
        get() = links.filter { it.playableHere }.maxByOrNull { it.score }
            ?: links.maxByOrNull { it.score }

    /** Whether the detail screen's Play button can do anything at all. */
    val playableHere: Boolean get() = bestLink?.playableHere == true

    /** What the row says beside the badge: behaviour words, never somebody else's name. */
    val bestOptionLabel: String? get() = bestLink?.displayLabel()

    /**
     * The single print score, on the surviving server print scale (0..1000): the print-quality
     * axis ([descriptor]'s `qualityScore`) is already a CAM-safe total order, so a cam can
     * never outrank a distribution print regardless of resolution. The available-link count
     * is a tie-breaker only, so it never crosses onto the print scale.
     */
    val rankKey: Int get() = descriptor.qualityScore * 10 + availableLinks.coerceAtMost(9)

    /** What the detail row leads with: the server's quality rung, else a composed honest label. */
    val qualityLabel: String
        get() {
            descriptor.qualityLabel.takeIf { it.isNotBlank() }?.let { return it }
            val parts = mutableListOf<String>()
            if (resolution != Resolution.UNKNOWN) parts.add(resolution.display())
            hdr.firstOrNull()?.let { parts.add(it.display()) }
            if (sourceTag != SourceTag.UNKNOWN) parts.add(sourceTag.display())
            edition?.let { parts.add(it.display()) }
            return parts.joinToString(" · ").ifBlank { rawTitle?.takeIf { it.isNotBlank() } ?: "Print" }
        }

    /** What the detail row shows second: codec / size / languages, honest parts only. */
    val detailLine: String
        get() {
            val parts = mutableListOf<String>()
            codec?.let { parts.add(it.display()) }
            sizeBytes?.let { parts.add(formatBytes(it)) }
            if (languages.isNotEmpty()) parts.add(languages.joinToString("/"))
            return parts.joinToString(" · ")
        }
}

/** A single episode with its ranked prints. Packed seasons attach their pack here. */
data class EpisodeGroup(
    val season: Int,
    val numberWithinSeason: Int,
    val absoluteNumber: Int,
    val title: String?,
    val prints: List<RankedPrint>,
    /**
     * Wide artwork for this episode, chosen from the work's own backdrop set (see
     * [ReleaseLayoutBuilder]). Null when the catalog carries no usable wide art — the row
     * then paints the branded gradient card rather than repeating the series poster.
     */
    val stillUrl: String? = null,
) {
    val bestPrint: RankedPrint? get() = prints.maxByOrNull { it.rankKey }
    val onlyPacked: Boolean get() = prints.isNotEmpty() && prints.all { it.isPacked }
}

/** One season: its per-episode rows plus any whole-season pack. */
data class SeasonGroup(
    val number: Int,
    val episodes: List<EpisodeGroup>,
    val packedPrints: List<RankedPrint>,
    /**
     * This season's own artwork, distinct from its siblings whenever the catalog carries more
     * than one wide image. Null means the caller should draw the branded fallback.
     */
    val artworkUrl: String? = null,
) {
    val episodeCount: Int get() = episodes.size
    val bestPrint: RankedPrint? get() = (episodes.flatMap { it.prints } + packedPrints).maxByOrNull { it.rankKey }
    val hasAnyPackedOnly: Boolean get() = episodes.isNotEmpty() && episodes.all { it.onlyPacked }
}

/** Everything the detail screen can show honestly about one title's releases. */
data class ReleaseLayout(
    val isSeriesLike: Boolean,
    val seasons: List<SeasonGroup>,
    val workPrints: List<RankedPrint>,
    val capabilities: List<String>,
    val officialPrintCount: Int,
    val camPrintCount: Int,
    val totalPrints: Int,
) {
    val packedSeasons: List<Int> get() = seasons.filter { it.packedPrints.isNotEmpty() }.map { it.number }
    val hasAnyPrint: Boolean get() = totalPrints > 0
    val bestOverallPrint: RankedPrint?
        get() = (workPrints + seasons.flatMap { it.episodes.flatMap { e -> e.prints } } +
            seasons.flatMap { it.packedPrints }).maxByOrNull { it.rankKey }
}

/**
 * Builds the [ReleaseLayout] the detail screen renders. It reads every parsed field off the
 * [com.raddstream.app.network.models.PrintDescriptor] the model layer produces (via
 * [ReleaseDetail]'s `printDescriptor`) and does nothing but rank, group and label.
 */
object ReleaseLayoutBuilder {

    fun build(contentType: String?, releases: List<ReleaseDetail>): ReleaseLayout =
        build(contentType, null, releases, emptyList(), emptyList())

    fun build(
        contentType: String?,
        releases: List<ReleaseDetail>,
        artwork: List<String>,
        seasonArtwork: List<SeasonArtwork> = emptyList(),
        region: String = UserRegion.DEFAULT,
    ): ReleaseLayout = build(contentType, null, releases, artwork, seasonArtwork, region)

    /**
     * [artwork] is the work's wide art pool, best first (backdrops, then poster).
     * [seasonArtwork] is the server's mapped season poster / episode still set, which always
     * wins for the season or episode it names. The pool remains a fallback for databases
     * written before `backfill_tmdb.py` ran: it distributes real work-level images, and it
     * never pretends a work backdrop is an official season poster or an episode frame.
     *
     * [region] is the viewer's regional-dub preference ([UserRegion]); it re-partitions the
     * print lists the detail screen renders but never filters them.
     */
    fun build(
        contentType: String?,
        workType: WorkType?,
        releases: List<ReleaseDetail>,
        artwork: List<String> = emptyList(),
        seasonArtwork: List<SeasonArtwork> = emptyList(),
        region: String = UserRegion.DEFAULT,
    ): ReleaseLayout {
        val pool = artwork.filter { it.isNotBlank() }.distinct()
        val publishedPosters = seasonArtwork
            .asSequence()
            .filter { it.kind == "season_poster" && !it.url.isNullOrBlank() }
            .associate { it.season to it.url!! }
        val publishedStills = seasonArtwork
            .asSequence()
            .filter { it.kind == "episode_still" && !it.url.isNullOrBlank() }
            .associate { (it.season to it.episode) to it.url!! }
        val prints = releases.map { toPrint(it, workType) }
        val isSeries = looksLikeSeries(contentType, prints)
        val officialCount = prints.count { it.isOfficialPrint }
        val camCount = prints.count { it.isCam }
        val capabilities = deriveCapabilities(prints)

        if (!isSeries) {
            return ReleaseLayout(
                isSeriesLike = false,
                seasons = emptyList(),
                workPrints = orderPrints(prints, region),
                capabilities = capabilities,
                officialPrintCount = officialCount,
                camPrintCount = camCount,
                totalPrints = prints.size,
            )
        }

        val bySeason = prints.groupBy { it.season ?: 1 }
        val seasons = bySeason.toSortedMap().entries.mapIndexed { seasonIndex, (seasonNum, seasonPrints) ->
            val packed = seasonPrints.filter { it.isPacked }
            val perEpisode = seasonPrints.filterNot { it.isPacked }
            val epNumbers = sortedSetOf<Int>()
            perEpisode.forEach { p ->
                val from = p.episodeFrom ?: return@forEach
                val to = (p.episodeTo ?: from).coerceAtLeast(from).coerceAtMost(from + 500)
                var n = from
                while (n <= to) { epNumbers.add(n); n++ }
            }
            val episodes = epNumbers.mapIndexed { episodeIndex, num ->
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
                    prints = orderPrints(covering + packed, region),
                    stillUrl = publishedStills[seasonNum to num]
                        ?: stillAt(pool, seasonIndex, episodeIndex),
                )
            }
            SeasonGroup(
                number = seasonNum,
                episodes = episodes,
                packedPrints = orderPrints(packed, region),
                artworkUrl = publishedPosters[seasonNum]
                    ?: artworkAt(pool, seasonIndex),
            )
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

    /**
     * The order the release selector presents one print list in.
     *
     * Quality is the rule: the server's print score decides, and a CAM never outranks an
     * official print. For [UserRegion.DESI_DUBS] the ranked list is then stably
     * re-partitioned so a Hindi/Urdu/dual-audio print leads its own official/CAM class —
     * a Pakistani or Indian viewer should not have to scroll past English originals to
     * find the dub. Stability leaves the quality order untouched inside every class, and
     * language never lifts a CAM above an official print.
     */
    internal fun orderPrints(prints: List<RankedPrint>, region: String): List<RankedPrint> {
        val ranked = prints.sortedByDescending { it.rankKey }
        if (UserRegion.normalize(region) != UserRegion.DESI_DUBS) return ranked
        return ranked.sortedWith(
            compareByDescending<RankedPrint> { it.isOfficialPrint }
                .thenByDescending { it.isDesiDub },
        )
    }

    /**
     * Index into the work's wide-art pool. Seasons take one image each, in order; a pool
     * shorter than the season list wraps, which is still a deliberate choice rather than one
     * repeated poster on every card.
     */
    private fun artworkAt(pool: List<String>, index: Int): String? =
        if (pool.isEmpty()) null else pool[index % pool.size]

    /**
     * Episode stills only exist when the work carries more than one wide image. With a single
     * backdrop every row would show the identical frame, which reads as a broken grid; null
     * lets the row draw the branded gradient with its episode number instead.
     */
    private fun stillAt(pool: List<String>, seasonIndex: Int, episodeIndex: Int): String? =
        if (pool.size < 2) null else pool[(seasonIndex * 3 + episodeIndex) % pool.size]

    private fun looksLikeSeries(contentType: String?, prints: List<RankedPrint>): Boolean {
        val ct = contentType?.lowercase().orEmpty()
        if ("series" in ct || "season" in ct) return true
        // A WHOLE_WORK print is one file for the whole work (a film, or a one-file show) — that
        // is work-level, not a series trigger. Only a dated season, an episode, or a genuine
        // SEASON_PACK points the screen at the season list. (The deleted parser's `isPacked` was
        // SEASON_PACK∪PACK and never fired for a film; WHOLE_WORK would, so it is excluded here.)
        return prints.any {
            it.season != null || it.episodeFrom != null || it.coverage == CoverageType.SEASON_PACK
        }
    }

    /** The capability chips for a set of prints; reused when a gate filters some out. */
    internal fun capabilitiesOf(prints: List<RankedPrint>): List<String> = deriveCapabilities(prints)

    private fun deriveCapabilities(prints: List<RankedPrint>): List<String> {
        val out = LinkedHashSet<String>()
        if (prints.any { it.resolution == Resolution.R2160 }) out.add("4K")
        if (prints.any { it.hasHdr }) out.add("HDR")
        if (prints.any { it.resolution == Resolution.R1080 }) out.add("1080p")
        if (prints.any { it.isOfficialPrint }) out.add("Official prints")
        if (prints.any { p -> p.links.any { it.resumable } }) out.add("Resumable")
        if (prints.any { p -> p.links.any { it.playableHere } }) out.add("Streamable")
        if (prints.any { p -> p.links.any { it.keepable } }) out.add("Downloadable")
        val langs = prints.flatMap { it.languages }.distinct()
        if (langs.isNotEmpty()) out.add(langs.joinToString("/") + " audio")
        return out.toList()
    }

    private fun toPrint(release: ReleaseDetail, workType: WorkType?): RankedPrint {
        val descriptor = if (workType != null) {
            ReleaseLabelParsing.describe(
                releaseTitle = release.releaseTitle,
                quality = release.quality,
                codec = release.codec,
                size = release.size,
                season = release.season,
                episode = release.episode,
                languages = release.languages,
                workType = workType,
            )
        } else {
            release.printDescriptor
        }
        val singleEpisode = descriptor.episode.takeIf { it != 0 }
        val (rangeFrom, rangeTo) =
            if (singleEpisode == null) ReleaseLabelParsing.parseRange(descriptor.episodeRange) else 0 to 0
        return RankedPrint(
            releaseId = release.id,
            rawTitle = release.releaseTitle?.takeIf { it.isNotBlank() } ?: release.quality,
            descriptor = descriptor,
            languages = descriptor.audioLanguages,
            sizeBytes = descriptor.sizeBytes.takeIf { it > 0L },
            coverage = descriptor.coverageType,
            season = descriptor.coverageSeason.takeIf { it != 0 },
            episodeFrom = singleEpisode ?: rangeFrom.takeIf { it != 0 },
            episodeTo = singleEpisode ?: rangeTo.takeIf { it != 0 },
            links = release.sources.map { toLink(it) },
        )
    }

    private fun toLink(source: SourceDetail): RankedLink {
        val assessment = source.classification
        return RankedLink(
            streamId = source.streamId,
            linkId = source.linkId,
            health = LinkState.fromWire(source.status ?: source.state),
            ephemeral = source.isEphemeral,
            resumable = source.isResumableLink,
            playUrl = source.bestUrl,
            label = source.label,
            kind = source.kind,
            playability = assessment.playability,
            score = LinkClassification.rankOf(source),
        )
    }
}

// ── presentation display maps — app-local label choices, not grammar ──────────────────────

private fun Resolution.display(): String = when (this) {
    Resolution.R2160 -> "4K"
    Resolution.R1080 -> "1080p"
    Resolution.R720 -> "720p"
    Resolution.R480, Resolution.R480_OR_LOWER -> "480p"
    Resolution.UNKNOWN -> ""
}

private fun SourceTag.display(): String = when (this) {
    SourceTag.UHD_BLURAY -> "UHD BluRay"
    SourceTag.BLURAY -> "BluRay"
    SourceTag.WEB_DL -> "WEB-DL"
    SourceTag.WEBRIP -> "WEBRip"
    SourceTag.HDTV -> "HDTV"
    SourceTag.DVD_RIP -> "DVD"
    SourceTag.TELESYNC -> "TS"
    SourceTag.TELECINE -> "Telecine"
    SourceTag.PPV -> "PPV"
    SourceTag.CAM -> "CAM"
    SourceTag.HDT_C -> "HDTC"
    SourceTag.UNKNOWN -> ""
}

private fun HdrFormat.display(): String = when (this) {
    HdrFormat.DOLBY_VISION -> "DV"
    HdrFormat.HDR10_PLUS -> "HDR10+"
    HdrFormat.HDR10 -> "HDR10"
    HdrFormat.HLG -> "HLG"
    HdrFormat.UNKNOWN -> ""
}

private fun Codec.display(): String = when (this) {
    Codec.H265 -> "H.265"
    Codec.H264 -> "H.264"
    Codec.AV1 -> "AV1"
    Codec.XVID -> "XviD"
    Codec.MPEG2 -> "MPEG-2"
    Codec.UNKNOWN -> ""
}

private fun Edition.display(): String = when (this) {
    Edition.DIRECTOR_CUT -> "Director's Cut"
    Edition.EXTENDED -> "Extended"
    Edition.IMAX -> "IMAX"
    Edition.UNRATED -> "Unrated"
    Edition.REMASTERED -> "Remastered"
    Edition.RESTORED -> "Restored"
    Edition.UNCUT -> "Uncut"
    Edition.FAN_EDIT -> "Fan Edit"
    Edition.THEATRICAL -> "Theatrical"
    Edition.UNKNOWN -> ""
}

// [sizeBytes] is BINARY — `detectSize` multiplies by 1024 to match `release_descriptor`, which is
// how a "15.2GB" print is really 15.2 x 1024^3 bytes. Dividing it by 1000 here printed that same
// file as "16.3 GB", so the detail screen disagreed with the label the release carries and with
// the download card, which reads sizeBytes directly. Same units on both sides of the arrow.
private fun formatBytes(bytes: Long): String = when {
    bytes >= 1L shl 40 -> "%.1f TB".format(bytes / (1L shl 40).toDouble())
    bytes >= 1L shl 30 -> "%.1f GB".format(bytes / (1L shl 30).toDouble())
    bytes >= 1L shl 20 -> "%.0f MB".format(bytes / (1L shl 20).toDouble())
    bytes >= 1L shl 10 -> "%.0f KB".format(bytes / (1L shl 10).toDouble())
    else -> "$bytes B"
}
