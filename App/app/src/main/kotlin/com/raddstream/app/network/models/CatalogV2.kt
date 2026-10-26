package com.raddstream.app.network.models

/*
 * ─────────────────────────────────────────────────────────────────────────────
 *  v2 DOMAIN MODEL — the contract the app is built for
 * ─────────────────────────────────────────────────────────────────────────────
 * NOT SERVED YET, for this install: `Fast_Fetch/api_v2.py` now implements the v2 routes and
 * `viewer.py` mounts them, but every one of them requires the `cat_*` projection and the
 * database the public service runs on has none, so a real request answers `unavailable` and
 * the app must stay on v1 until the live catalog is swapped (see `EndpointGaps`).
 * Everything in this file is therefore (a) the shape the app programs
 * against and (b) the shape [V1CatalogMapper] translates the live v1 payload INTO, so the
 * app runs today against the current server and switches source without any UI rewrite.
 *
 * The domain types here are NOT Gson targets — [V2Wire] holds the wire DTOs, and the
 * enums in [CatalogEnums] are only ever built by `fromWire(...)`, never by Gson, so a new
 * server value degrades to UNKNOWN instead of crashing (API_V2.md §15.3, §16.6).
 *
 * Identity rule (API_V2.md §5): `work_key` is the stable key; the numeric `cat_*` ids
 * change on every re-projection, so they are carried for cache lookups only and never
 * persisted as a foreign key by the app.
 */

/**
 * `catalog_v2.work_key_for()`: imdb id, else tmdb id, else `family:normalized-title:year`.
 * Two different works can share a title; a re-scraper cannot change an imdb id, which is
 * why this — not `id` — is the cache/sync key.
 */
object WorkIdentity {

    /** `catalog_v2.normalize_title()`. */
    fun normalizeTitle(title: String?): String {
        var text = title.orEmpty().lowercase()
        text = BRACKETS_RE.replace(text, " ")
        text = NON_WORD_RE.replace(text, " ")
        return text.split(' ').filter { it.isNotEmpty() }.joinToString(" ")
    }

    /**
     * Port of `work_key_for()`. `null`/blank imdb id and null/0 tmdb id both fall through,
     * exactly as the Python does. `year` of null becomes the literal "ny" ("no year").
     *
     * Difference noted honestly: Python's `\w` is Unicode-aware, Kotlin's default
     * `[^\w\s]` is not, so a Devanagari title keeps its letters here where the server would
     * too — the ASCII case (all ledger titles today) is identical.
     */
    fun workKey(cleanTitle: String?, year: Int?, workType: WorkType, imdbId: String?, tmdbId: Int?): String {
        if (!imdbId.isNullOrBlank()) return "imdb:$imdbId"
        if (tmdbId != null && tmdbId != 0) return "tmdb:$tmdbId"
        val normalized = normalizeTitle(cleanTitle).ifEmpty { "unknown" }
        val family = if (workType.isServerSeriesType) "series" else "movie"
        return "$family:$normalized:${year ?: "ny"}"
    }

    private val BRACKETS_RE = Regex("""\[[^]]*]|\([^)]*\)|\{[^}]*}""")
    private val NON_WORD_RE = Regex("""[^\p{L}\p{N}_\s]""")
}

/** `cat_works` + the rollups `_finalize` computes. */
data class Work(
    val workKey: String,
    val id: Long? = null,
    val title: String,
    val originalTitle: String? = null,
    val year: Int? = null,
    val workType: WorkType = WorkType.UNKNOWN,
    val genres: List<String> = emptyList(),
    val synopsis: String? = null,
    val posterUrl: String? = null,
    val backdropUrls: List<String> = emptyList(),
    val imdbId: String? = null,
    val tmdbId: Int? = null,
    val imdbRating: String? = null,
    val country: String? = null,
    val industry: String? = null,
    val language: String? = null,
    val seasons: List<Season> = emptyList(),
    val prints: List<Print> = emptyList(),
    val entitlements: List<Entitlement> = emptyList(),
    val flags: List<WorkFlag> = emptyList(),
    val bestQualityScore: Int = 0,
    val linkCount: Int = 0,
    val streamableCount: Int = 0,
) {
    /** Every episode of the work, season order then episode order. */
    val episodes: List<Episode>
        get() = seasons.flatMap { it.episodes }

    /** True when the work needs an episode picker at all. */
    val isEpisodic: Boolean get() = workType.isSeriesFamily || seasons.isNotEmpty()
}

/** `cat_seasons`. */
data class Season(
    val number: Int,
    val id: Long? = null,
    val year: Int? = null,
    val kind: SeasonType = SeasonType.REGULAR,
    val episodeCount: Int = 0,
    val episodes: List<Episode> = emptyList(),
)

/**
 * `cat_episodes`. An episode is addressable TWO ways, and the app must support both
 * because the backend is: `(season, episode)` for a normal drop, and `absoluteNumber`
 * for daily/anime series where the ledger labels "S01E1072" but the viewer says "1072".
 */
data class Episode(
    val seasonNumber: Int,
    val number: Int,
    val id: Long? = null,
    val absoluteNumber: Int? = null,
    val title: String? = null,
    val stillUrl: String? = null,
    val runtimeMinutes: Int? = null,
    val bestReleaseId: Long? = null,
) {
    /** Both addresses at once, so a caller never has to guess which one the server used. */
    val address: EpisodeAddress get() = EpisodeAddress(seasonNumber, number, absoluteNumber)
}

/** The two addressing schemes, unified. `display` is what the UI shows. */
data class EpisodeAddress(
    val season: Int,
    val episode: Int,
    val absolute: Int? = null,
) {
    val seDisplay: String get() = "S%02dE%02d".format(season, episode)
    val display: String get() = absolute?.let { "Ep $it" } ?: seDisplay

    /** Matches an episode by either scheme — the rule `episode_ranges.py` follows. */
    fun matches(other: EpisodeAddress): Boolean =
        (season == other.season && episode == other.episode) ||
            (absolute != null && absolute == other.absolute)
}

/**
 * `cat_parts` — multi-part films. The projector fills the table from `Part/Chapter/Disc n`
 * labels when one work's prints name two or more parts, so a client reads structure instead
 * of guessing it; a work with no real parts still has no rows (API_V2.md §S4).
 */
data class Part(
    val number: Int,
    val title: String? = null,
    val runtimeMinutes: Int? = null,
)

/**
 * AXIS 1 — one print of a work (`cat_releases`). `qualityScore` is the PRINT score
 * (0..1000) and must never be compared with a [MediaLink] score.
 *
 * No source site and no origin URL: the served print is described by its own label plus the
 * descriptor fields ([PrintDescriptor]) — resolution, source tag, codec, size, languages —
 * which is everything a viewer needs to choose a quality and nothing that names a scrape.
 */
data class Print(
    val id: Long? = null,
    val label: String,
    val seasonNumber: Int? = null,
    val coverage: CoverageType = CoverageType.UNKNOWN,
    val episodeRange: String = "",
    val descriptor: PrintDescriptor,
    val links: List<MediaLink> = emptyList(),
    val createdAt: String? = null,
) {
    val qualityScore: Int get() = descriptor.qualityScore
    val resolution: Resolution get() = descriptor.resolution
    val flags: List<PrintFlag> get() = descriptor.flags

    /** Links of this print that our own player can present, best-first. */
    val playableLinks: List<MediaLink>
        get() = links.filter { it.canonical }.sortedByDescending { it.score }

    /** Links that can be played right now, in-app, from our own address. */
    val streamableLinks: List<MediaLink>
        get() = playableLinks.filter { it.assessment.canStream }

    /** Links that exist but cannot be presented here — offered for keeping, honestly. */
    val keepOnlyLinks: List<MediaLink>
        get() = playableLinks.filterNot { it.assessment.canStream }
}

/**
 * AXIS 2 — one link of one print (`cat_links`). Carries its OWN quality axis so it can
 * never be confused with the print it hangs off.
 *
 * A link is addressed by [streamId] (the opaque handle the server handed out) and [playUrl]
 * (OUR OWN `/api/v1/stream?id=<handle>` redirector). There is no upstream URL on this type:
 * the client never learns, stores or renders one, so a failover or an external hand-off
 * cannot leak it.
 */
data class MediaLink(
    val streamId: String = "",
    val playUrl: String? = null,
    val label: String? = null,
    val id: Long? = null,
    val printId: Long? = null,
    val assessment: LinkAssessment,
    val score: Int = 0,
    val scoreScale: ScoreScale = ScoreScale.PROJECTION_PRIOR,
    val sizeBytes: Long? = null,
    val httpStatus: Int? = null,
    val mimeType: String? = null,
    val resumable: Boolean = false,
    val expiresAt: Double? = null,
    val lastEvidenceAt: String? = null,
) {
    /** A link with no handle of ours is not a link; it is still modelled, never dropped. */
    val canonical: Boolean get() = assessment.kind != LinkKind.DEAD_END

    /** Our own playable address, and only when the link really has one. */
    val addressableUrl: String? get() = playUrl?.takeIf { WireText.isHttpUrl(it) }
}

/** `cat_entitlements`. Only FREE rows exist today; the rest is the contract they will use. */
data class Entitlement(
    val model: EntitlementModel = EntitlementModel.FREE,
    val ownership: Ownership = Ownership.PERMANENT,
    val priceMinor: Int? = null,
    val currency: String? = null,
    val offers: List<String> = emptyList(),
    val note: String? = null,
) {
    companion object {
        /** The only entitlement the live server implies for every catalog row today. */
        val freeDefault = Entitlement(EntitlementModel.FREE, Ownership.PERMANENT)
    }
}

/** What the server says the work currently is, per print. */
data class Availability(
    val streamable: Boolean,
    val downloadable: Boolean,
    val linkCount: Int,
    val bestPrintId: Long? = null,
)

/** `GET /browse` row: a work plus the one print the surface would default to. */
data class BrowseItem(
    val workKey: String,
    val title: String,
    val year: Int? = null,
    val workType: WorkType = WorkType.UNKNOWN,
    val posterUrl: String? = null,
    val imdbRating: String? = null,
    val releaseCount: Int = 0,
    val sourceCount: Int = 0,
    val bestQualityScore: Int = 0,
)

/* ── playback (API_V2.md §8) — shapes only; every one of these is NOT SERVED YET ── */

/** `/api/v2/play` answer: everything needed to start one session, already ranked. */
data class PlayBundle(
    val workKey: String,
    val printId: Long? = null,
    val episodeAddress: EpisodeAddress? = null,
    val renditions: List<Rendition> = emptyList(),
    val entitlement: Entitlement = Entitlement.freeDefault,
    val expiresAt: Double? = null,
    val ttlSeconds: Int? = null,
) {
    /** The bundle the server would have picked; empty when nothing is playable. */
    val primary: Rendition? get() = renditions.firstOrNull()
}

/** One playable option inside a bundle: our own address plus how to reach it. */
data class Rendition(
    val linkId: Long? = null,
    val streamId: String? = null,
    /** OUR OWN `/api/v1/stream?id=<handle>` redirector. Never an upstream URL. */
    val playUrl: String? = null,
    val label: String? = null,
    val protocol: PlayProtocol = PlayProtocol.UNKNOWN,
    val playability: Playability = Playability.UNKNOWN,
    val qualityLabel: String = "",
    val qualityScore: Int = 0,
    val linkScore: Int = 0,
    val scoreScale: ScoreScale = ScoreScale.UNKNOWN,
    val ephemeral: Boolean = false,
    val offsetSeconds: Int = 0,
    val headers: Map<String, String> = emptyMap(),
)

/** What the player should do with a rendition (§8.5). There is exactly one presentation. */
data class PlaybackPlan(
    val rendition: Rendition?,
    val mode: PlaybackMode,
    val problem: ProblemDetails? = null,
)

enum class PlaybackMode {
    /** Our own http(s) or HLS address, straight into Media3 (which follows the 302 itself). */
    DIRECT,

    /**
     * Not presentable in this app: keep it for offline instead, and SAY so. This is what a
     * link the server marks `external`/`download` lands on — there is no WebView path and no
     * silent failure any more.
     */
    DOWNLOAD,

    /** Nothing playable; the UI must show [PlaybackPlan.problem]. */
    NOTHING,
}

/** `/download` option set (§12). NOT SERVED YET. */
data class DownloadOption(
    val linkId: Long? = null,
    val url: String? = null,
    val sizeBytes: Long? = null,
    val resumable: Boolean = false,
    val entitlement: Entitlement = Entitlement.freeDefault,
)

/** Failover policy the client applies when a link dies mid-session (§8.4). */
data class FailurePolicy(
    val maxRetriesPerLink: Int = 1,
    val failoverToNextRendition: Boolean = true,
    val reResolveWhenEphemeral: Boolean = true,
    val reportDeadLinks: Boolean = true,
)

/** One playback attempt, kept so recovery and reporting have an anchor. */
data class PlaySession(
    val workKey: String,
    val printId: Long? = null,
    val address: EpisodeAddress? = null,
    val bundle: PlayBundle? = null,
    val attemptIndex: Int = 0,
    val lastProblem: ProblemDetails? = null,
)

/** RFC 9457 `application/problem+json` (§16.4). Never built by Gson from an enum field. */
data class ProblemDetails(
    val type: String? = null,
    val title: String? = null,
    val status: Int? = null,
    val detail: String? = null,
    val instance: String? = null,
    val code: ProblemCode = ProblemCode.UNKNOWN,
    val errors: List<String> = emptyList(),
) {
    /** §13: an adult-flagged resource answers 404, and the flag is never in the payload. */
    val isNotFound: Boolean get() = status == 404 || code == ProblemCode.NOT_FOUND
}
