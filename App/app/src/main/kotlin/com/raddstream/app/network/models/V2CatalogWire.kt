package com.raddstream.app.network.models

import com.google.gson.annotations.SerializedName
import com.raddstream.app.network.streamRedirectUrl

/*
 * v2 CATALOG WIRE DTOs — the JSON `Fast_Fetch/catalog_api.py` ACTUALLY sends on
 * GET /api/v2/browse, /api/v2/search and /api/v2/works/{id} (Phase 7, M1).
 *
 * These are NOT the shapes `V2Wire.kt` guessed at: that file's `WireWork` expects
 * flat `poster_url`/`backdrop_urls` strings and top-level `seasons`/`releases`
 * lists, but the server sends a structured `poster` object (`{src, kind, index}`)
 * on list items, an `images: {poster, backdrops}` object on a work detail, and
 * prints nested under `prints[]` with `audio`/`subtitles`/`coverage` objects and
 * `release_id` (not `id`) as the key. A DTO that parses the spec instead of the
 * server decodes everything to null — the exact mistake the old `WirePlayBundle`
 * made — so every field here was checked against `catalog_api.py` (`_browse_item`,
 * `work_detail`, `_print_view`, `_link_view`) before it was written.
 *
 * Two decode-safety rules, inherited from `V2Wire.kt`:
 *  1. NO field is typed as an enum. Gson would throw on a value added later; every
 *     enum is a String plus `fromWire(...)` in `toDomain()`.
 *  2. NO collection has a non-empty default and no scalar is non-null unless the
 *     server guarantees it, because a partially-implemented v2 route is expected to
 *     answer with missing keys rather than crash.
 *
 * ID SPACES: a v2 row is a WORK (`cat_works.id`); a v1 row is a POST (`posts.id`).
 * They are different numbers for the same title, and a work id must never be
 * passed where a post id is expected (Room favorites/history, `GET
 * /api/v1/posts/{id}`, the adult revalidation ledger). A mapped [Post] therefore
 * carries the work id in [Post.workId] and a NEGATIVE [Post.id] (`-workId`): a
 * negative id can never name a v1 post, `ResumeTile.of` already drops rows with
 * `postId <= 0`, and the id-keyed rails stay unique per work. Detail navigation
 * branches on `workId` first (see `Screen.Detail.createRouteForWork`); the real
 * v1 post id is resolved inside `CatalogRepository.getWorkDetailV2` through the
 * `work_ref` bridge and stored as the mapped detail's id.
 */

/** One structured artwork handle as the v2 read model serves it (`_images`). */
data class WireV2Image(
    val src: String? = null,
    val kind: String? = null,
    val index: Int? = null,
    val width: Int? = null,
    val height: Int? = null,
    val locale: String? = null,
)

/** The availability block of a grid item (`_available_view`). */
data class WireAvailability(
    val stream: Boolean? = null,
    val download: Boolean? = null,
    val any: Boolean? = null,
    val state: String? = null,
)

/** The entitlement block of a grid item: only the model is ever served. */
data class WireEntitlementRef(
    val model: String? = null,
)

/**
 * One `_browse_item` row: the shape GET /api/v2/browse and GET /api/v2/search
 * both return under `items[]`. `poster` is the structured object, NOT a URL
 * string — its `src` is already our own `/api/v1/art` handle or a public-CDN
 * URL, exactly as the v1 rows serve it. `prints` is a COUNT here, not a list;
 * the prints themselves only arrive on the detail route.
 */
data class WireBrowseItem(
    val id: Long? = null,
    @SerializedName("work_ref")
    val workRef: String? = null,
    val title: String? = null,
    val year: Int? = null,
    @SerializedName("work_type")
    val workType: String? = null,
    val animated: Boolean? = null,
    val poster: WireV2Image? = null,
    /** `imdb_rating` is TEXT in the ledger ("6.9"), never a JSON number. */
    val rating: String? = null,
    val genres: List<String?> = emptyList(),
    val languages: List<String?> = emptyList(),
    val country: String? = null,
    val industry: String? = null,
    @SerializedName("site_count")
    val siteCount: Int? = null,
    val seasons: Int? = null,
    val episodes: Int? = null,
    val prints: Int? = null,
    @SerializedName("quality_max")
    val qualityMax: String? = null,
    @SerializedName("best_quality_score")
    val bestQualityScore: Int? = null,
    val available: WireAvailability? = null,
    val flags: List<String?> = emptyList(),
    @SerializedName("identity_suspect")
    val identitySuspect: Boolean? = null,
    val entitlement: WireEntitlementRef? = null,
) {
    /**
     * A list-row [Post]. `contentType` is the v1 word the tiles already render:
     * `anime` is a work_type on this wire but a flag on a v1 row, so it becomes
     * `series` + [Post.isAnimated]. `id` is the negative-work-id sentinel
     * described in the file header — never a v1 post id.
     */
    fun toPost(): Post = Post(
        id = if (id != null && id in 1..Int.MAX_VALUE) -id.toInt() else 0,
        workId = id,
        title = title.orEmpty(),
        cleanTitle = title,
        year = year,
        contentType = when (workType?.trim()?.lowercase()) {
            "anime" -> "series"
            else -> workType
        },
        isAnimated = animated == true || workType?.trim()?.equals("anime", ignoreCase = true) == true,
        seasons = seasons?.toString(),
        posterUrl = poster?.src,
        backdropUrls = null,
        imdbRating = rating,
        imdbId = null,
        tmdbId = null,
        genres = genres.filterNotNull().joinToString(", ").takeIf { it.isNotBlank() },
        industry = industry,
        country = country,
        language = languages.filterNotNull().firstOrNull(),
        subtitled = null,
        releaseCount = prints,
        sourceCount = null,
        workRef = workRef,
    )
}

/** The envelope `send_layer2` puts around a browse/search answer. */
data class WireBrowseResponse(
    val ok: Boolean = false,
    val items: List<WireBrowseItem> = emptyList(),
    @SerializedName("next_cursor")
    val nextCursor: String? = null,
    @SerializedName("has_more")
    val hasMore: Boolean = false,
    @SerializedName("total_estimate")
    val totalEstimate: Int? = null,
    val count: Int? = null,
    val query: String? = null,
    val sort: String? = null,
)

/** The `images` object of a work detail (`_images`). */
data class WireDetailImages(
    val poster: WireV2Image? = null,
    val backdrops: List<WireV2Image> = emptyList(),
)

/** The `work` object of GET /api/v2/works/{id} (`work_detail`). */
data class WireDetailWork(
    val id: Long? = null,
    @SerializedName("work_ref")
    val workRef: String? = null,
    val title: String? = null,
    @SerializedName("original_title")
    val originalTitle: String? = null,
    val year: Int? = null,
    @SerializedName("work_type")
    val workType: String? = null,
    val animated: Boolean? = null,
    val synopsis: String? = null,
    val genres: List<String?> = emptyList(),
    val languages: List<String?> = emptyList(),
    val country: String? = null,
    val industry: String? = null,
    val rating: String? = null,
    @SerializedName("runtime_minutes")
    val runtimeMinutes: Int? = null,
    val images: WireDetailImages? = null,
    @SerializedName("site_count")
    val siteCount: Int? = null,
    @SerializedName("print_count")
    val printCount: Int? = null,
    @SerializedName("episode_count")
    val episodeCount: Int? = null,
    @SerializedName("season_count")
    val seasonCount: Int? = null,
    @SerializedName("quality_max")
    val qualityMax: String? = null,
    @SerializedName("best_quality_score")
    val bestQualityScore: Int? = null,
)

/** The `identity` object: the ids the detail resolves against, no work key. */
data class WireDetailIdentity(
    @SerializedName("imdb_id")
    val imdbId: String? = null,
    @SerializedName("tmdb_id")
    val tmdbId: Int? = null,
    @SerializedName("tvdb_id")
    val tvdbId: Int? = null,
    @SerializedName("work_type")
    val workType: String? = null,
)

/** One episode inside a detail season. */
data class WireDetailEpisode(
    val id: Long? = null,
    val number: Int? = null,
    @SerializedName("absolute_number")
    val absoluteNumber: Int? = null,
    @SerializedName("season_number")
    val seasonNumber: Int? = null,
    val title: String? = null,
    @SerializedName("air_date")
    val airDate: String? = null,
    @SerializedName("runtime_minutes")
    val runtimeMinutes: Int? = null,
    @SerializedName("best_release_id")
    val bestReleaseId: Long? = null,
    @SerializedName("print_ids")
    val printIds: List<Long?> = emptyList(),
    @SerializedName("print_labels")
    val printLabels: List<String?> = emptyList(),
    @SerializedName("quality_options")
    val qualityOptions: List<String?> = emptyList(),
    @SerializedName("print_count")
    val printCount: Int? = null,
)

/** One season of a work detail. */
data class WireDetailSeason(
    val id: Long? = null,
    val number: Int? = null,
    @SerializedName("season_type")
    val seasonType: String? = null,
    val title: String? = null,
    @SerializedName("episode_count")
    val episodeCount: Int? = null,
    @SerializedName("enumerated_episode_count")
    val enumeratedEpisodeCount: Int? = null,
    val episodes: List<WireDetailEpisode> = emptyList(),
    @SerializedName("print_ids")
    val printIds: List<Long?> = emptyList(),
    @SerializedName("pack_only")
    val packOnly: Boolean? = null,
)

/** A print's coverage block (`_print_view.coverage`). */
data class WireDetailCoverage(
    val type: String? = null,
    @SerializedName("season_number")
    val seasonNumber: Int? = null,
    @SerializedName("part_number")
    val partNumber: Int? = null,
    @SerializedName("episode_range")
    val episodeRange: String? = null,
    @SerializedName("episode_first")
    val episodeFirst: Int? = null,
    @SerializedName("episode_last")
    val episodeLast: Int? = null,
    val enumerated: Boolean? = null,
)

/** A print's audio block. */
data class WireDetailAudio(
    val languages: List<String?> = emptyList(),
    val channels: String? = null,
    val codecs: List<String?> = emptyList(),
    @SerializedName("dual_audio")
    val dualAudio: Boolean? = null,
)

/** A print's subtitle block. */
data class WireDetailSubtitles(
    val mode: String? = null,
    val languages: List<String?> = emptyList(),
)

/** A print's link counts. */
data class WireDetailCounts(
    val links: Int? = null,
    val streamable: Int? = null,
    val downloadable: Int? = null,
)

/**
 * One `_link_view` row. The key is `link_id`, NOT `id` (the `WireLink` DTO's
 * `id` field never matches this shape), and there is deliberately NO `play_url`:
 * the player builds our own redirector from `stream_id` (see
 * [toSourceDetail]), exactly as the v2 play bundle does. `downloadable`,
 * `is_temporary`, `is_resumable` and `mime_type` are NOT served here — the
 * view carries `playability`, `ephemeral`, `resumable` and `content_type`
 * instead, and the mapping derives the rest from those. `playable` is the
 * server's own verdict (group <= resolve, state not unplayable, ledger id
 * present) — a link with no ledger id is not playable even though it is not
 * dead, so `dead` alone must never stand in for it.
 */
data class WireDetailLink(
    @SerializedName("link_id")
    val linkId: Long? = null,
    @SerializedName("release_id")
    val releaseId: Long? = null,
    @SerializedName("work_id")
    val workId: Long? = null,
    @SerializedName("stream_id")
    val streamId: String? = null,
    val label: String? = null,
    val kind: String? = null,
    val playability: String? = null,
    /** The server's own playable verdict — see the class KDoc. Null when the server did not say. */
    val playable: Boolean? = null,
    val group: Int? = null,
    val state: String? = null,
    val dead: Boolean? = null,
    val tier: Int? = null,
    val protocol: String? = null,
    @SerializedName("content_type")
    val contentType: String? = null,
    val ephemeral: Boolean? = null,
    @SerializedName("expires_at")
    val expiresAt: Double? = null,
    val resumable: Boolean? = null,
    @SerializedName("accepts_ranges")
    val acceptsRanges: Boolean? = null,
    @SerializedName("size_bytes")
    val sizeBytes: Long? = null,
    @SerializedName("rank_score")
    val rankScore: Int? = null,
    @SerializedName("http_status")
    val httpStatus: Int? = null,
    @SerializedName("latency_ms")
    val latencyMs: Int? = null,
    @SerializedName("speed_mbps")
    val speedMbps: Double? = null,
    val measured: Boolean? = null,
    @SerializedName("score_scale")
    val scoreScale: String? = null,
    @SerializedName("last_evidence_at")
    val lastEvidenceAt: String? = null,
) {
    /**
     * A v1-shaped [SourceDetail]: the detail screen, the player and the
     * download card all read that model, so a v2 print must speak it. The
     * play URL is OUR redirector for the handle — the wire carries no URL,
     * by design, and a link with no handle has nothing to play.
     */
    fun toSourceDetail(baseUrl: String, releaseId: Long?): SourceDetail = SourceDetail(
        streamId = streamId.orEmpty(),
        playUrl = streamId?.takeIf { it.isNotBlank() }?.let { streamRedirectUrl(baseUrl, it) },
        linkId = linkId?.toInt(),
        releaseId = releaseId?.toInt(),
        label = label,
        kind = kind,
        playability = playability,
        protocol = protocol,
        container = null,
        status = state,
        state = state,
        // The wire's own verdict: a link with no ledger id is not playable even
        // though it is not dead, so `dead` alone must never stand in for it.
        playable = playable,
        downloadable = when (playability) {
            "download", "both" -> true
            "stream", "resolve_required" -> false
            else -> null
        },
        isTemporary = ephemeral,
        isResumable = resumable,
        resumable = resumable,
        ephemeral = ephemeral,
        httpStatus = httpStatus,
        fileSizeBytes = sizeBytes,
        sizeBytes = sizeBytes,
        mimeType = contentType,
        rankScore = rankScore,
        tier = tier,
        latencyMs = latencyMs,
        speedMbps = speedMbps,
        lastEvidenceAt = lastEvidenceAt,
        expiresAt = expiresAt,
    )
}

/**
 * One `_print_view` row: a `cat_releases` row with its links. `id` is
 * `release_id` on the wire; the flat `audio_languages` / `subtitle_mode`
 * keys `WirePrint` expects do not exist — they ride under `audio` /
 * `subtitles` objects, and the coverage rides under `coverage`.
 */
data class WireDetailPrint(
    @SerializedName("release_id")
    val releaseId: Long? = null,
    @SerializedName("work_id")
    val workId: Long? = null,
    @SerializedName("print_label")
    val printLabel: String? = null,
    val label: String? = null,
    val coverage: WireDetailCoverage? = null,
    val resolution: String? = null,
    @SerializedName("quality_label")
    val qualityLabel: String? = null,
    @SerializedName("source_tag")
    val sourceTag: String? = null,
    val codec: String? = null,
    @SerializedName("bit_depth")
    val bitDepth: Int? = null,
    val hdr: List<String?> = emptyList(),
    val container: String? = null,
    val edition: String? = null,
    @SerializedName("print_version")
    val printVersion: Int? = null,
    @SerializedName("release_group")
    val releaseGroup: String? = null,
    @SerializedName("size_bytes")
    val sizeBytes: Long? = null,
    @SerializedName("size_per_episode_bytes")
    val sizePerEpisodeBytes: Long? = null,
    val audio: WireDetailAudio? = null,
    val subtitles: WireDetailSubtitles? = null,
    val watermarked: Boolean? = null,
    @SerializedName("official_print")
    val officialPrint: Boolean? = null,
    @SerializedName("quality_score")
    val qualityScore: Int? = null,
    val flags: List<String?> = emptyList(),
    val counts: WireDetailCounts? = null,
    @SerializedName("created_at")
    val createdAt: String? = null,
    val links: List<WireDetailLink> = emptyList(),
) {
    /**
     * A v1-shaped [ReleaseDetail]. `season`/`episode` come from the structured
     * coverage, not from parsing the label: a pack has a season and no episode,
     * a single episode has both. `size` is the byte figure as text, because
     * [ReleaseDetail.sizeBytes] parses the text form.
     */
    fun toReleaseDetail(baseUrl: String, v1PostId: Int): ReleaseDetail = ReleaseDetail(
        id = releaseId?.toInt() ?: 0,
        postId = v1PostId.takeIf { it > 0 },
        releaseTitle = printLabel,
        season = coverage?.seasonNumber?.toString(),
        episode = when (coverage?.type) {
            "single_episode" -> coverage.episodeFirst?.toString()
            "episode_range" -> coverage.episodeRange
            else -> null
        },
        quality = qualityLabel ?: resolution,
        codec = codec,
        size = sizeBytes?.let { formatBytes(it) },
        languages = audio?.languages?.filterNotNull()?.joinToString("|"),
        sources = links.map { it.toSourceDetail(baseUrl, releaseId) },
    )

    /** The quality band this print belongs on, by the server's own rule (`tiers.band_of`). */
    fun band(): String = bandOf(resolution, qualityLabel, label)
}

/**
 * GET /api/v2/resolve/{handle} with `redirect=0`: the re-resolved link's
 * measured facts, no location. Same facts `/api/v1/stream?redirect=0` answers,
 * from the v2 universe (a cat link id, mintable back into a v1 stream handle
 * through the echoed `stream_id`).
 */
data class WireResolveResponse(
    val ok: Boolean = false,
    @SerializedName("link_ref")
    val linkRef: String? = null,
    @SerializedName("stream_id")
    val streamId: String? = null,
    val kind: String? = null,
    @SerializedName("mime_type")
    val mimeType: String? = null,
    @SerializedName("file_size_bytes")
    val fileSizeBytes: Long? = null,
    val resumable: Boolean? = null,
    @SerializedName("expires_in")
    val expiresIn: Long? = null,
    val refreshed: Boolean? = null,
)

/**
 * GET /api/v2/works/{id}. Only the keys the mapper reads are modelled; Gson
 * ignores the rest (`parts`, `print_groups`, `review_queue`,
 * `scope_unresolved_prints`, `provenance`), so an additive server change can
 * never crash decoding.
 */
data class WireWorkDetailResponse(
    val ok: Boolean = false,
    val work: WireDetailWork? = null,
    val identity: WireDetailIdentity? = null,
    val seasons: List<WireDetailSeason> = emptyList(),
    val prints: List<WireDetailPrint> = emptyList(),
    val availability: WireAvailability? = null,
    val entitlements: List<WireEntitlement> = emptyList(),
    val flags: List<String?> = emptyList(),
    @SerializedName("identity_suspect")
    val identitySuspect: Boolean? = null,
) {
    /**
     * A v1-shaped [PostDetail]: the detail screen, the player and the download
     * card all read that model, so a v2 work must speak it.
     *
     * `v1PostId` is the post id the `work_ref` bridge resolved (0 when it did
     * not resolve): Room favorites/history and the adult ledger key on it, so
     * it must be a real post id or 0, never the work id. `castNames` and
     * `seasonArtwork` ride in from the v1 detail for the same reason — the v2
     * projection carries neither, and a detail that dropped the cast section
     * would be worse than the v1 page it replaces.
     *
     * `optionGroups` is built here, client-side, from the prints: the v2
     * detail serves `print_groups`, not the server-collapsed ladder, and the
     * quality card reads [OptionGroup]. The winner rule is the server's own
     * (best playable copy by `rank_score` per band); the server's `/play`
     * bundle remains the authority at play time, so this ladder can only
     * offer what the bundle would also offer.
     */
    fun toPostDetail(
        baseUrl: String,
        v1PostId: Int = 0,
        castNames: String? = null,
        seasonArtwork: List<SeasonArtwork> = emptyList(),
    ): PostDetail? {
        val detailWork = work ?: return null
        val releases = prints.map { it.toReleaseDetail(baseUrl, v1PostId) }
        return PostDetail(
            id = v1PostId,
            title = detailWork.title.orEmpty(),
            cleanTitle = detailWork.title,
            year = detailWork.year,
            runtimeMinutes = detailWork.runtimeMinutes,
            contentType = when (detailWork.workType?.trim()?.lowercase()) {
                "anime" -> "series"
                else -> detailWork.workType
            },
            seasons = detailWork.seasonCount?.toString(),
            posterUrl = detailWork.images?.poster?.src,
            backdropUrls = detailWork.images?.backdrops
                ?.mapNotNull { it.src?.takeIf(String::isNotBlank) }
                ?.takeIf { it.isNotEmpty() }
                ?.let { urls -> urls.joinToString(",", "[", "]") { "\"${it.replace("\\", "\\\\").replace("\"", "\\\"")}\"" } },
            imdbRating = detailWork.rating,
            imdbId = identity?.imdbId,
            tmdbId = identity?.tmdbId,
            genres = detailWork.genres.filterNotNull().joinToString(", ").takeIf { it.isNotBlank() },
            synopsis = detailWork.synopsis,
            castNames = castNames,
            isAnimated = detailWork.animated == true ||
                detailWork.workType?.trim()?.equals("anime", ignoreCase = true) == true,
            industry = detailWork.industry,
            country = detailWork.country,
            language = detailWork.languages.filterNotNull().firstOrNull(),
            releases = releases,
            optionGroups = buildOptionGroups(prints, baseUrl),
            workRef = detailWork.workRef,
            seasonArtworkRows = seasonArtwork.ifEmpty { null },
        )
    }
}

/**
 * Which quality band a print's own words describe — the server's rule
 * (`Fast_Fetch/tiers.py::band_of`), copied verbatim so the client-built ladder
 * cannot disagree with the server-collapsed one about what a rung is. "HD"
 * alone is 720p, never 1080p: promising 1080p for a 720p file shows a blurry
 * picture under a label the viewer trusted.
 */
internal fun bandOf(vararg texts: String?): String {
    val blob = texts.filterNotNull().joinToString(" ").lowercase()
    val patterns = listOf(
        "2160p" to listOf("2160", "4k", "uhd", "hdr"),
        "1080p" to listOf("1080", "full hd", "fhd"),
        "720p" to listOf("720", "hd rip"),
        "480p" to listOf("480", "sdrip", "sd rip"),
        "sd" to listOf("360", "240", "400p", "cam", "hdts", "hd-ts"),
    )
    for ((band, needles) in patterns) {
        if (needles.any { it in blob }) return band
    }
    if ("hd" in blob || "hdtv" in blob) return "720p"
    return "unspecified"
}

/** The display name of a band, as the server names it (`tiers.py`). */
private fun bandLabel(band: String): String = when (band) {
    "2160p" -> "4K Ultra HD"
    "1080p" -> "Full HD"
    "720p" -> "HD"
    "480p" -> "480p"
    "sd" -> "SD"
    else -> band
}

/** One print's byte figure as the text [ReleaseDetail.sizeBytes] parses. */
private fun formatBytes(bytes: Long): String = when {
    bytes >= 1_000_000_000L -> "%.1f GB".format(java.util.Locale.US, bytes / 1_000_000_000.0)
    bytes >= 1_000_000L -> "%.0f MB".format(java.util.Locale.US, bytes / 1_000_000.0)
    bytes >= 1_000L -> "%.0f KB".format(java.util.Locale.US, bytes / 1_000.0)
    else -> "$bytes B"
}

/**
 * The server-collapsed ladder, built from v2 prints: one [OptionGroup] per
 * scope (a movie is a single null/null group; a series has one per season, and
 * one per episode where prints cover single episodes), one [LadderTier] per
 * band in the scope, the winner the best playable copy by `rank_score`.
 * A scope whose prints have no playable link still gets its tiers with
 * `mode = download_only`, so the card can offer the keep instead of vanishing.
 */
internal fun buildOptionGroups(prints: List<WireDetailPrint>, baseUrl: String): List<OptionGroup> {
    data class Scope(val season: Int?, val episode: Int?)
    val byScope = prints.groupBy { print ->
        when (print.coverage?.type) {
            "whole_work" -> Scope(null, null)
            "season_pack", "parts" -> Scope(print.coverage?.seasonNumber, null)
            "single_episode" -> Scope(print.coverage?.seasonNumber, print.coverage?.episodeFirst)
            "episode_range" -> Scope(print.coverage?.seasonNumber, print.coverage?.episodeFirst)
            else -> Scope(print.coverage?.seasonNumber, null)
        }
    }
    return byScope.entries.sortedWith(
        compareBy({ it.key.season ?: -1 }, { it.key.episode ?: -1 }),
    ).map { (scope, scopePrints) ->
        val byBand = scopePrints.groupBy { it.band() }
        val tiers = byBand.entries.sortedBy { bandRank(it.key) }.map { (band, bandPrints) ->
            val links = bandPrints.flatMap { print ->
                print.links.map { link -> print to link }
            }.filter { (_, link) -> !link.streamId.isNullOrBlank() }
            val playable = links.filter { (_, link) -> link.dead != true && link.playable != false }
            val ordered = (playable.ifEmpty { links }).sortedWith(
                compareByDescending<Pair<WireDetailPrint, WireDetailLink>> { (_, link) -> link.rankScore ?: 0 }
                    .thenByDescending { (_, link) -> link.speedMbps ?: 0.0 },
            )
            val winner = ordered.firstOrNull()
            val winnerPlayable = winner != null && winner.second.dead != true && winner.second.playable != false
            LadderTier(
                band = band,
                quality = winner?.first?.resolution,
                label = bandLabel(band),
                mode = if (winnerPlayable) "play" else "download_only",
                playable = winnerPlayable,
                copies = links.size,
                link = winner?.let { (print, link) ->
                    LadderLink(
                        streamId = link.streamId,
                        playUrl = link.streamId?.let { streamRedirectUrl(baseUrl, it) },
                        kind = link.kind,
                        playable = winnerPlayable,
                        status = link.state,
                        expiresAt = link.expiresAt?.toString(),
                        isResumable = link.resumable,
                        isTemporary = link.ephemeral,
                        fileSizeBytes = link.sizeBytes,
                        mimeType = link.contentType,
                        label = link.label,
                    )
                },
                backupHandles = ordered.drop(1).mapNotNull { (_, link) -> link.streamId },
                audioLanguages = winner?.first?.audio?.languages?.filterNotNull().orEmpty(),
            )
        }
        val best = tiers.filter { it.playable }.minByOrNull { bandRank(it.band) }
        OptionGroup(
            season = scope.season?.toString(),
            episode = scope.episode?.toString(),
            tiers = tiers,
            auto = best?.link?.streamId?.let { LadderAuto(band = best.band, reason = "best", streamId = it) },
            downloadOnlyBands = tiers.filter { it.mode == "download_only" }.map { it.band },
        )
    }
}

/** 0 for the best band, ascending; `unspecified` last (mirrors `tiers.band_rank`). */
private fun bandRank(band: String): Int {
    val bands = listOf("2160p", "1080p", "720p", "480p", "sd")
    return if (band in bands) bands.indexOf(band) else bands.size
}
