package com.raddstream.app.network.models

import com.google.gson.annotations.SerializedName

/*
 * v2 WIRE DTOs — the JSON the v2 contract says the server WILL send (API_V2.md §14, §8.1,
 * §16.4), written down so the mapping layer is real code and not a wish.
 *
 * // NOT SERVED YET - needs /api/v2/works (see EndpointGaps.MANIFEST, EndpointGaps.PLAY)
 * `viewer.py` has no route that returns any of these objects, and no `do_POST`. NOTHING in
 * this file is reachable from `RaddStreamApi`. It exists so that when the v2 surface lands,
 * the client change is "add four @GET lines" instead of a rewrite — and so the review
 * discussion about the contract happens against code, not prose.
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

/** `/api/v2/play` (§8.1). */
data class WirePlayBundle(
    @SerializedName("work_key")
    val workKey: String? = null,
    @SerializedName("release_id")
    val releaseId: Long? = null,
    val episode: WireEpisodeAddress? = null,
    val renditions: List<WireRendition> = emptyList(),
    val entitlement: WireEntitlement? = null,
    @SerializedName("expires_at")
    val expiresAt: Double? = null,
    @SerializedName("ttl_seconds")
    val ttlSeconds: Int? = null,
) {
    fun toDomain(): PlayBundle = PlayBundle(
        workKey = workKey.orEmpty(),
        printId = releaseId,
        episodeAddress = episode?.toDomain(),
        renditions = renditions.map { it.toDomain() },
        entitlement = entitlement?.toDomain() ?: Entitlement.freeDefault,
        expiresAt = expiresAt,
        ttlSeconds = ttlSeconds,
    )
}

data class WireEpisodeAddress(
    val season: Int? = null,
    val episode: Int? = null,
    val absolute: Int? = null,
) {
    fun toDomain(): EpisodeAddress = EpisodeAddress(season ?: 0, episode ?: 0, absolute)
}

data class WireRendition(
    @SerializedName("link_id")
    val linkId: Long? = null,
    @SerializedName("stream_id")
    val streamId: String? = null,
    /** OUR OWN redirector (`/api/v1/stream?id=<handle>`); no upstream address is served. */
    @SerializedName("play_url")
    val playUrl: String? = null,
    val label: String? = null,
    val protocol: String? = null,
    val playability: String? = null,
    @SerializedName("quality_label")
    val qualityLabel: String? = null,
    @SerializedName("quality_score")
    val qualityScore: Int? = null,
    @SerializedName("link_score")
    val linkScore: Int? = null,
    @SerializedName("score_scale")
    val scoreScale: String? = null,
    val ephemeral: Boolean? = null,
    @SerializedName("offset_seconds")
    val offsetSeconds: Int? = null,
    val headers: Map<String, String?> = emptyMap(),
) {
    fun toDomain(): Rendition = Rendition(
        linkId = linkId,
        streamId = streamId,
        playUrl = playUrl,
        label = label,
        protocol = PlayProtocol.fromWire(protocol),
        playability = Playability.fromWire(playability),
        qualityLabel = qualityLabel.orEmpty(),
        qualityScore = qualityScore ?: 0,
        linkScore = linkScore ?: 0,
        scoreScale = ScoreScale.fromWire(scoreScale),
        ephemeral = ephemeral == true,
        offsetSeconds = offsetSeconds ?: 0,
        headers = headers.filterValues { it != null }.mapValues { it.value!! },
    )
}

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
