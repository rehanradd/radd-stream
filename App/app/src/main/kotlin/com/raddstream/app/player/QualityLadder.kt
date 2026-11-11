package com.raddstream.app.player

import com.raddstream.app.data.UserRegion
import com.raddstream.app.network.models.LadderTier
import com.raddstream.app.network.models.LinkClassification
import com.raddstream.app.network.models.OptionGroup
import com.raddstream.app.network.models.ProviderPageLinks

/**
 * The quality switch and the download card, in one honest shape per rung.
 *
 * The server already collapsed every copy of a print into one winner per band
 * (`Fast_Fetch/tiers.py`), so this file adds no ranking of its own: it turns that
 * verdict into what a row can show — the picture, the approximate size, whether
 * our one player can start it here, and the silent runner-ups to hop to if the
 * first CDN refuses. Site names, hoster names and upstream addresses are not on
 * the wire model, so they cannot reach a composable from here either.
 *
 * WHY IT LIVES IN `player`: this is the app-local VIEW state of a rung — a handle, our own
 * address, and whether this player can present it. The server's own ladder contract
 * (`network/models/QualityLadder.kt`: [OptionGroup], [LadderTier], …) is the single wire owner,
 * and the one function below that crosses the boundary is [LadderTier.toOptionOrNull]. There
 * is deliberately no second copy of either layer and no alias tying them together.
 */
data class QualityOption(
    /** `2160p | 1080p | 720p | 480p | sd | unspecified` — the switch's row key. */
    val band: String,
    /** "4K Ultra HD · HEVC" — the server's own words, quality only. */
    val title: String,
    /** The opaque handle of ours this rung plays by. Blank when the rung has no winner. */
    val streamId: String,
    /** OUR OWN redirector address, null when there is none. */
    val playUrl: String?,
    val sizeBytes: Long?,
    /** Same-band runner-ups, handles only — the silent failover ladder. */
    val backupHandles: List<String>,
    val playsHere: Boolean,
    val resumable: Boolean,
    val copies: Int,
    /** The winning print's stored audio languages. Empty when the print's
     * languages column is empty — the row shows no audio line then. */
    val audioLanguages: List<String> = emptyList(),
    /** What the winner copy measurably is: a manifest stream or a direct file.
     * Null when the copy was never probed — the row claims neither. */
    val streamCategory: StreamCategory? = null,
    /**
     * The rung's winner is a page, not a file: it can be opened, never streamed here and never
     * kept. No default on purpose — every construction of a rung has to answer for it, so a page
     * cannot be reclassified as "download only" by a caller that forgot the field.
     */
    val isProviderPage: Boolean,
) {
    /** A rung you can only keep: the card says it out loud instead of failing quietly. */
    val downloadOnly: Boolean get() = !playsHere && !isProviderPage

    /**
     * Netflix-style size hint, "≈ 1.4 GB"; null when the server never measured a size.
     * Session 121 (P-8): also null when the probe measured something implausibly small
     * for a video file (a redirect or landing page, not the file — a 3.05 GB film once
     * arrived as 513 bytes and rendered as "≈ 513 B"). A real video is never under 1 MB.
     */
    val sizeLine: String? get() = sizeBytes?.takeIf { it >= 1_000_000 }?.let { formatBytes(it) }

    /** The row's sentence: what the picture is, then what the app can do with it. */
    val detailLine: String
        get() = listOfNotNull(
            sizeLine?.let { "≈ $it" },
            when {
                playsHere -> PLAYABLE_HERE
                isProviderPage -> PROVIDER_PAGE_ONLY
                else -> KEEPS_ONLY
            },
        ).joinToString(" · ")

    companion object {
        // "Plays here" has exactly ONE owner — PLAYABLE_HERE, in this package's
        // LinkKindClassifier.kt — so a rung row and a detail-screen link can never say two
        // different things about the same presentation.
        const val KEEPS_ONLY = "Download only"

        /** Human sizes, one place, so the card and the download list never disagree. */
        fun formatBytes(bytes: Long): String {
            val units = listOf("B", "KB", "MB", "GB", "TB")
            var value = bytes.toDouble()
            var unit = 0
            while (value >= 1024.0 && unit < units.lastIndex) {
                value /= 1024.0
                unit++
            }
            val text = if (value >= 100 || unit == 0) "%.0f".format(value) else "%.1f".format(value)
            return "$text ${units[unit]}"
        }
    }
}

/**
 * What a rung's winner copy measurably is — a manifest stream or a direct file —
 * named by the container the probe actually measured. Null is a real answer: the
 * copy was never probed, so the row claims neither shape rather than a guessed one.
 */
data class StreamCategory(val kind: Kind, val container: String) {
    enum class Kind { INSTANT_STREAM, DIRECT_FILE }

    /** "Instant Stream · M3U8" / "Direct File · MP4" — the row's own words. */
    val label: String
        get() = when (kind) {
            Kind.INSTANT_STREAM -> "Instant Stream · $container"
            Kind.DIRECT_FILE -> "Direct File · $container"
        }
}

/**
 * The stream category of one winner copy, from the probe-measured MIME the
 * server publishes on the ladder link — never from a host name or a guessed
 * speed. A manifest MIME outranks everything (the same rule
 * [ManifestProtocolTest] pins for playback); a video file MIME names its
 * container; anything else — an HTML page, an audio file, no measurement at
 * all — yields null, and the row shows no category.
 */
fun streamCategoryFor(mimeType: String?, playUrl: String?): StreamCategory? {
    if (LinkClassification.isHls(mimeType, playUrl)) {
        return StreamCategory(StreamCategory.Kind.INSTANT_STREAM, "M3U8")
    }
    if (LinkClassification.isDash(mimeType, playUrl)) {
        return StreamCategory(StreamCategory.Kind.INSTANT_STREAM, "DASH")
    }
    val mime = mimeType?.trim()?.lowercase().orEmpty()
    val container = FILE_MIME_CONTAINERS.entries.firstOrNull { (marker, _) -> marker in mime }?.value
        ?: return null
    return StreamCategory(StreamCategory.Kind.DIRECT_FILE, container)
}

/** Probe-measured video file MIME → the container the row may name. */
private val FILE_MIME_CONTAINERS = mapOf(
    "video/mp4" to "MP4",
    "video/x-matroska" to "MKV",
    "video/matroska" to "MKV",
    "video/webm" to "WebM",
    "video/quicktime" to "MOV",
    "video/x-msvideo" to "AVI",
    "video/mpeg" to "MPG",
    "video/mp2t" to "TS",
    "video/x-m4v" to "M4V",
    "video/3gpp" to "3GP",
    "video/ogg" to "OGV",
)

/**
 * Data cost per hour of watching, from the plan §1.7 guide (approximate,
 * codec-dependent — a HEVC 1080p costs less than an AVC one, so these are the
 * guide's own numbers, never a measurement of this print). A separate pure
 * band → cost mapping on purpose: it is NOT derived from `sizeBytes`, because a
 * file's size says how big its download is, not how fast an hour of it plays.
 *
 * The plan's own example ("High ≈ 1.5 GB/hour") is the 720p rung — the free cap —
 * not 1080p, which the same §1.7 guide prices at ~3 GB/hour. Unknown or unbanded
 * rungs show no cost rather than a guessed one.
 */
fun qualityCostPerHour(band: String): String? = when (band.trim().lowercase()) {
    "2160p" -> "≈ 7–11 GB/hour"
    "1080p" -> "≈ 3 GB/hour"
    "720p" -> "≈ 1.5 GB/hour"
    "480p" -> "≈ 700 MB/hour"
    "sd" -> "≈ 300 MB/hour"
    else -> null
}

/**
 * The audio languages a region leads with. Only DESI_DUBS orders anything
 * today — Hindi and Urdu, the same pair the release selector already uses
 * to lead its prints — so every other region gets an empty set and the
 * ladder keeps its server order.
 *
 * Audit #32: the quality rows lead with the viewer's own audio, and the
 * lead row is labelled "your pick" on the card.
 */
fun preferredAudioLanguages(region: String?): Set<String> =
    if (UserRegion.normalize(region) == UserRegion.DESI_DUBS) setOf("Hindi", "Urdu") else emptySet()

/** True when this rung's winner carries one of the preferred languages. */
fun carriesPreferredAudio(option: QualityOption, preferred: Set<String>): Boolean =
    preferred.isNotEmpty() && option.audioLanguages.any { lang ->
        preferred.any { it.equals(lang, ignoreCase = true) }
    }

/**
 * Display order only: preferred-audio rows lead, the rest keep their old
 * order (stable sort). The ladder itself is NOT reordered — Auto still
 * starts at the best picture — only the card the viewer reads is.
 */
fun preferredAudioFirst(options: List<QualityOption>, preferred: Set<String>): List<QualityOption> =
    if (preferred.isEmpty()) options
    else options.sortedWith(compareByDescending { carriesPreferredAudio(it, preferred) })

/** Everything the detail screen needs from one scope's ladder. */
data class LadderForScope(
    val options: List<QualityOption>,
    /** The rung `Auto` starts at, or null when nothing in this scope plays. */
    val autoBand: String?,
    /** Rungs that exist but cannot be presented here — the card keeps them visible. */
    val downloadOnlyBands: List<String>,
) {
    val isEmpty: Boolean get() = options.isEmpty()

    /** Auto's row, or the best rung available when the server named no playable one. */
    val autoOption: QualityOption?
        get() = options.firstOrNull { it.band == autoBand } ?: options.firstOrNull { it.playsHere }
            ?: options.firstOrNull()

    fun optionFor(band: String?): QualityOption? =
        if (band == null || band == AUTO) autoOption else options.firstOrNull { it.band == band }

    /**
     * The handle the player is told: Auto resolves to the server's best playable rung, and a
     * remembered band that this scope no longer offers resolves to Auto rather than to nothing
     * — a stale preference must never strand the viewer without a link.
     */
    fun resolvedFor(band: String?): QualityOption? = optionFor(band) ?: autoOption

    companion object {
        const val AUTO = "auto"
        val EMPTY = LadderForScope(emptyList(), null, emptyList())
    }
}

object QualityLadder {

    /**
     * The ladder for one season/episode scope. A movie's ledger columns are both
     * null, so a null query matches exactly the group whose keys are null — matching
     * on the served TEXT, never re-parsing a title, because a scraper's sentence is
     * not a scope. When a series has no group for the requested episode we show
     * nothing rather than another episode's links.
     */
    fun forScope(groups: List<OptionGroup>, season: String?, episode: String?): LadderForScope {
        if (groups.isEmpty()) return LadderForScope.EMPTY
        val wanted = groups.firstOrNull { group ->
            scopeOf(group.season) == scopeOf(season) && scopeOf(group.episode) == scopeOf(episode)
        } ?: return LadderForScope.EMPTY
        return from(wanted)
    }

    /** A scope key of our own making: trimmed, blank-as-null, case-folded. */
    private fun scopeOf(value: String?): String? =
        value?.trim()?.takeIf { it.isNotEmpty() }?.lowercase()

    /**
     * The same lookup for the detail screen, which counts seasons and episodes rather than
     * holding the ledger's text. The scope columns are stamped by our own importers in a
     * `S01`/`E05` shape, so reading the digits back is a key lookup on a column we own — not
     * a parse of a scraper's sentence. A group whose season column is empty matches any
     * season, because a site that never recorded seasons has exactly one.
     */
    fun forNumberedScope(
        groups: List<OptionGroup>,
        season: Int?,
        episode: Int?,
    ): LadderForScope {
        if (groups.isEmpty()) return LadderForScope.EMPTY
        val wanted = groups.firstOrNull { group ->
            val groupSeason = digitsOf(group.season)
            (groupSeason == null || groupSeason == season) && digitsOf(group.episode) == episode
        } ?: return if (season == null && episode == null && groups.size == 1) {
            from(groups.first())
        } else {
            LadderForScope.EMPTY
        }
        return from(wanted)
    }

    private fun digitsOf(value: String?): Int? =
        value?.filter { it.isDigit() }?.takeIf { it.isNotEmpty() }?.toIntOrNull()

    fun from(group: OptionGroup): LadderForScope = LadderForScope(
        options = group.tiers.mapNotNull { it.toOptionOrNull() },
        autoBand = group.auto?.band?.takeIf { it.isNotBlank() },
        downloadOnlyBands = group.downloadOnlyBands,
    )

    /**
     * One rung → one row. A rung with no winner is skipped: the server folded every
     * copy of the print into that winner, so an empty rung means the band exists in
     * no copy at all and there is nothing honest to offer.
     */
    private fun LadderTier.toOptionOrNull(): QualityOption? {
        val winner = link ?: return null
        val id = winner.streamId?.trim().orEmpty()
        if (id.isEmpty()) return null
        return QualityOption(
            band = band,
            title = label?.takeIf { it.isNotBlank() } ?: quality?.takeIf { it.isNotBlank() }
            ?: band,
            streamId = id,
            playUrl = winner.bestUrl,
            sizeBytes = winner.fileSizeBytes,
            backupHandles = backupHandles.filter { it.isNotBlank() },
            playsHere = playable && winner.playable && !winner.isDead,
            resumable = winner.isResumableLink,
            copies = copies,
            audioLanguages = audioLanguages,
            streamCategory = streamCategoryFor(winner.mimeType, winner.bestUrl),
            // The ladder's copy of a link carries `kind` and no `playability` (that is the
            // `ladder_link` projection, not the full one), so the rung's page verdict comes from
            // the served kind word alone — the same rule the detail rows use. WORDS only, never
            // health: a rung whose page is currently down is still not a file to keep, and its
            // deadness already shows up as `playsHere` being false.
            isProviderPage = ProviderPageLinks.isPageVerdict(
                kind = winner.kind,
                playability = null,
            ),
        )
    }
}
