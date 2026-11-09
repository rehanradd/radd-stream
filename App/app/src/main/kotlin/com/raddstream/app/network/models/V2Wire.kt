package com.raddstream.app.network.models

import com.google.gson.annotations.SerializedName
import com.raddstream.app.network.streamRedirectUrl

/*
 * v2 WIRE DTOs — the JSON the v2 contract said the server WOULD send (API_V2.md §14, §8.1,
 * §16.4), written down so the mapping layer is real code and not a wish.
 *
 * Phase 7 (D2): the premise this header was written under is gone — v2 IS served now
 * (rev-7 projection live since 2026-11-10; `POST /api/v2/play`, `GET /api/v2/suggest`,
 * `POST /api/v2/links/`, `POST /api/v2/episodes/`, `/api/v2/account` all allow-listed
 * in live nginx, and the GET catalog routes `browse`/`search`/`works/{id}` are served
 * by `catalog_api.py`). What is NOT true is that the server sends THESE shapes: the
 * real wire carries a structured `poster` object, `images:{poster,backdrops}`, prints
 * under `prints[]` with nested `audio`/`subtitles`/`coverage`, and links keyed by
 * `link_id` with no `play_url` — so `WireWork`/`WireSeason`/`WirePrint`/`WireLink`
 * have ZERO callers and no tests, and wiring them would repeat the
 * `WirePlayBundle` parses-everything-to-null mistake this file itself documents.
 * The live shapes are `V2CatalogWire.kt`, which the app actually calls; this file
 * stays as the contract record, not the mapping layer.
 *
 * Two decode-safety rules that are load-bearing here and nowhere else:
 *  1. NO field is typed as an enum. Gson would throw on a value added later; every enum is
 *     a String plus `fromWire(...)` in `toDomain()` (§16.6, pinned by EnumToleranceTest).
 *  2. NO collection has a non-empty default and no scalar is non-null unless the server
 *     guarantees it, because a partially-implemented v2 route is expected to answer with
 *     missing keys rather than crash.
 */

/** A `cat_works` row as JSON. */
data class WireWork(
    val id: Long? = null,
    @SerializedName("work_key")
    val workKey: String? = null,
    val title: String? = null,
    @SerializedName("original_title")
    val originalTitle: String? = null,
    val year: Int? = null,
    @SerializedName("work_type")
    val workType: String? = null,
    val genres: List<String?> = emptyList(),
    val synopsis: String? = null,
    @SerializedName("poster_url")
    val posterUrl: String? = null,
    @SerializedName("backdrop_urls")
    val backdropUrls: List<String?> = emptyList(),
    @SerializedName("imdb_id")
    val imdbId: String? = null,
    @SerializedName("tmdb_id")
    val tmdbId: Int? = null,
    @SerializedName("imdb_rating")
    val imdbRating: String? = null,
    val country: String? = null,
    val industry: String? = null,
    val language: String? = null,
    val flags: List<String?> = emptyList(),
    val seasons: List<WireSeason> = emptyList(),
    val releases: List<WirePrint> = emptyList(),
    val entitlements: List<WireEntitlement> = emptyList(),
    @SerializedName("link_count")
    val linkCount: Int? = null,
    @SerializedName("streamable_count")
    val streamableCount: Int? = null,
    @SerializedName("best_quality_score")
    val bestQualityScore: Int? = null,
) {
    fun toDomain(): Work = Work(
        workKey = workKey.orEmpty(),
        id = id,
        title = title.orEmpty(),
        originalTitle = originalTitle,
        year = year,
        workType = WorkType.fromWire(workType),
        genres = genres.filterNotNull().map { it.trim() }.filter { it.isNotEmpty() },
        synopsis = synopsis,
        posterUrl = posterUrl,
        backdropUrls = backdropUrls.filterNotNull().filter { it.isNotEmpty() },
        imdbId = imdbId,
        tmdbId = tmdbId,
        imdbRating = imdbRating,
        country = country,
        industry = industry,
        language = language,
        seasons = seasons.map { it.toDomain() },
        prints = releases.map { it.toDomain() },
        entitlements = entitlements.map { it.toDomain() },
        flags = WorkFlag.listFromWire(flags),
        bestQualityScore = bestQualityScore ?: 0,
        linkCount = linkCount ?: 0,
        streamableCount = streamableCount ?: 0,
    )
}

data class WireSeason(
    val id: Long? = null,
    val number: Int? = null,
    val year: Int? = null,
    @SerializedName("season_type")
    val seasonType: String? = null,
    @SerializedName("episode_count")
    val episodeCount: Int? = null,
    val episodes: List<WireEpisode> = emptyList(),
) {
    fun toDomain(): Season = Season(
        number = number ?: 0,
        id = id,
        year = year,
        kind = SeasonType.fromWire(seasonType),
        episodeCount = episodeCount ?: episodes.size,
        episodes = episodes.map { it.toDomain(number ?: 0) },
    )
}

data class WireEpisode(
    val id: Long? = null,
    val number: Int? = null,
    @SerializedName("absolute_number")
    val absoluteNumber: Int? = null,
    val title: String? = null,
    @SerializedName("still_url")
    val stillUrl: String? = null,
    @SerializedName("runtime_minutes")
    val runtimeMinutes: Int? = null,
    @SerializedName("best_release_id")
    val bestReleaseId: Long? = null,
) {
    fun toDomain(seasonNumber: Int): Episode = Episode(
        seasonNumber = seasonNumber,
        number = number ?: 0,
        id = id,
        absoluteNumber = absoluteNumber,
        title = title,
        stillUrl = stillUrl,
        runtimeMinutes = runtimeMinutes,
        bestReleaseId = bestReleaseId,
    )
}

/**
 * A `cat_releases` row. The print axis arrives fully structured, which is the whole point
 * of the v2 surface: no client-side parsing, no `quality_score` re-derived by hand.
 *
 * `source_site` and `origin_url` are NOT modelled: the served `print` view does not contain
 * them, so a v2 response could not reintroduce provenance into the UI even if the server
 * started sending them (unknown keys are ignored — §16.6).
 */
data class WirePrint(
    val id: Long? = null,
    val label: String? = null,
    @SerializedName("season_number")
    val seasonNumber: Int? = null,
    @SerializedName("coverage_type")
    val coverageType: String? = null,
    @SerializedName("episode_range")
    val episodeRange: String? = null,
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
    @SerializedName("size_bytes")
    val sizeBytes: Long? = null,
    @SerializedName("size_per_episode_bytes")
    val sizePerEpisodeBytes: Long? = null,
    @SerializedName("audio_languages")
    val audioLanguages: List<String?> = emptyList(),
    @SerializedName("audio_channels")
    val audioChannels: String? = null,
    @SerializedName("audio_codecs")
    val audioCodecs: List<String?> = emptyList(),
    @SerializedName("dual_audio")
    val dualAudio: Boolean? = null,
    @SerializedName("subtitle_mode")
    val subtitleMode: String? = null,
    @SerializedName("subtitle_languages")
    val subtitleLanguages: List<String?> = emptyList(),
    val watermarked: Boolean? = null,
    @SerializedName("official_print")
    val officialPrint: Boolean? = null,
    @SerializedName("quality_score")
    val qualityScore: Int? = null,
    val flags: List<String?> = emptyList(),
    @SerializedName("created_at")
    val createdAt: String? = null,
    val links: List<WireLink> = emptyList(),
) {
    fun toDomain(): Print {
        val mode = SubtitleMode.fromWire(subtitleMode)
        val descriptor = PrintDescriptor(
            resolution = Resolution.fromWire(resolution),
            qualityLabel = qualityLabel.orEmpty(),
            sourceTag = SourceTag.fromWire(sourceTag),
            codec = Codec.fromWire(codec),
            bitDepth = bitDepth ?: 0,
            hdr = hdr.filterNotNull().map { HdrFormat.fromWire(it) },
            container = Container.fromWire(container),
            edition = Edition.fromWire(edition),
            version = printVersion ?: 0,
            isPack = flags.any { it == "pack" },
            episodeRange = episodeRange.orEmpty(),
            season = seasonNumber ?: 0,
            episode = 0,
            scope = PrintScope.UNKNOWN,
            sizeBytes = sizeBytes ?: 0L,
            sizePerEpisodeBytes = sizePerEpisodeBytes ?: 0L,
            audioLanguages = audioLanguages.filterNotNull(),
            audioCodecs = audioCodecs.filterNotNull(),
            channelLayout = audioChannels.orEmpty().ifEmpty { "unknown" },
            dualAudio = dualAudio == true || audioLanguages.filterNotNull().size >= 2,
            subtitlesAvailable = mode != SubtitleMode.NONE && mode != SubtitleMode.UNKNOWN,
            subtitlesExternal = mode == SubtitleMode.EXTERNAL,
            subtitlesHardcoded = mode == SubtitleMode.HARDCODED,
            subtitleLangs = subtitleLanguages.filterNotNull(),
            watermarked = watermarked == true,
            officialPrint = officialPrint == true,
            // The server's number, verbatim. 0 is only used when the key is absent, and a
            // missing score is NOT re-derived here: that would be a second source of truth.
            qualityScore = qualityScore ?: 0,
            coverageType = CoverageType.fromWire(coverageType),
            coverageSeason = seasonNumber ?: 0,
            episodeCountCovered = 0,
            flags = PrintFlag.listFromWire(flags),
        )
        return Print(
            id = id,
            label = label.orEmpty(),
            seasonNumber = seasonNumber,
            coverage = CoverageType.fromWire(coverageType),
            episodeRange = episodeRange.orEmpty(),
            descriptor = descriptor,
            links = links.map { it.toDomain() },
            createdAt = createdAt,
        )
    }
}

/**
 * A `cat_links` row: every link-axis field the server measured or projected.
 *
 * Addressed by our own opaque handle ([streamId]) and our own redirector ([playUrl]). The
 * hoster vocabulary that used to sit here — `source_site`, `service`, `source_name`, `url`,
 * `final_url`, `resource_id` — is ABSENT from the model, not merely unused: the projection
 * strips it at the HTTP edge, and a client that cannot decode it cannot render it.
 */
data class WireLink(
    @SerializedName("stream_id")
    val streamId: String? = null,
    @SerializedName("play_url")
    val playUrl: String? = null,
    /** Ours: "Fast direct" | "Standard". Describes how it behaves, never who runs it. */
    val label: String? = null,
    val id: Long? = null,
    @SerializedName("release_id")
    val releaseId: Long? = null,
    val kind: String? = null,
    val playability: String? = null,
    val state: String? = null,
    val protocol: String? = null,
    val tier: Int? = null,
    val playable: Boolean? = null,
    val downloadable: Boolean? = null,
    val ephemeral: Boolean? = null,
    val resumable: Boolean? = null,
    @SerializedName("is_temporary")
    val isTemporary: Boolean? = null,
    @SerializedName("is_resumable")
    val isResumable: Boolean? = null,
    @SerializedName("accepts_ranges")
    val acceptsRanges: Boolean? = null,
    @SerializedName("expires_at")
    val expiresAt: Double? = null,
    @SerializedName("content_type")
    val contentType: String? = null,
    @SerializedName("mime_type")
    val mimeType: String? = null,
    @SerializedName("size_bytes")
    val sizeBytes: Long? = null,
    @SerializedName("file_size_bytes")
    val fileSizeBytes: Long? = null,
    @SerializedName("http_status")
    val httpStatus: Int? = null,
    @SerializedName("latency_ms")
    val latencyMs: Int? = null,
    @SerializedName("speed_mbps")
    val speedMbps: Double? = null,
    @SerializedName("rank_score")
    val rankScore: Int? = null,
    @SerializedName("score_scale")
    val scoreScale: String? = null,
    @SerializedName("last_evidence_at")
    val lastEvidenceAt: Double? = null,
) {
    fun toDomain(): MediaLink {
        val assessment = LinkClassification.classify(
            SourceDetail(
                streamId = streamId.orEmpty(),
                playUrl = playUrl,
                linkId = id?.toInt(),
                releaseId = releaseId?.toInt(),
                label = label,
                kind = kind,
                playability = playability,
                protocol = protocol,
                state = state,
                playable = playable,
                downloadable = downloadable,
                isTemporary = isTemporary ?: ephemeral,
                isResumable = isResumable ?: resumable,
                httpStatus = httpStatus,
                fileSizeBytes = fileSizeBytes ?: sizeBytes,
                mimeType = mimeType ?: contentType,
                tier = tier,
                latencyMs = latencyMs,
                speedMbps = speedMbps,
                expiresAt = expiresAt,
                lastEvidenceAt = lastEvidenceAt?.toString(),
            ),
        )
        return MediaLink(
            streamId = streamId.orEmpty(),
            playUrl = playUrl,
            label = label,
            id = id,
            printId = releaseId,
            assessment = assessment,
            score = rankScore ?: LinkClassification.rankScore(assessment),
            scoreScale = ScoreScale.fromWire(scoreScale),
            sizeBytes = fileSizeBytes ?: sizeBytes,
            httpStatus = httpStatus,
            mimeType = mimeType ?: contentType,
            resumable = isResumable ?: resumable == true,
            expiresAt = expiresAt,
            lastEvidenceAt = lastEvidenceAt?.toString(),
        )
    }
}

/** A `cat_entitlements` row (§11). */
data class WireEntitlement(
    val model: String? = null,
    val ownership: String? = null,
    @SerializedName("price_minor")
    val priceMinor: Int? = null,
    val currency: String? = null,
    val offers: List<String?> = emptyList(),
    val note: String? = null,
) {
    fun toDomain(): Entitlement = Entitlement(
        model = EntitlementModel.fromWire(model),
        ownership = Ownership.fromWire(ownership),
        priceMinor = priceMinor,
        currency = currency,
        offers = offers.filterNotNull(),
        note = note,
    )
}

/**
 * POST /api/v2/play (§8.1): one of release_id / episode_id / work_id. `prefer` orders
 * the ladder (`quality` | `speed` | `data_saver`); null means the server's default.
 * `device` is a caller-chosen label, truncated to 64 chars server-side.
 */
data class WirePlayRequest(
    @SerializedName("release_id")
    val releaseId: Int? = null,
    @SerializedName("episode_id")
    val episodeId: Int? = null,
    @SerializedName("work_id")
    val workId: Int? = null,
    val prefer: String? = null,
    val device: String? = null,
)

/**
 * POST /api/v2/play response — the shape the server ACTUALLY sends
 * (`catalog_api.play_bundle`), not the §8.1 spec shape: there is no `renditions`,
 * no `entitlement`, no `expires_at` and no `work_key` on the wire. The server ranks
 * the candidates itself and hands back one tier per print plus the ranked lists,
 * and the chapter data rides in `coverage.enumerated_episodes`. The spec-shaped
 * `WirePlayBundle` that used to live here parsed everything to null on a real
 * answer, so it is gone; this is the shape a live call returns.
 */
data class WirePlayResponse(
    val target: WirePlayTarget? = null,
    @SerializedName("work_id")
    val workId: Int? = null,
    @SerializedName("release_id")
    val releaseId: Long? = null,
    @SerializedName("print_label")
    val printLabel: String? = null,
    val tiers: List<WirePlayTier> = emptyList(),
    val auto: WirePlayAuto? = null,
    val coverage: WirePlayCoverage? = null,
    @SerializedName("stream_candidates")
    val streamCandidates: List<WirePlayCandidate> = emptyList(),
    val candidates: List<WirePlayCandidate> = emptyList(),
    @SerializedName("download_options")
    val downloadOptions: List<WirePlayCandidate> = emptyList(),
    val playable: Boolean = false,
    val available: Boolean = false,
    val reason: String? = null,
    val protocol: String? = null,
    val ephemeral: Boolean = false,
    @SerializedName("candidate_count")
    val candidateCount: Int = 0,
    @SerializedName("dead_candidate_count")
    val deadCandidateCount: Int = 0,
    val prefer: String? = null,
    val device: String? = null,
) {
    /**
     * The server-ranked candidates become the failover order, in the order the server
     * sent them — the client does not re-rank. Each rendition's address is OUR OWN
     * redirector for its handle: the response carries no URL, by design.
     * `workKey` stays empty — the response carries `work_id`, not a work key, and the
     * player identifies the work by its own staged scope, not by this field.
     * `entitlement` stays the free default — the response carries no entitlement.
     * The print's coverage does NOT ride here: it is a [com.raddstream.app.player.Coverage],
     * which lives in the player package, so [WirePlayCoverage.toPlayerCoverage] maps it
     * from the caller's side and the repository returns both together.
     */
    fun toDomain(baseUrl: String): PlayBundle {
        val qualityLabel = tiers.firstOrNull()?.label ?: printLabel.orEmpty()
        return PlayBundle(
            workKey = "",
            printId = releaseId,
            episodeAddress = target?.toDomain(),
            renditions = streamCandidates.map { it.toDomain(baseUrl, qualityLabel) },
            entitlement = Entitlement.freeDefault,
            expiresAt = null,
            ttlSeconds = null,
        )
    }
}

data class WirePlayTarget(
    val kind: String? = null,
    @SerializedName("episode_id")
    val episodeId: Int? = null,
    @SerializedName("work_id")
    val workId: Int? = null,
    @SerializedName("release_id")
    val releaseId: Int? = null,
    @SerializedName("work_type")
    val workType: String? = null,
    val season: Int? = null,
    val episode: Int? = null,
    val absolute: Int? = null,
) {
    fun toDomain(): EpisodeAddress = EpisodeAddress(season ?: 0, episode ?: 0, absolute)
}

/**
 * POST /api/v2/links/{handle}/report — one playback fact about one link, so the
 * server's link-health axis learns from real viewers instead of only its own
 * probes. The `{handle}` path segment is OUR OWN opaque handle (the same one the
 * player streams through) — never a raw row id and never a host address. `event`
 * is one of `played` | `stalled` | `failed` | `resolved`; `error` is a short
 * human sentence, scrubbed to 200 chars server-side. Best-effort by design: a
 * failed report is dropped, never shown to the viewer and never retried.
 * (Session 123: closes the gap EndpointGaps.REPORT used to list.)
 */
data class LinkReportRequest(
    val event: String,
    @SerializedName("latency_ms")
    val latencyMs: Int? = null,
    val error: String? = null,
    val device: String? = null,
)

data class LinkReportResponse(
    val ok: Boolean = false,
    val recorded: Boolean = false,
    @SerializedName("report_id")
    val reportId: Int = 0,
    val event: String = "",
    @SerializedName("link_ref")
    val linkRef: String? = null,
)

/**
 * POST /api/v2/episodes/{episode_id}/offset — a learned pack offset: where
 * episode N starts inside a season-pack file. The `{episode_id}` is the
 * catalog's own episode id (carried on `WirePlayEpisode.episode_id` through
 * `EpisodeCoverage.episodeId`); the server stores it against the work identity
 * and echoes it back to the next `/play`, so a wrong offset can be corrected
 * once by one viewer and learned by every later one. `chapter_title` is
 * scrubbed server-side (it is echoed back publicly). Best-effort like the
 * link report: a failed post leaves the local learned offset in place.
 * (Session 123: closes the gap EndpointGaps.OFFSET used to list.)
 */
data class EpisodeOffsetRequest(
    @SerializedName("offset_seconds")
    val offsetSeconds: Int,
    @SerializedName("chapter_title")
    val chapterTitle: String? = null,
    @SerializedName("release_label")
    val releaseLabel: String? = null,
)

data class EpisodeOffsetResponse(
    val ok: Boolean = false,
    val recorded: Boolean = false,
    @SerializedName("episode_id")
    val episodeId: Int = 0,
    val season: Int = 0,
    val episode: Int = 0,
    @SerializedName("offset_seconds")
    val offsetSeconds: Int = 0,
)

data class WirePlayAuto(
    val band: String? = null,
    val playable: Boolean = false,
)

/**
 * One tier of the print: the band, the single best copy, and the same-band
 * runner-ups as handles only (`backup_handles`), so a silent failover never
 * widens what one response discloses. There is one tier per print — this call
 * is per print, not per work.
 */
data class WirePlayTier(
    val band: String? = null,
    val quality: String? = null,
    val label: String? = null,
    val mode: String? = null,
    val playable: Boolean = false,
    val link: WirePlayCandidate? = null,
    val copies: Int = 0,
    @SerializedName("backup_handles")
    val backupHandles: List<String> = emptyList(),
)

/**
 * One candidate link, exactly as `catalog_api._link_view` shapes it: our opaque
 * handle, the measured facts, and no upstream address of any kind. `playable` is
 * the server's own verdict (streamable group and not dead); `dead` is the same
 * verdict the other way round, kept because the response's `tried` list names it.
 */
data class WirePlayCandidate(
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
    val playable: Boolean = false,
    val group: Int? = null,
    val state: String? = null,
    val dead: Boolean = false,
    val tier: Int? = null,
    val protocol: String? = null,
    @SerializedName("content_type")
    val contentType: String? = null,
    val ephemeral: Boolean? = null,
    @SerializedName("expires_at")
    val expiresAt: Long? = null,
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
    fun toDomain(baseUrl: String, qualityLabel: String): Rendition = Rendition(
        linkId = linkId,
        streamId = streamId,
        // No URL is served: the address is our own redirector for this handle.
        playUrl = streamId?.takeIf { it.isNotBlank() }?.let { streamRedirectUrl(baseUrl, it) },
        label = label,
        protocol = PlayProtocol.fromWire(protocol),
        playability = Playability.fromWire(playability),
        qualityLabel = qualityLabel,
        // The tier carries no quality score, only the band: 0 is "not served",
        // never a guess at the print's score.
        qualityScore = 0,
        linkScore = rankScore ?: 0,
        scoreScale = ScoreScale.fromWire(scoreScale),
        ephemeral = ephemeral == true,
        offsetSeconds = 0,
        resumable = resumable == true,
        headers = emptyMap(),
    )
}

/**
 * The print's coverage block: the type and the episode boundaries (`enumerated_episodes`,
 * one row per episode with its offset and chapter title), plus the overlay for the
 * episode this call is about (`offset_seconds`, `chapter_title`, `ordinal`). This is
 * the chapter data step 11's ticks read — the v1 detail never serves the offsets,
 * only this call does.
 */
data class WirePlayCoverage(
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
    @SerializedName("enumerated_episodes")
    val enumeratedEpisodes: List<WirePlayEpisode> = emptyList(),
    @SerializedName("offset_seconds")
    val offsetSeconds: Int? = null,
    @SerializedName("chapter_title")
    val chapterTitle: String? = null,
    val ordinal: Int? = null,
    val source: String? = null,
    @SerializedName("needs_offset_calibration")
    val needsOffsetCalibration: Boolean? = null,
    @SerializedName("pack_warning")
    val packWarning: String? = null,
)

data class WirePlayEpisode(
    @SerializedName("episode_id")
    val episodeId: Int? = null,
    val number: Int? = null,
    @SerializedName("absolute_number")
    val absoluteNumber: Int? = null,
    @SerializedName("season_number")
    val seasonNumber: Int? = null,
    val ordinal: Int? = null,
    @SerializedName("offset_seconds")
    val offsetSeconds: Int? = null,
    @SerializedName("chapter_title")
    val chapterTitle: String? = null,
)

/**
 * RFC 9457 problem+json (§16.4). Decodable by Gson because every field is a String/Int/List
 * and `code` is mapped through `fromWire` in [toDomain], never typed as an enum.
 */
data class WireProblem(
    val type: String? = null,
    val title: String? = null,
    val status: Int? = null,
    val detail: String? = null,
    val instance: String? = null,
    val code: String? = null,
    val errors: List<String?> = emptyList(),
) {
    fun toDomain(): ProblemDetails = ProblemDetails(
        type = type,
        title = title,
        status = status,
        detail = detail,
        instance = instance,
        code = ProblemCode.fromWire(code),
        errors = errors.filterNotNull(),
    )
}
