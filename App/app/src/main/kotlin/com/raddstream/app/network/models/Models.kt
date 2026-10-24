package com.raddstream.app.network.models

import com.google.gson.annotations.SerializedName

/*
 * ─────────────────────────────────────────────────────────────────────────────
 *  v1 WIRE MODELS — a field-by-field map of what the server ACTUALLY serialises.
 * ─────────────────────────────────────────────────────────────────────────────
 * Ground truth (verified 2026-10-22 against `Fast_Fetch/viewer.py` + `fast_fetch.py`
 * and against a live `Fast_Fetch/multimovies.db`):
 *
 *  GET /api/v1/posts            → [PostsResponse]            (the served list view)
 *  GET /api/v1/posts/{id}       → [PostDetailResponse]       (post view + `releases[]`,
 *                               each release with `sources[]` projected by the link view)
 *  GET /api/v1/stream           → [StreamResponse]           (our own redirector, `redirect=0`)
 *  GET /api/v1/stats            → [StatsResponse]            (scale only, no per-site rows)
 *
 * Those four are the ENTIRE served surface. There is no `/api/v1/sync`, no
 * `/api/v2` endpoint at all, and the public answers carry NO source-site, hoster or upstream
 * URL anywhere — the redaction stops at the HTTP edge, so a key that is not here cannot be
 * rendered by this app by accident. `/api/v1/rules` is operator-only (loopback) and 404s
 * publicly, so this client must never try to unwrap a bridge itself. Every v2 type in this
 * package is a target contract, not a live endpoint (see [V2Wire] and [EndpointGaps]).
 *
 * Rules these models obey:
 *  1. A field exists only if the server sends that key. Where v1 ships free TEXT
 *     (`season`, `episode`, `quality`) the structured value is a documented DERIVATION
 *     computed by [ReleaseLabelParsing] — never a phantom `@SerializedName`.
 *  2. JSON type == Kotlin type. Numeric-or-text columns use the lenient adapters in
 *     `RaddGson.kt` (see its KDoc for why `is_temporary` is 0/1 on one endpoint and a
 *     boolean on another).
 *  3. Unknown keys are ignored by Gson, so an additive server change can never crash
 *     decoding (API_V2.md §16.6).
 *  4. Adult policy (App/AGENTS.md, API_V2.md §13): `is_18_plus` is deliberately NOT
 *     modelled anywhere in this app. The server filters at the SQL level and answers
 *     404 for a flagged id; the client neither reads, stores, renders nor requests the
 *     flag. `is_animated` is unrestricted metadata and IS modelled.
 */

/** Exact response of GET /api/v1/posts. `page`/`limit`/`total`/`total_pages` are always JSON ints. */
data class PostsResponse(
    val page: Int = 1,
    val limit: Int = 20,
    val total: Int = 0,
    @SerializedName("total_pages")
    val totalPages: Int = 1,
    val results: List<Post> = emptyList(),
)

/** One catalog row of GET /api/v1/posts (the served `post_brief` view: identity + title fields + counts). */
data class Post(
    val id: Int,
    val title: String,
    @SerializedName("clean_title")
    val cleanTitle: String? = null,
    /** `posts.year` — INTEGER affinity, so JSON number or null (a text year decodes to null). */
    val year: Int? = null,
    /**
     * `posts.content_type` — the ONLY values `classify_media()` ever writes are
     * `movie | series | complete_season | ongoing_season`. `?type=anime` is accepted by
     * the route but matches no row, so it must never be offered as a filter (see
     * [WorkType.fromContentType] for the anime truth: `is_animated`).
     */
    @SerializedName("content_type")
    val contentType: String? = null,
    /** `posts.seasons` — free TEXT ("2", "S01–S03"), nullable. */
    val seasons: String? = null,
    @SerializedName("poster_url")
    val posterUrl: String? = null,
    /** `posts.imdb_rating` is TEXT in the ledger ("6.9", "8"), not a JSON number. */
    @SerializedName("imdb_rating")
    val imdbRating: String? = null,
    @SerializedName("imdb_id")
    val imdbId: String? = null,
    @SerializedName("tmdb_id")
    val tmdbId: Int? = null,
    /** TEXT; in practice either CSV ("Action, Drama") or a JSON-array string ("[\"A, B\"]"). */
    val genres: String? = null,
    val industry: String? = null,
    val country: String? = null,
    val language: String? = null,
    @SerializedName("release_count")
    val releaseCount: Int? = null,
    @SerializedName("source_count")
    val sourceCount: Int? = null,
) {
    /** Display helper so UI never has to know that `year` is numeric on the wire. */
    val yearLabel: String? get() = year?.toString()
    val genreList: List<String> get() = WireText.listOf(genres)
    val displayTitle: String get() = cleanTitle?.takeIf { it.isNotBlank() } ?: title
}

/** Response of GET /api/v1/posts/{id}. Unknown id or an adult-flagged id → 404 + `success:false`. */
data class PostDetailResponse(
    val success: Boolean = false,
    val data: PostDetail? = null,
    val error: String? = null,
)

/** The raw `posts` row as the public may see it, plus its `releases`. */
data class PostDetail(
    val id: Int,
    val title: String,
    @SerializedName("clean_title")
    val cleanTitle: String? = null,
    val year: Int? = null,
    @SerializedName("content_type")
    val contentType: String? = null,
    val seasons: String? = null,
    @SerializedName("poster_url")
    val posterUrl: String? = null,
    /** TEXT holding a JSON array of URL strings (no width/kind metadata — API_V2.md §14). */
    @SerializedName("backdrop_urls")
    val backdropUrls: String? = null,
    @SerializedName("imdb_rating")
    val imdbRating: String? = null,
    @SerializedName("imdb_id")
    val imdbId: String? = null,
    @SerializedName("tmdb_id")
    val tmdbId: Int? = null,
    val genres: String? = null,
    val synopsis: String? = null,
    /** `posts.is_animated` INTEGER 0/1 — metadata, not a restricted flag. */
    @SerializedName("is_animated")
    val isAnimated: Boolean? = null,
    val industry: String? = null,
    val country: String? = null,
    val language: String? = null,
    val releases: List<ReleaseDetail> = emptyList(),
    /**
     * The server's collapsed quality ladder, one group per season/episode scope
     * (see [OptionGroup]). The quality switch and the download card read THIS, not
     * the raw `releases[].sources[]`, so one rung means one row to the viewer.
     */
    @SerializedName("option_groups")
    val optionGroups: List<OptionGroup> = emptyList(),
) {
    val yearLabel: String? get() = year?.toString()
    val genreList: List<String> get() = WireText.listOf(genres)
    val backdropList: List<String> get() = WireText.listOf(backdropUrls)
    val displayTitle: String get() = cleanTitle?.takeIf { it.isNotBlank() } ?: title
}

/**
 * One `releases` row, exactly as the public view projects it:
 * `id, post_id, release_title, season, episode, quality, codec, size, languages`
 * + the joined, already-projected `sources` (see [SourceDetail]).
 *
 * PHANTOM FIELDS REMOVED (they mapped keys the API never returns, so they were
 * permanently null and silently killed season/episode grouping — App/AGENTS.md §6):
 *   `season_number`, `episode_number`, `episode_title`, `resolution`, `audio`.
 * The first two and `resolution`/`audio` are now DERIVATIONS of columns that do exist
 * (`season`, `episode`, `quality`+`release_title`, `languages`); `episode_title` has no
 * server counterpart at all, so it is gone and [releaseTitle] is the honest label.
 *
 * PROVENANCE FIELDS ARE ABSENT ON PURPOSE: `source_site`, `origin_url`, `intermediate_url`
 * and `created_at` are not in the served view any more, so no UI can render them by
 * accident and no test can pin them back into existence.
 */
data class ReleaseDetail(
    val id: Int,
    @SerializedName("post_id")
    val postId: Int? = null,
    @SerializedName("release_title")
    val releaseTitle: String? = null,
    /** Free TEXT: "S01", "1", "Batch", null — see [seasonNumber]. */
    val season: String? = null,
    /** Free TEXT: "E01", "1", null — see [episodeNumber]. */
    val episode: String? = null,
    /** Free TEXT quality rung label ("1080p", "HDTS", "720p WEB-DL"). */
    val quality: String? = null,
    val codec: String? = null,
    /** Free TEXT size label ("2.4GB"); [sizeBytes] parses it. */
    val size: String? = null,
    /** Audio languages of the print (TEXT, e.g. "English" or "Hindi|Tamil"). */
    val languages: String? = null,
    val sources: List<SourceDetail> = emptyList(),
) {
    /**
     * The print descriptor (coverage, season, episode range, score) — the honest v1 view.
     *
     * NOT cached on purpose: Gson instantiates these models via `Unsafe` when there is no
     * no-arg constructor, and a `by lazy` delegate would then be null at first access.
     * Callers that need several fields should read this ONCE and reuse the descriptor —
     * the derived getters below each parse the label again, which is fine for one release
     * and wasteful in a list (see docs/HANDOFF_appnet.md for the UI-side adoption).
     */
    val printDescriptor: PrintDescriptor get() = ReleaseLabelParsing.describe(this)

    /** Parsed from [season] then the label. null = the server never said which season. */
    val seasonNumber: Int? get() = ReleaseLabelParsing.seasonOf(printDescriptor)

    /**
     * Parsed from [episode] then the label. null for a pack/whole-season file — which is the
     * truth, not missing data: see [printDescriptor]'s `coverageType`.
     */
    val episodeNumber: Int? get() = ReleaseLabelParsing.episodeOf(printDescriptor)

    /**
     * The print axis, as the server would name it: the resolution rung found in
     * `quality` + `release_title` ("1080p"), or null when the label names none.
     * Re-points the old phantom `resolution` key.
     */
    val resolution: String? get() = ReleaseLabelParsing.resolutionOf(printDescriptor)

    /** Re-points the old phantom `audio` key: v1's audio languages live in `languages`. */
    val audio: String? get() = languages

    /** Parsed from the `size` column, else from the label. null = no byte figure anywhere. */
    val sizeBytes: Long? get() = ReleaseLabelParsing.sizeBytesOf(printDescriptor)

    /**
     * Links of this print, best-first. When the server publishes `rank_score` on a link that
     * is used as-is; otherwise [LinkClassification.rankOf] derives the same score from our own
     * classification (`kind`/`playability`/`tier`/`state`) — never from a hoster name, which
     * is no longer on the wire.
     */
    val rankedSources: List<SourceDetail>
        get() = sources.sortedWith(
            compareByDescending<SourceDetail> { LinkClassification.rankOf(it) }
                .thenByDescending { if (it.status == "active") 1 else 0 }
                .thenBy { it.streamId },
        )
}

/**
 * One link of one print, as the public may see it — the served `link_view`.
 *
 * There is deliberately NO hoster name, NO service slug, NO source/origin/final URL and no
 * raw ledger `id` in this shape: the server projects them away before the response leaves it
 * (`Fast_Fetch/redact.py` `VIEWS["link"]`), and what it publishes instead is
 *  - [streamId] — an opaque signed handle, the only key the client has for the link, and
 *  - [playUrl] — OUR OWN `/api/v1/stream?id=<handle>` redirector, which answers a 302 to the
 *    bytes when it can and never tells anyone who hosts them.
 * Everything else here describes OUR behaviour (kind, playability, ephemerality, resumability,
 * measured http status, size, mime), which is exactly what a player needs and nothing of what
 * a provenance surface could show.
 *
 * [kind] is the server's own vocabulary — `direct | resolve | download | external` — where
 * `external` means "only a page outside this app can present it". The client maps that to an
 * honest download-only offer labelled "Not playable here"; it never opens one.
 */
data class SourceDetail(
    @SerializedName("stream_id")
    val streamId: String = "",
    @SerializedName("play_url")
    val playUrl: String? = null,
    @SerializedName("link_id")
    val linkId: Int? = null,
    @SerializedName("release_id")
    val releaseId: Int? = null,
    /** Ours: "Fast direct" when the link resumes, else "Standard". Never a hoster name. */
    val label: String? = null,
    /** Ours: `direct | resolve | download | external`. */
    val kind: String? = null,
    /** Ours: `stream | download | both | resolve_required | none` (the served classification). */
    val playability: String? = null,
    /** Ours: `hls | progressive | dash | html | unknown`. */
    val protocol: String? = null,
    /** Ours: `container` of the file we would hand over, when measured. */
    val container: String? = null,
    /** Server-written scrape status: `active | dead | expired`. */
    val status: String? = null,
    val state: String? = null,
    val playable: Boolean? = null,
    val downloadable: Boolean? = null,
    /** INTEGER 0/1 here (a JSON number) but a real boolean on /api/v1/stream — [LenientBooleanAdapter] accepts both. */
    @SerializedName("is_temporary")
    val isTemporary: Boolean? = null,
    @SerializedName("is_resumable")
    val isResumable: Boolean? = null,
    val resumable: Boolean? = null,
    val ephemeral: Boolean? = null,
    @SerializedName("http_status")
    val httpStatus: Int? = null,
    @SerializedName("file_size_bytes")
    val fileSizeBytes: Long? = null,
    @SerializedName("size_bytes")
    val sizeBytes: Long? = null,
    @SerializedName("mime_type")
    val mimeType: String? = null,
    @SerializedName("rank_score")
    val rankScore: Int? = null,
    @SerializedName("tier")
    val tier: Int? = null,
    @SerializedName("latency_ms")
    val latencyMs: Int? = null,
    @SerializedName("speed_mbps")
    val speedMbps: Double? = null,
    @SerializedName("last_evidence_at")
    val lastEvidenceAt: String? = null,
    @SerializedName("expires_at")
    val expiresAt: Double? = null,
) {
    /**
     * The only URL the player may be handed: OUR OWN redirector. A link with no `play_url`
     * has nothing to play — the raw upstream address is not on this model any more, so there
     * is nothing else it could fall back to.
     */
    val bestUrl: String?
        get() = playUrl?.trim()?.takeIf { WireText.isHttpUrl(it) }

    /** What this link *is* and what a client can do with it (link axis, [LinkKind]). */
    val classification: LinkAssessment
        get() = LinkClassification.classify(this)

    val isEphemeral: Boolean get() = isTemporary == true || ephemeral == true
    val isResumableLink: Boolean get() = isResumable == true || resumable == true
    val isDead: Boolean get() = status == "dead" || status == "expired" || state == "dead"
}

/**
 * GET /api/v1/stream?id=<handle>&redirect=0 → the public answer of our own redirector.
 *
 * The public view of this endpoint carries NO url at all: `redirect=1` answers a bare 302 and
 * the player follows it, so a client that wants bytes never needs to read a body, and a client
 * that reads the body gets only OUR classification. Addressing a playback is therefore
 * structural: [streamHandle] + our base URL, never a served media address.
 *
 * `redirect=0` keys (verified against the served view): `success, stream_id, kind, mime_type,
 * file_size_bytes, resumable, expires_in`, and `error` on the failure paths.
 */
data class StreamResponse(
    val success: Boolean = false,
    @SerializedName("stream_id")
    val streamHandle: String? = null,
    /** Ours: `direct | resolve | download | external`. */
    val kind: String? = null,
    @SerializedName("mime_type")
    val mimeType: String? = null,
    @SerializedName("file_size_bytes")
    val fileSizeBytes: Long? = null,
    val resumable: Boolean? = null,
    /** Seconds our handle stays valid; null = durable. */
    @SerializedName("expires_in")
    val expiresIn: Long? = null,
    val cached: Boolean? = null,
    val refreshed: Boolean? = null,
    val error: String? = null,
) {
    /**
     * The answer is usable when the redirector handed back a handle of ours. There is no URL
     * on this payload to check: the address a client plays is the one it already has,
     * `play_url`, and the 302 behind it either yields bytes or it does not.
     */
    val streamId: String? get() = streamHandle?.takeIf { it.isNotBlank() }?.let { if (success) it else null }

    /** True when the answer is "looked successful but produced nothing usable". */
    val isFalseSuccess: Boolean get() = success && streamId == null

    /** Expiry of the handle in epoch millis, or null when the link is durable. */
    fun expiresAtEpochMillis(nowEpochMillis: Long): Long? =
        if (expiresIn == null) null else nowEpochMillis + expiresIn * 1000L
}

/** GET /api/v1/stats — snake_case exactly as viewer.py:2165-2172 emits them. */
data class StatsResponse(
    val posts: Int = 0,
    val releases: Int = 0,
    val sources: Int = 0,
    @SerializedName("active_sources")
    val activeSources: Int? = null,
    @SerializedName("resumable_sources")
    val resumableSources: Int? = null,
    @SerializedName("temporary_sources")
    val temporarySources: Int? = null,
)
