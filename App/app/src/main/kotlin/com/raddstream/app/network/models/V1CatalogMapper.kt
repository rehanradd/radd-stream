package com.raddstream.app.network.models

/*
 * THE v1 -> v2 FALLBACK LAYER. This is the compatibility strategy in one file:
 *
 *   UI and Repository program against [Work] / [Print] / [MediaLink] / [PlayBundle].
 *   Today those objects are produced HERE, from the four live v1 endpoints, by
 *   [V1CatalogMapper]. When `/api/v2` is served, the same types come from [V2Wire]
 *   instead and this file shrinks to the `browse()` list only.
 *
 * That is why there are no optimistic nulls scattered through the models: every field the
 * v1 server cannot answer is filled by a DOCUMENTED derivation here (and only here), and
 * each derivation names the rule it copies. Nothing is invented: a field with no v1
 * counterpart stays null/empty and is listed in [EndpointGaps].
 *
 * ADULT POLICY: this mapper neither reads nor propagates `is_18_plus` (App/AGENTS.md,
 * API_V2.md §13). The server already filtered it out of the list, answers 404 for a flagged
 * id, and never sends the flag; the app has no field for it, so there is no way to display
 * or request a flagged work through this layer.
 */
object V1CatalogMapper {

    /** A v1 list row -> a browse tile. No parsing beyond the year/rating text. */
    fun browseItem(post: Post): BrowseItem {
        val workType = WorkType.fromContentType(post.contentType, animatedFromList(post))
        return BrowseItem(
            workKey = WorkIdentity.workKey(
                cleanTitle = post.displayTitle,
                year = post.year,
                workType = workType,
                imdbId = post.imdbId,
                tmdbId = post.tmdbId,
            ),
            title = post.displayTitle,
            year = post.year,
            workType = workType,
            posterUrl = post.posterUrl,
            imdbRating = post.imdbRating,
            releaseCount = post.releaseCount ?: 0,
            sourceCount = post.sourceCount ?: 0,
            bestQualityScore = 0,
        )
    }

    fun browseItems(response: PostsResponse): List<BrowseItem> = response.results.map { browseItem(it) }

    /**
     * The list row carries `is_animated` (verified live 2026-10-28: `?type=anime` returns
     * rows whose `is_animated` is 1), so a browse tile is typed ANIME from the wire the moment
     * it decodes — it no longer waits for the detail response to correct it. A row from a
     * server that sends no such key stays null, and [WorkType.fromContentType] then leaves the
     * `content_type` alone: unknown is never read as "not animated".
     */
    private fun animatedFromList(post: Post): Boolean? = post.isAnimated

    /**
     * `/api/v1/posts/{id}` -> the v2 domain [Work]. Seasons and episodes are built from the
     * prints' own coverage, exactly as `catalog_v2._project_pages` does it: the episode tree
     * is whatever the releases name, and a season pack contributes a season but NO episodes
     * (gap G-2 — the server cannot enumerate a pack's episodes either).
     */
    fun work(detail: PostDetail): Work {
        val workType = WorkType.fromContentType(detail.contentType, detail.isAnimated)
        val family = if (workType.isServerSeriesType) "series" else "movie"
        val prints = detail.releases.map { toPrint(it, workType) }

        // Season/episode tree, from the prints. Keyed like the projector: (season, episode).
        val episodesBySeason = linkedMapOf<Int, MutableMap<Int, Episode>>()
        val seasonNumbers = sortedSetOf<Int>()
        for (release in detail.releases) {
            val descriptor = ReleaseLabelParsing.describe(release, workType)
            val season = descriptor.coverageSeason
            if (family == "series" || season > 0) seasonNumbers.add(season)
            when (descriptor.coverageType) {
                CoverageType.SINGLE_EPISODE -> {
                    val number = descriptor.episode
                    if (number > 0) {
                        episodesBySeason.getOrPut(season) { linkedMapOf() }[number] = Episode(
                            seasonNumber = season,
                            number = number,
                        )
                    }
                }
                CoverageType.EPISODE_RANGE -> {
                    val (lo, hi) = ReleaseLabelParsing.parseRange(descriptor.episodeRange)
                    if (lo > 0) {
                        val upper = if (hi >= lo && hi - lo + 1 <= MAX_ENUMERATED_EPISODES) hi else lo
                        for (number in lo..upper) {
                            episodesBySeason.getOrPut(season) { linkedMapOf() }[number] = Episode(
                                seasonNumber = season,
                                number = number,
                            )
                        }
                    }
                }
                CoverageType.SEASON_PACK, CoverageType.WHOLE_WORK, CoverageType.PARTS,
                CoverageType.UNKNOWN -> Unit
            }
        }

        val seasons = (seasonNumbers + episodesBySeason.keys).sorted().map { number ->
            val eps = episodesBySeason[number].orEmpty().values.sortedBy { it.number }
                .mapIndexed { index, episode -> episode.copy(absoluteNumber = index + 1) }
            Season(
                number = number,
                episodeCount = eps.size,
                episodes = eps,
            )
        }

        return Work(
            workKey = WorkIdentity.workKey(
                cleanTitle = detail.displayTitle,
                year = detail.year,
                workType = workType,
                imdbId = detail.imdbId,
                tmdbId = detail.tmdbId,
            ),
            id = detail.id.toLong(),
            title = detail.displayTitle,
            year = detail.year,
            workType = workType,
            genres = detail.genreList,
            synopsis = detail.synopsis,
            posterUrl = detail.posterUrl,
            backdropUrls = detail.backdropList,
            imdbId = detail.imdbId,
            tmdbId = detail.tmdbId,
            imdbRating = detail.imdbRating,
            country = detail.country,
            industry = detail.industry,
            language = detail.language,
            seasons = seasons,
            prints = prints,
            entitlements = listOf(Entitlement.freeDefault),
            flags = if (workType == WorkType.UNKNOWN) listOf(WorkFlag.IDENTITY_SUSPECT) else emptyList(),
            bestQualityScore = prints.maxOfOrNull { it.qualityScore } ?: 0,
            linkCount = prints.sumOf { it.links.size },
            streamableCount = prints.sumOf { print -> print.links.count { it.assessment.canStream } },
        )
    }

    /** One v1 release row -> one [Print] (both axes filled from their own source of truth). */
    fun toPrint(release: ReleaseDetail, workType: WorkType? = null): Print {
        val descriptor = ReleaseLabelParsing.describe(release, workType)
        return Print(
            id = release.id.toLong(),
            label = release.releaseTitle.orEmpty(),
            seasonNumber = ReleaseLabelParsing.seasonOf(descriptor),
            coverage = descriptor.coverageType,
            episodeRange = descriptor.episodeRange,
            descriptor = descriptor,
            links = release.sources.map { toLink(it, release.id.toLong()) },
            // NOT SERVED YET: the public release view has no timestamp column.
            createdAt = null,
        )
    }

    /**
     * One served link row -> one [MediaLink]. The row carries our opaque `stream_id` and our
     * own `play_url`, plus our own classification; there is nothing here to translate into a
     * hoster name because the wire has none.
     */
    fun toLink(source: SourceDetail, printId: Long? = null): MediaLink {
        val assessment = LinkClassification.classify(source)
        return MediaLink(
            streamId = source.streamId,
            playUrl = source.bestUrl,
            label = source.label,
            id = source.linkId?.toLong(),
            printId = printId,
            assessment = assessment,
            score = LinkClassification.rankOf(source),
            // The score above was produced on the client from the projection's own rule; it
            // is labelled so nobody compares it against `link_health`'s measured scale.
            scoreScale = ScoreScale.CLIENT_V1_PRIOR,
            sizeBytes = source.fileSizeBytes ?: source.sizeBytes,
            httpStatus = source.httpStatus,
            mimeType = source.mimeType,
            resumable = source.isResumableLink,
            expiresAt = source.expiresAt,
            lastEvidenceAt = source.lastEvidenceAt,
        )
    }

    /**
     * Builds the play decision for one link from v1 data.
     *
     * // NOT SERVED YET - needs /api/v2/play (see EndpointGaps.PLAY): the server does not
     * // rank, so the client ranks with the projection's own formula.
     * The bundle's `expiresAt` is null on purpose: only `/api/v1/stream` produces a live URL
     * and it does not report a TTL, so the client must treat every resolved URL as
     * possibly-rotten — which is what [PlaybackRecovery] exists for.
     */
    fun playBundle(detail: PostDetail, releaseId: Int, streamId: String): PlayBundle {
        val domainWork = work(detail)
        val print = domainWork.prints.firstOrNull { it.id == releaseId.toLong() }
            ?: domainWork.prints.firstOrNull()
        val selected = print?.links?.filter { it.streamId == streamId } ?: print?.links
        val renditions = (selected ?: emptyList())
            .filter { it.canonical }
            .sortedByDescending { it.score }
            .map { rendition ->
                Rendition(
                    linkId = rendition.id,
                    streamId = rendition.streamId,
                    playUrl = rendition.addressableUrl,
                    label = rendition.label,
                    protocol = rendition.assessment.protocol,
                    playability = rendition.assessment.playability,
                    qualityLabel = print?.descriptor?.qualityLabel.orEmpty(),
                    qualityScore = print?.qualityScore ?: 0,
                    linkScore = rendition.score,
                    scoreScale = rendition.scoreScale,
                    ephemeral = rendition.assessment.ephemeral,
                )
            }
        return PlayBundle(
            workKey = domainWork.workKey,
            printId = print?.id,
            renditions = renditions,
            entitlement = domainWork.entitlements.firstOrNull() ?: Entitlement.freeDefault,
        )
    }

    /**
     * A `/api/v1/stream?id=<handle>&redirect=0` answer folded back into a [Rendition]. The
     * public answer names no URL — the address a client plays is the redirector it already
     * has — so this only refreshes the *measured* facts about the handle (mime, size,
     * resumability, expiry) and re-derives the protocol from the mime the redirector reported.
     */
    fun resolvedRendition(source: SourceDetail, stream: StreamResponse): Rendition {
        val mime = stream.mimeType?.lowercase().orEmpty()
        val isHls = LinkClassification.isHls(stream.mimeType, source.bestUrl) ||
            mime.contains("mpegurl")
        val playable = stream.streamId != null && source.bestUrl != null
        return Rendition(
            linkId = source.linkId?.toLong(),
            streamId = stream.streamId ?: source.streamId,
            playUrl = source.bestUrl,
            label = source.label,
            protocol = if (isHls) PlayProtocol.HLS else PlayProtocol.PROGRESSIVE,
            playability = if (playable) Playability.STREAM else Playability.NONE,
            qualityLabel = "",
            ephemeral = stream.expiresIn != null || source.isEphemeral,
        )
    }

    /**
     * `catalog_v2._covered_episodes` caps how many episodes one label may create, so a
     * "S01E(01-1000)" batch label cannot fabricate a thousand rows.
     */
    private const val MAX_ENUMERATED_EPISODES = 100

}
