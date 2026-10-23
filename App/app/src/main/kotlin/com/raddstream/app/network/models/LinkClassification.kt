package com.raddstream.app.network.models

/*
 * ─────────────────────────────────────────────────────────────────────────────
 *  AXIS 2 — LINK QUALITY (what the link *is*, and what a client can do with it now)
 * ─────────────────────────────────────────────────────────────────────────────
 * Kept deliberately separate from [PrintDescriptor] (axis 1, how good the print is):
 * the backend stores them in different columns of different tables
 * (`cat_releases.quality_score` vs `cat_links.rank_score`) and they are never
 * comparable with each other. A BluRay print behind a dead link is unwatchable, and a
 * CAM print on a fast CDN is still a CAM. Nothing here may be used to judge the print,
 * and nothing in [ReleaseLabelParsing] may be used to judge a link.
 *
 * SINCE THE PUBLIC EDGE WAS REDACTED, this file classifies OUR OWN links only. The
 * served link object carries `kind` / `playability` / `protocol` / `tier` / `state` /
 * `playable` — the projector's verdict in our words — plus the opaque `stream_id` handle
 * and our own `play_url`. It carries no hoster slug and no upstream address, and this
 * layer used to be the one place in the app that still keyed on both
 * (`_TIER1`/`_EMBED_SERVICES`/`_BRIDGE_SERVICES` tables copied out of `catalog_v2.py`).
 * Those tables are GONE, on purpose: a list of hoster names inside the client is a
 * provenance surface even when no screen renders it, and the server now ships the verdict
 * the tables used to guess. The verdict is taken as authoritative; when a key is absent
 * the fallback is measured data (mime, http status, state), never a hostname lookup.
 *
 * `rankScore()` is the projection's own ranking CASE (`catalog_v2._finalize`), reproduced
 * so the client can rank a link the server scored only qualitatively. `rankOf()` prefers
 * the server's published `rank_score` whenever it is there.
 */

/** One link's answer to "what is this link and can I play it right now?". */
data class LinkAssessment(
    val kind: LinkKind,
    val playability: Playability,
    /** `link.protocol`: hls | progressive | dash | html | unknown. */
    val protocol: PlayProtocol = PlayProtocol.UNKNOWN,
    /** `cat_links.tier`: 1 = a byte endpoint we measured as fast, 2 = everything else. */
    val tier: Int = 2,
    /** `cat_links.ephemeral` — the link address rots, so it must not be replayed from cache. */
    val ephemeral: Boolean = false,
    /** `cat_links.state`. */
    val state: LinkState = LinkState.UNKNOWN,
    /**
     * `cat_links.accepts_ranges` — still not served (`is_resumable` is a different claim and
     * is carried on [MediaLink.resumable] instead of being re-interpreted as range support).
     * Worth +50 in [rankScore] once the server can answer it.
     */
    val acceptsRanges: Boolean = false,
    /** Measured probe data: `cat_links.speed_mbps` / `latency_ms`. */
    val speedMbps: Double? = null,
    val latencyMs: Int? = null,
    /** True when the server says this link presents inside our own player. */
    val serverSaysPlayable: Boolean? = null,
) {
    val canStream: Boolean get() = playability.isDirectlyPlayable

    /**
     * The only presentation this app has: a Media3 address. A link the server does not mark
     * playable is offered for keeping, with an honest "Not playable here" — never a WebView,
     * never an external hand-off of somebody else's page.
     */
    val playableHere: Boolean get() = playability.isDirectlyPlayable
    val downloadableOnly: Boolean
        get() = playability == Playability.DOWNLOAD || playability == Playability.NONE
}

object LinkClassification {

    private val HLS_MIME_MARKERS = listOf("mpegurl", "m3u8", "vnd.apple.mpegurl", "mp2t")
    private val TEXT_MIME_MARKERS = listOf("text/html", "application/xhtml", "text/plain")
    private val ARCHIVE_MIME_MARKERS = listOf("zip", "rar", "7z", "gzip", "x-tar")

    /**
     * `_protocol_of(kind, playability)`, kept for the projection's own rule: a manifest is
     * HLS, anything a player or a downloader can open is progressive, HTML kinds are html.
     */
    fun protocolOf(kind: LinkKind, playability: Playability): PlayProtocol = when {
        kind == LinkKind.HLS_MANIFEST -> PlayProtocol.HLS
        playability == Playability.STREAM || playability == Playability.DOWNLOAD ||
            playability == Playability.BOTH -> PlayProtocol.PROGRESSIVE
        kind == LinkKind.CLOUD_PAGE || kind == LinkKind.BRIDGE || kind == LinkKind.EMBED ->
            PlayProtocol.HTML
        else -> PlayProtocol.UNKNOWN
    }

    /** The server's `kind` word, in our vocabulary. Unknown words never become a guess. */
    fun kindFromWire(kind: String?, playability: Playability): LinkKind {
        val word = kind?.trim()?.lowercase().orEmpty()
        return when (word) {
            "direct" -> LinkKind.CDN_DIRECT
            // "resolve" = the 302 behind OUR handle does the work; to the player that is a
            // file endpoint, exactly like "direct".
            "resolve" -> LinkKind.CDN_DIRECT
            "hls", "manifest" -> LinkKind.HLS_MANIFEST
            "download", "external" -> LinkKind.DOWNLOAD_ONLY
            "" -> fallbackKind(playability)
            else -> fallbackKind(playability)
        }
    }

    private fun fallbackKind(playability: Playability): LinkKind = when (playability) {
        Playability.STREAM, Playability.BOTH -> LinkKind.CDN_DIRECT
        Playability.DOWNLOAD -> LinkKind.DOWNLOAD_ONLY
        Playability.NONE -> LinkKind.DEAD_END
        else -> LinkKind.UNKNOWN
    }

    /**
     * `cat_links.playability` as served, or our derivation of the server's `kind` word and its
     * own `playable` verdict when the older route does not send one. `external` and `download`
     * both land on DOWNLOAD: the honest "we cannot present this inside this app", never a
     * silent failure and never an embed page.
     */
    fun playabilityFromWire(
        kind: String?,
        playability: String?,
        playable: Boolean?,
        downloadable: Boolean?,
        resumable: Boolean,
        hasHandle: Boolean,
    ): Playability {
        if (!hasHandle) return Playability.NONE
        val word = kind?.trim()?.lowercase().orEmpty()
        if (playable == false) {
            // The server already answered "not inside our player". Believe it, and say what
            // remains: keeping it, or nothing at all.
            return if (downloadable == true || word == "download" || word == "external") {
                Playability.DOWNLOAD
            } else {
                Playability.NONE
            }
        }
        val served = playability?.trim()?.lowercase()?.let { Playability.fromWire(it) }
            ?.takeIf { it != Playability.UNKNOWN && it != Playability.WEBVIEW }
        if (served != null) return served
        return when (word) {
            "direct" -> if (resumable) Playability.BOTH else Playability.STREAM
            // "resolve" = the 302 behind OUR handle does the work; Media3 follows it, so the
            // link is directly addressable exactly like "direct".
            "resolve", "hls", "manifest" -> Playability.STREAM
            "download", "external" -> Playability.DOWNLOAD
            else -> Playability.STREAM
        }
    }

    /** A mime type, or our own play_url, naming an HLS manifest. */
    fun isHls(mimeType: String?, playUrl: String?): Boolean {
        val mime = mimeType?.trim()?.lowercase().orEmpty()
        if (HLS_MIME_MARKERS.any { it in mime }) return true
        val path = playUrl?.lowercase()?.substringBefore("#")?.substringBefore("?").orEmpty()
        return path.endsWith(".m3u8") || path.endsWith(".mpd") ||
            HLS_MIME_MARKERS.any { it in playUrl?.lowercase().orEmpty() && it != "text/html" }
    }

    /** A mime that is a page or an archive: never something a media player should open. */
    fun isNonMediaMime(mimeType: String?): Boolean {
        val mime = mimeType?.trim()?.lowercase().orEmpty()
        if (mime.isEmpty()) return false
        return TEXT_MIME_MARKERS.any { mime.startsWith(it) } ||
            ARCHIVE_MIME_MARKERS.any { mime.contains(it) }
    }

    /**
     * The one classification the live path uses: everything comes from the served link
     * object — our handle, our `play_url`, our own kind/playability/protocol/state words and
     * the measured mime/status. It never looks at a hostname, because none is served.
     */
    fun classify(source: SourceDetail): LinkAssessment {
        val hasHandle = source.streamId.isNotBlank() && source.bestUrl != null
        val resumable = source.isResumableLink
        val state = LinkState.fromWire(source.state ?: source.status)
        val servedPlayability = Playability.fromWire(source.playability).takeIf {
            source.playability?.trim()?.lowercase() != null && it != Playability.UNKNOWN
        }
        val playability = playabilityFromWire(
            kind = source.kind,
            playability = source.playability,
            playable = source.playable,
            downloadable = source.downloadable,
            resumable = resumable,
            hasHandle = hasHandle,
        )
        val hls = isHls(source.mimeType, source.bestUrl)
        val kind = when {
            !hasHandle -> LinkKind.DEAD_END
            hls && (servedPlayability == null || servedPlayability.isDirectlyPlayable) ->
                LinkKind.HLS_MANIFEST
            playability == Playability.DOWNLOAD || playability == Playability.NONE ->
                LinkKind.DOWNLOAD_ONLY
            else -> kindFromWire(source.kind, playability)
        }
        val protocol = PlayProtocol.fromWire(source.protocol).let {
            if (it == PlayProtocol.UNKNOWN) protocolOf(kind, playability) else it
        }
        return LinkAssessment(
            kind = if (kind == LinkKind.UNKNOWN && playability.isDirectlyPlayable) {
                // A playable link with no kind word is still playable: the UNKNOWN kind would
                // strand it in the skip list. Only the kind degrades, never the playability.
                LinkKind.CDN_DIRECT
            } else {
                kind
            },
            playability = playability,
            protocol = protocol,
            tier = source.tier ?: 2,
            ephemeral = source.isEphemeral,
            state = state,
            speedMbps = source.speedMbps,
            latencyMs = source.latencyMs,
            serverSaysPlayable = source.playable,
        )
    }

    /**
     * `cat_links.state` is copied verbatim from the ledger `status`, whose written values are
     * `active | dead | expired`. Anything else is UNKNOWN — never a guess of "active".
     */
    fun stateOf(status: String?): LinkState = LinkState.fromWire(status)

    /**
     * `catalog_v2._finalize`'s `rank_score` CASE, verbatim. Band 0..900 = a *projection
     * prior* ([ScoreScale.PROJECTION_PRIOR]); `link_health.score_link()`'s 0..1000 is the
     * *measured* score and the two are not comparable.
     */
    fun rankScore(assessment: LinkAssessment): Int {
        val base = when (assessment.playability) {
            Playability.STREAM, Playability.BOTH -> 500
            Playability.DOWNLOAD -> 250
            Playability.RESOLVE_REQUIRED -> 120
            Playability.WEBVIEW -> 80
            Playability.NONE -> 0
            Playability.UNKNOWN -> 0
        }
        val tierBonus = if (assessment.tier == 1) 150 else 0
        val durable = if (!assessment.ephemeral) 100 else 0
        val ranges = if (assessment.acceptsRanges) 50 else 0
        val stateBonus = when (assessment.state) {
            LinkState.ACTIVE -> 100
            LinkState.UNKNOWN, LinkState.UNCHECKED -> 0
            else -> -450
        }
        return base + tierBonus + durable + ranges + stateBonus
    }

    /** One served link, ranked: the server's number when it published one, else our derivation. */
    fun rankOf(source: SourceDetail): Int =
        source.rankScore ?: rankScore(classify(source))
}
