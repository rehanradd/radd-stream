package com.raddstream.app.player

import com.google.gson.annotations.SerializedName
import java.net.URI
import java.net.URLEncoder
import com.raddstream.app.network.models.CoverageType
import com.raddstream.app.network.models.LinkAssessment
import com.raddstream.app.network.models.LinkClassification
import com.raddstream.app.network.models.LinkKind
import com.raddstream.app.network.models.Playability
import com.raddstream.app.network.models.SourceDetail

/**
 * Client-side model of the backend **PlayBundle** contract
 * (`Fast_Fetch/API_V2.md` §5 — "an ordered, self-describing failover plan").
 *
 * The same shapes are produced by the v2 `POST /api/v2/play` endpoint and, for the current
 * v1 server, synthesized from the links the catalog already holds with
 * [PlaybackBundle.Companion.forStreamHandle] / [PlaybackBundle.Companion.forCandidates].
 * URL fields are plain strings so this file stays JVM-unit-testable; conversion to `MediaItem`
 * happens in `PlaybackMediaItemFactory.kt`.
 *
 * WHAT A URL FIELD ON THESE TYPES MEANS NOW: it is OUR OWN
 * `<server>/api/v1/stream?id=<handle>` redirector, and nothing else. The upstream address is
 * not on any type in this file, so no player, download, share or external hand-off can be
 * pointed at it — the same-origin guard in [sameOriginPlayUrl] is the second lock.
 *
 * Gson note (mirrors the Models.kt caveats in App/AGENTS.md §6): fields are nullable/defaulted
 * so a *partial* server payload never crashes the player. Unknown enum wire values decode to
 * `UNKNOWN` (API_V2 §10.5 requires clients to tolerate new enum values).
 */

/** Descriptor of the *print* (release) this rendition comes from — `cat_releases` slice. */
data class PrintInfo(
    @SerializedName("label") val label: String? = null,
    @SerializedName("resolution") val resolution: String? = null,
    @SerializedName("source_tag") val sourceTag: String? = null,
    @SerializedName("codec") val codec: String? = null,
    @SerializedName("hdr") val hdr: List<String> = emptyList(),
    @SerializedName("edition") val edition: String? = null,
    @SerializedName("quality_score") val qualityScore: Int = 0,
    @SerializedName("size_bytes") val sizeBytes: Long = 0L,
    @SerializedName("watermarked") val watermarked: Boolean = false,
    @SerializedName("official_print") val officialPrint: Boolean = false,
    /** Audio codecs named by the print (e.g. ["dts","eac3"]) — used for device-capability hints. */
    @SerializedName("audio_codecs") val audioCodecs: List<String> = emptyList(),
) {
    /** Short human label for the top-bar "playing" chip: the quality rung and how it was captured. */
    fun summary(): String {
        val parts = listOfNotNull(
            resolution?.takeIf { it.isNotBlank() && it != "unknown" },
            sourceTag?.takeIf { it.isNotBlank() && it != "unknown" }?.replace('_', ' '),
            codec?.takeIf { it.isNotBlank() && it != "unknown" }?.uppercase(),
        )
        return if (parts.isNotEmpty()) parts.joinToString(" · ") else (label ?: "")
    }

    /**
     * Bitrate language in the viewer's words — the Netflix-style half of the label. Derived
     * from the descriptor fields the backend already ranks on (resolution, capture source,
     * whether the print is an official distribution copy), never from who hosts anything.
     * Null when the print names no resolution, because guessing a quality is worse than
     * saying nothing.
     */
    fun bitrateClass(): String? {
        val rung = resolution?.trim()?.lowercase()?.takeIf { it.isNotEmpty() && it != "unknown" }
            ?: return null
        val tag = sourceTag?.trim()?.lowercase().orEmpty()
        val camCopy = !officialPrint || watermarked || tag in CAM_TAGS
        return when (rung) {
            "2160p", "4k", "uhd" -> if (camCopy) "Standard bitrate" else "High bitrate"
            "1080p", "full hd" -> if (camCopy) "Standard bitrate" else "High bitrate"
            "720p", "hd" -> "Standard bitrate"
            "480p", "sd", "unknown_resolution" -> "Data saver"
            else -> "Standard bitrate"
        }
    }

    /** Quality rung + bitrate class, e.g. "1080p · High bitrate". */
    fun qualityLine(): String =
        listOfNotNull(
            resolution?.takeIf { it.isNotBlank() && it != "unknown" },
            bitrateClass(),
        ).joinToString(" · ")

    private companion object {
        val CAM_TAGS = setOf("cam", "telesync", "telecine", "hdtc", "ppv")
    }
}

/** The concrete playable endpoint and its measured properties (`playback` block of §8.1). */
data class PlaybackInfo(
    /**
     * OUR OWN redirector — `/api/v1/stream?id=<handle>` on the server the app is connected to.
     * Nullable exactly as in the API_V2.md §8.1 annotated example: a rank can carry
     * `"play_url": null` when the link has no address of ours at all. Gson injects explicit
     * JSON nulls regardless of Kotlin nullability, so declaring this non-null would be a lie
     * that NPEs the first blank-check in failover.
     *
     * There is deliberately no field on this type that could hold an upstream URL: the server
     * stopped serving one, the model stopped declaring one, and an unknown JSON key is ignored.
     */
    @SerializedName("play_url") val playUrl: String? = null,
    /** The opaque handle [playUrl] resolves. The only identity a link has on the public edge. */
    @SerializedName("stream_id") val streamId: String? = null,
    /** Ours, in the viewer's words: "Fast direct" | "Standard". Never a hoster name. */
    @SerializedName("label") val label: String? = null,
    /** §8.3: true = this link breaks over cleartext. Never downgrade; skip if https impossible. */
    @SerializedName("requires_https") val requiresHttps: Boolean = false,
    @SerializedName("protocol") val protocol: String? = null, // hls | progressive | dash | html
    @SerializedName("container") val container: String? = null,
    @SerializedName("mime_type") val mimeType: String? = null,
    @SerializedName("http_headers") val httpHeaders: Map<String, String> = emptyMap(),
    // Evidence-based flags, "null until probed" per §8.1 — null means unknown, not yes/no.
    @SerializedName("seekable") val seekable: Boolean? = null,
    @SerializedName("accepts_ranges") val acceptsRanges: Boolean? = null,
    @SerializedName("resumable") val resumable: Boolean = false,
    @SerializedName("cors_open") val corsOpen: Boolean = false,
    @SerializedName("expires_at") val expiresAt: Long? = null, // epoch seconds; null = durable
    @SerializedName("ephemeral") val ephemeral: Boolean = false,
    @SerializedName("score") val score: Int = 0,
    @SerializedName("kind") val kind: String? = null,
    @SerializedName("playability") val playabilityWire: String? = null,
    @SerializedName("drm") val drm: Map<String, String>? = null,
    /**
     * The runner-ups of OUR OWN rung, as handles only (`backup_handles` on the ladder).
     * They are never displayed: they exist so a 403 from one CDN becomes an instant,
     * silent hop at the same quality and the same position instead of an error dialog.
     */
    @SerializedName("backup_handles")
    val backupStreamIds: List<String> = emptyList(),
) {
    fun kindOrUnknown(): LinkKind = LinkKind.fromWire(kind)
    fun playabilityOrUnknown(): Playability = Playability.fromWire(playabilityWire)
    fun isHls(): Boolean =
        protocol?.lowercase() == "hls" || playUrl?.lowercase()?.contains(".m3u8") == true

    /** URL rot guard: expires_at is epoch **seconds** in the wire contract. */
    fun isExpired(nowEpochMillis: Long): Boolean =
        expiresAt != null && nowEpochMillis / 1000L >= expiresAt!!

    /**
     * §8.5: `accepts_ranges:false` (or `seekable:false`) => disable seeking in the UI rather
     * than let ExoPlayer stall. Null = not probed yet -> treated as seekable; the player then
     * learns at runtime and failover narrates any death.
     */
    val effectiveSeekable: Boolean
        get() = seekable != false && acceptsRanges != false

    /** §8.3: cleartext media URL — playable in debug builds only; release blocks it. */
    val isCleartext: Boolean
        get() = playUrl?.startsWith("http://") == true

    /**
     * The address is only usable if it is OUR OWN redirector. Every hand-off in the app checks
     * this, so an upstream URL could not be opened even if one somehow reached this model.
     */
    fun isSameOriginAs(baseUrl: String): Boolean = sameOriginPlayUrl(playUrl, baseUrl)
}

/**
 * True only when [playUrl] is an absolute http(s) address on the SAME host+port as
 * [baseUrl] — the origin the user configured. This is the guard behind every hand-off in the
 * app (external player, download, share): anything else, including a well-meaning upstream
 * URL, is refused.
 */
internal fun sameOriginPlayUrl(playUrl: String?, baseUrl: String): Boolean {
    val target = playUrl?.trim()?.takeIf { it.isNotEmpty() } ?: return false
    val base = baseUrl.trim().takeIf { it.isNotEmpty() } ?: return false
    val targetUri = runCatching { URI(target) }.getOrNull() ?: return false
    val baseUri = runCatching { URI(base) }.getOrNull() ?: return false
    val scheme = targetUri.scheme?.lowercase() ?: return false
    if (scheme != "http" && scheme != "https") return false
    val host = targetUri.host?.lowercase() ?: return false
    val baseHost = baseUri.host?.lowercase() ?: return false
    if (host != baseHost) return false
    val basePort = if (baseUri.port >= 0) baseUri.port else defaultPort(baseUri.scheme)
    val targetPort = if (targetUri.port >= 0) targetUri.port else defaultPort(targetUri.scheme)
    return basePort == targetPort
}

private fun defaultPort(scheme: String?): Int = when (scheme?.lowercase()) {
    "https" -> 443
    "http" -> 80
    else -> -1
}

/**
 * The same redirector addressed by a different handle.
 *
 * A silent failover must not widen what the app is allowed to play, so this only
 * rewrites OUR OWN stream route (`/api/v1/stream?id=<handle>`) and refuses anything
 * else, returning null when the address is not ours to rewrite. The handle is
 * url-encoded on the way in: it is base64-ish noise from the server, and a `+` or
 * `=` in it must not become a query separator.
 */
internal fun streamUrlForHandle(playUrl: String?, handle: String): String? {
    val url = playUrl?.trim()?.takeIf { it.isNotEmpty() } ?: return null
    val candidate = handle.trim()
    if (candidate.isEmpty()) return null
    if (!url.contains(STREAM_ROUTE)) return null
    val encoded = URLEncoder.encode(candidate, "UTF-8")
    val rewritten = url.replaceFirst(Regex("([?&])id=[^&#]*"), "$1id=" + encoded)
    if (rewritten == url) return null
    return rewritten.takeIf { it.contains(STREAM_ROUTE) && it.contains("id=$encoded") }
}

private const val STREAM_ROUTE = "/api/v1/stream"

data class AudioTrackInfo(
    @SerializedName("lang") val language: String? = null,
    @SerializedName("name") val name: String? = null,
    @SerializedName("default") val isDefault: Boolean = false,
    @SerializedName("channels") val channels: String? = null,
    @SerializedName("codec") val codec: String? = null,
)

data class SubtitleTrackInfo(
    @SerializedName("lang") val language: String? = null,
    @SerializedName("kind") val kind: String? = "subtitles",
    @SerializedName("url") val url: String? = null,
    @SerializedName("format") val format: String? = null, // srt | vtt | ass | ssa | ttml
    @SerializedName("default") val isDefault: Boolean = false,
    @SerializedName("forced") val forced: Boolean = false,
)

data class TracksInfo(
    @SerializedName("audio") val audio: List<AudioTrackInfo> = emptyList(),
    @SerializedName("subtitles") val subtitles: List<SubtitleTrackInfo> = emptyList(),
)

/** One covered episode with its learned in-file start (`cat_release_episodes` row). */
data class EpisodeCoverage(
    // Defaulted so Gson can construct every PlayBundle class via its synthesized no-arg
    // constructor (all-defaulted params) and never fall back to Unsafe allocation, which
    // would leave non-nullable collection fields null on partial payloads.
    @SerializedName("number") val number: Int = 0,
    @SerializedName("offset_seconds") val offsetSeconds: Int? = null,
    @SerializedName("chapter_title") val chapterTitle: String? = null,
)

/** Coverage block of a rendition: which episodes the file holds and where they start. */
data class Coverage(
    @SerializedName("type") val typeWire: String? = null,
    @SerializedName("season") val season: Int = 0,
    @SerializedName("ordinal") val ordinal: Int = 0,
    @SerializedName("offset_seconds") val offsetSeconds: Int? = null,
    @SerializedName("needs_offset_calibration") val needsOffsetCalibration: Boolean = false,
    @SerializedName("pack_warning") val packWarning: String? = null,
    @SerializedName("first_episode") val firstEpisode: Int = 0,
    @SerializedName("last_episode") val lastEpisode: Int = 0,
    @SerializedName("episodes") val episodes: List<EpisodeCoverage> = emptyList(),
) {
    fun type(): CoverageType = CoverageType.fromWire(typeWire)

    /** The file holds more than one episode → position = offset of the requested one. */
    fun isPacked(): Boolean =
        type() == CoverageType.SEASON_PACK || type() == CoverageType.EPISODE_RANGE

    /** Offset for a specific episode, from the server-provided chapter data only. */
    fun serverOffsetFor(episodeNumber: Int): Int? = when {
        type() == CoverageType.SINGLE_EPISODE || type() == CoverageType.WHOLE_WORK -> 0
        type() == CoverageType.EPISODE_RANGE || type() == CoverageType.SEASON_PACK ->
            episodes.firstOrNull { it.number == episodeNumber }?.offsetSeconds
                ?: offsetSeconds.takeIf { episodeNumber == ordinal }
        else -> offsetSeconds
    }
}

/** One ranked candidate inside the bundle (§5 `renditions[]`). */
data class PlaybackRendition(
    @SerializedName("rank") val rank: Int = 0,
    @SerializedName("release_id") val releaseId: Int = 0,
    @SerializedName("print") val print: PrintInfo = PrintInfo(),
    @SerializedName("playback") val playback: PlaybackInfo = PlaybackInfo(),
    @SerializedName("tracks") val tracks: TracksInfo = TracksInfo(),
    @SerializedName("coverage") val coverage: Coverage = Coverage(),
) {
    /**
     * Display label used everywhere the player must say *what settled* — quality and bitrate
     * language only ("1080p · High bitrate · Fast direct"), because that is all the viewer can
     * act on and all the server is willing to say.
     */
    fun displayLabel(): String {
        val quality = print.qualityLine().ifBlank { print.summary() }
        return listOfNotNull(
            quality.takeIf { it.isNotBlank() },
            playback.label?.takeIf { it.isNotBlank() },
        ).distinct().joinToString(" · ").ifBlank { "Rank #$rank" }
    }

    /** The honest sentence for a candidate this app cannot present: said out loud, never hidden. */
    fun notPlayableHere(): Boolean = !playback.playabilityOrUnknown().isDirectlyPlayable
}

data class PlaybackDownloadOption(
    @SerializedName("release_id") val releaseId: Int = 0,
    /** Ours, again: the same redirector address, kept instead of streamed. */
    @SerializedName("play_url") val playUrl: String = "",
    @SerializedName("stream_id") val streamId: String? = null,
    @SerializedName("kind") val kindWire: String? = null,
    @SerializedName("resumable") val resumable: Boolean = false,
    @SerializedName("size_bytes") val sizeBytes: Long = 0L,
    @SerializedName("score") val score: Int = 0,
    @SerializedName("expires_at") val expiresAt: Long? = null,
) {
    fun kind(): LinkKind = LinkKind.fromWire(kindWire)
    /** API_V2 §5: only resumable options may be offered for offline save. */
    fun offerableForKeep(): Boolean =
        resumable && kind().wire in setOf("cdn_direct", "hls_manifest", "download_only") &&
            playUrl.isNotBlank()
}

/** §5 `failure_policy` — client-mandated failover parameters. */
data class PlaybackFailurePolicy(
    @SerializedName("retry_same") val retrySame: Int = 1,
    @SerializedName("then_next_rank") val thenNextRank: Boolean = true,
    @SerializedName("max_ranks") val maxRanks: Int = 3,
    @SerializedName("report_url") val reportUrl: String? = null,
    @SerializedName("backoff_ms") val backoffMs: Long = 800L,
)

data class SessionInfo(
    @SerializedName("id") val id: String? = null,
    @SerializedName("issued_at") val issuedAt: Long? = null,
    @SerializedName("expires_in") val expiresIn: Long? = null, // seconds
    @SerializedName("strategy") val strategy: String? = "failover",
) {
    fun expiresAtEpochMillis(nowEpochMillis: Long): Long? =
        if (issuedAt == null || expiresIn == null) null
        else (issuedAt + expiresIn) * 1000L
}

data class PlayTarget(
    @SerializedName("kind") val kind: String? = "work", // work | release | episode
    @SerializedName("id") val id: Int = 0,
    @SerializedName("work_key") val workKey: String? = null,
    @SerializedName("work_type") val workType: String? = null,
    @SerializedName("season") val season: Int = 0,
    @SerializedName("episode") val episode: Int = 0,
    @SerializedName("episode_id") val episodeId: Int? = null,
    @SerializedName("part") val part: Int = 0,
)

/**
 * The whole failover plan handed to the player. Ordered candidate links = [renditions].
 */
data class PlaybackBundle(
    @SerializedName("session") val session: SessionInfo = SessionInfo(),
    @SerializedName("target") val target: PlayTarget = PlayTarget(),
    @SerializedName("renditions") val renditions: List<PlaybackRendition> = emptyList(),
    @SerializedName("download_options") val downloadOptions: List<PlaybackDownloadOption> = emptyList(),
    @SerializedName("failure_policy") val failurePolicy: PlaybackFailurePolicy = PlaybackFailurePolicy(),
) {
    /** Session-level expiry — never persist or replay a bundle beyond its lifetime (§5). */
    fun isStale(nowEpochMillis: Long): Boolean =
        session.expiresAtEpochMillis(nowEpochMillis)?.let { nowEpochMillis >= it } ?: false

    val isEmpty: Boolean get() = renditions.none { !it.playback.playUrl.isNullOrBlank() }

    /** True when nothing in this plan can be presented here — the UI must say so, not stall. */
    val hasNothingPlayable: Boolean get() = renditions.none { it.playback.playabilityOrUnknown().isDirectlyPlayable }

    companion object {

        /**
         * Bundle for the navigation path in `NavGraph.kt` (`player/{streamId}/{title}`): one
         * handle of ours, classified by the single server-shaped rule in [LinkClassification],
         * addressed by our own redirector. [backupHandles] come from the ladder the detail
         * screen already holds (staged through [PlayerSessionStore.stageFailover]), so the route
         * stays a single opaque handle while a silent same-quality hop is still possible.
         */
        fun forStreamHandle(
            streamId: String,
            playUrl: String,
            title: String,
            label: String? = null,
            kind: String? = null,
            mimeType: String? = null,
            resumable: Boolean = false,
            ephemeral: Boolean = false,
            backupHandles: List<String> = emptyList(),
        ): PlaybackBundle {
            val classified = LinkClassification.classify(
                SourceDetail(
                    streamId = streamId,
                    playUrl = playUrl,
                    label = label,
                    kind = kind,
                    mimeType = mimeType,
                    isResumable = resumable,
                    isTemporary = ephemeral,
                ),
            )
            return PlaybackBundle(
                session = SessionInfo(id = "v1-$title".hashCode().toString(16)),
                target = PlayTarget(kind = "work", id = 0),
                renditions = listOf(
                    PlaybackRendition(
                        rank = 1,
                        print = PrintInfo(label = title),
                        playback = PlaybackInfo(
                            playUrl = playUrl,
                            streamId = streamId,
                            label = label,
                            kind = classified.kind.wire,
                            playabilityWire = classified.playability.wire,
                            mimeType = mimeType,
                            resumable = resumable,
                            ephemeral = ephemeral,
                            protocol = classified.protocol.wire,
                            backupStreamIds = backupHandles.filter { it.isNotBlank() },
                        ),
                    ),
                ),
            )
        }

        /**
         * Bundle from the *ordered* candidates the detail screen already holds, ranked the way
         * §3 of API_V2 demands: presentable here first, durable handles before ephemeral ones,
         * then the server's own link score, otherwise input order preserved.
         */
        fun forCandidates(
            title: String,
            candidates: List<StreamCandidate>,
        ): PlaybackBundle {
            val ranked = candidates
                .map { c ->
                    val classified = LinkClassification.classify(
                        SourceDetail(
                            streamId = c.streamId,
                            playUrl = c.playUrl,
                            label = c.label,
                            kind = c.kind,
                            playability = c.playability,
                            protocol = c.protocol,
                            mimeType = c.mimeType,
                            isResumable = c.resumable,
                            isTemporary = c.ephemeral,
                            status = c.status,
                            tier = c.tier,
                            rankScore = c.score,
                        ),
                    )
                    Triple(
                        c,
                        classified,
                        classified.playability.isDirectlyPlayable && c.playUrl.isNotBlank(),
                    )
                }
                .sortedWith(
                    compareByDescending<Triple<StreamCandidate, LinkAssessment, Boolean>> { it.third }
                        .thenByDescending { LinkClassification.rankScore(it.second) }
                        .thenBy { it.first.ephemeral },
                )
                .mapIndexed { index, (candidate, cls, _) ->
                    PlaybackRendition(
                        rank = index + 1,
                        releaseId = candidate.releaseId,
                        print = candidate.print.takeIf { it != PrintInfo() }
                            ?: PrintInfo(label = candidate.printLabel ?: title),
                        playback = PlaybackInfo(
                            playUrl = candidate.playUrl.takeIf { it.isNotBlank() },
                            streamId = candidate.streamId,
                            label = candidate.label,
                            kind = cls.kind.wire,
                            playabilityWire = cls.playability.wire,
                            mimeType = candidate.mimeType,
                            resumable = candidate.resumable,
                            ephemeral = candidate.ephemeral,
                            protocol = cls.protocol.wire,
                            score = candidate.score,
                        ),
                    )
                }
            return PlaybackBundle(
                session = SessionInfo(id = "v1b-${title.hashCode().toString(16)}"),
                target = PlayTarget(kind = "work"),
                renditions = ranked,
                failurePolicy = PlaybackFailurePolicy(),
            )
        }
    }
}

/**
 * One link as the detail screen holds it, trimmed to what the player needs and addressed by
 * OUR handle. Owned by the caller; it cannot carry an upstream URL because nothing in the app
 * has one to put here.
 */
data class StreamCandidate(
    val streamId: String,
    val playUrl: String,
    val releaseId: Int = 0,
    val printLabel: String? = null,
    val print: PrintInfo = PrintInfo(),
    /** Our server's own words: `direct | resolve | download | external`. */
    val label: String? = null,
    val kind: String? = null,
    val playability: String? = null,
    val protocol: String? = null,
    val mimeType: String? = null,
    val status: String? = null,
    val tier: Int? = null,
    val score: Int = 0,
    val resumable: Boolean = false,
    val ephemeral: Boolean = false,
)
