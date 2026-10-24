package com.raddstream.app.network.models

/*
 * Enumerations of the catalog contract.
 *
 * THE ENUM-TOLERANCE RULE (API_V2.md §16.6): the server may add a value at any time and
 * never renames one, so NO enum here is ever parsed by Gson directly. Every wire value
 * arrives as a String and goes through a `fromWire(...)` that returns [unknown]-style
 * fallbacks. Gson decoding of a brand-new server value therefore cannot crash the client
 * (pinned by EnumToleranceTest), and "unknown" always means "the server said something we
 * have no rule for" — never a silently wrong guess.
 */

/** `cat_works.work_type` — the value set `catalog_v2._WORK_TYPE_BY_CONTENT` can produce. */
enum class WorkType(val wire: String) {
    MOVIE("movie"),
    SERIES("series"),
    ANIME("anime"),
    DOCUMENTARY("documentary"),
    SPORT_EVENT("sport_event"),
    MUSIC_VIDEO("music_video"),
    /**
     * tv_special / miniseries are named in the design but the projector never emits them
     * (API_V2.md §4.2). Kept so a server that starts sending them is understood, not
     * degraded to UNKNOWN.
     */
    TV_SPECIAL("tv_special"),
    MINISERIES("miniseries"),
    /**
     * v1 ledger spellings of a series (`classify_media()` writes them; the Layer-1
     * projector maps both to `series`). Modelled so a v1 `content_type` never degrades.
     */
    COMPLETE_SEASON("complete_season"),
    ONGOING_SEASON("ongoing_season"),
    UNKNOWN("unknown");

    /** Series-family: seasons/episodes exist and movie↔series never merge. */
    val isSeriesFamily: Boolean
        get() = this == SERIES || this == ANIME || this == MINISERIES ||
            this == TV_SPECIAL || this == COMPLETE_SEASON || this == ONGOING_SEASON

    /**
     * `catalog_v2._SERIES_TYPES`, verbatim — used wherever the client must agree with the
     * server's `work_family()`. NOTE the quirk that is reproduced rather than "fixed":
     * `tv_special` is NOT in the server's set, so a special is in the MOVIE family there
     * while [isSeriesFamily] (a presentation notion) keeps it series-side.
     */
    val isServerSeriesType: Boolean
        get() = this == SERIES || this == ANIME || this == MINISERIES ||
            this == COMPLETE_SEASON || this == ONGOING_SEASON

    companion object {
        fun fromWire(raw: String?): WorkType = when (raw?.trim()?.lowercase()) {
            null, "" -> UNKNOWN
            "movie" -> MOVIE
            "series" -> SERIES
            "anime" -> ANIME
            "documentary" -> DOCUMENTARY
            "sport_event", "sport", "sports_event" -> SPORT_EVENT
            "music_video" -> MUSIC_VIDEO
            "tv_special", "special" -> TV_SPECIAL
            "miniseries" -> MINISERIES
            "complete_season" -> COMPLETE_SEASON
            "ongoing_season" -> ONGOING_SEASON
            "unknown" -> UNKNOWN
            else -> UNKNOWN
        }

        /**
         * The v1 truth: `content_type` only ever holds movie/series/complete_season/
         * ongoing_season, and anime lives in the separate `is_animated` flag — exactly the
         * rule `catalog_v2.work_type_for()` applies. `?type=anime` returns zero rows, so
         * the client derives anime instead of asking for it.
         */
        fun fromContentType(contentType: String?, isAnimated: Boolean?): WorkType {
            val base = fromWire(contentType)
            return when {
                isAnimated == true && (base.isSeriesFamily || base == UNKNOWN) -> ANIME
                base == COMPLETE_SEASON || base == ONGOING_SEASON -> SERIES
                else -> base
            }
        }
    }
}

/** `cat_seasons.season_type` — only 'regular' is written today. */
enum class SeasonType(val wire: String) {
    REGULAR("regular"),
    SPECIAL("special"),
    EXTRA("extra"),
    UNKNOWN("unknown");

    companion object {
        fun fromWire(raw: String?): SeasonType =
            values().firstOrNull { it.wire == raw?.trim()?.lowercase() } ?: UNKNOWN
    }
}

/**
 * `cat_releases.coverage_type` — how one file covers episodes (API_V2.md §4.3).
 * There is deliberately NO `parts` value: `_release_coverage()` never emits one, and
 * multi-part films are `whole_work` prints carrying a part label (gap G-3).
 */
enum class CoverageType(val wire: String) {
    WHOLE_WORK("whole_work"),
    SEASON_PACK("season_pack"),
    EPISODE_RANGE("episode_range"),
    SINGLE_EPISODE("single_episode"),
    PARTS("parts"),
    UNKNOWN("unknown");

    /** One file holds many episodes, so the player needs an offset to reach episode N. */
    val isPacked: Boolean get() = this == SEASON_PACK || this == WHOLE_WORK

    companion object {
        fun fromWire(raw: String?): CoverageType =
            values().firstOrNull { it.wire == raw?.trim()?.lowercase() } ?: UNKNOWN
    }
}

/** Print axis — `cat_releases.resolution`. Complete value set of `release_descriptor`. */
enum class Resolution(val wire: String, val weight: Int, val label: String) {
    R2160("2160p", 400, "4K UHD"),
    R1080("1080p", 300, "Full HD"),
    R720("720p", 200, "HD"),
    R480("480p", 120, "SD"),
    R480_OR_LOWER("480p_or_lower", 100, "SD"),
    UNKNOWN("unknown", 50, "");

    companion object {
        fun fromWire(raw: String?): Resolution =
            values().firstOrNull { it.wire == raw?.trim()?.lowercase() } ?: UNKNOWN
    }
}

/** Print axis — capture source. Complete set of `_SOURCE_PATTERNS` (+ the planned `hdtc`). */
enum class SourceTag(val wire: String, val weight: Int, val official: Boolean, val camFamily: Boolean) {
    UHD_BLURAY("uhd_bluray", 300, true, false),
    BLURAY("bluray", 280, true, false),
    WEB_DL("web_dl", 240, true, false),
    WEBRIP("webrip", 220, true, false),
    HDTV("hdtv", 180, true, false),
    DVD_RIP("dvdrip", 150, true, false),
    TELESYNC("telesync", 80, false, true),
    TELECINE("telecine", 70, false, true),
    PPV("ppv", 20, false, false),
    CAM("cam", 20, false, true),
    /** Planned rung (gap G-4): HDTC scores as UNKNOWN today, not as a cam. */
    HDT_C("hdtc", 60, false, false),
    UNKNOWN("unknown", 60, false, false);

    companion object {
        fun fromWire(raw: String?): SourceTag =
            values().firstOrNull { it.wire == raw?.trim()?.lowercase() } ?: UNKNOWN
    }
}

/** Print axis — video codec. */
enum class Codec(val wire: String) {
    H265("h265"),
    H264("h264"),
    AV1("av1"),
    XVID("xvid"),
    MPEG2("mpeg2"),
    UNKNOWN("unknown");

  companion object {
    fun fromWire(raw: String?): Codec = when (raw?.trim()?.lowercase()) {
        "h265", "hevc", "x265", "265" -> H265
        "h264", "avc", "x264", "264" -> H264
        "av1", "av01" -> AV1
        "xvid" -> XVID
        "mpeg2", "mpeg", "mpgv", "dvdvideo" -> MPEG2
        "unknown", null, "" -> UNKNOWN
        else -> UNKNOWN
    }
  }
}

/** Print axis — HDR formats, `cat_releases.hdr` JSON array items. */
enum class HdrFormat(val wire: String, val label: String) {
    DOLBY_VISION("dolby_vision", "Dolby Vision"),
    HDR10_PLUS("hdr10_plus", "HDR10+"),
    HDR10("hdr10", "HDR10"),
    HLG("hlg", "HLG"),
    /** An array item the app has never seen: kept as itself so the label is still honest. */
    UNKNOWN("unknown", "");

    companion object {
        fun fromWire(raw: String?): HdrFormat =
            values().firstOrNull { it.wire == raw?.trim()?.lowercase() } ?: UNKNOWN
    }
}

/** Print axis — container. */
enum class Container(val wire: String) {
    MKV("mkv"), MP4("mp4"), AVI("avi"), MOV("mov"), TS("ts"), M4A("m4a"), UNKNOWN("unknown");

    companion object {
        fun fromWire(raw: String?): Container =
            values().firstOrNull { it.wire == raw?.trim()?.lowercase() } ?: UNKNOWN
    }
}

/** Print axis — edition. Editions are separate prints, never "qualities" of one another. */
enum class Edition(val wire: String, val label: String, val bonus: Boolean) {
    DIRECTOR_CUT("director_cut", "Director's Cut", true),
    EXTENDED("extended", "Extended", true),
    IMAX("imax", "IMAX", false),
    UNRATED("unrated", "Unrated", false),
    REMASTERED("remastered", "Remastered", true),
    RESTORED("restored", "Restored", true),
    UNCUT("uncut", "Uncut", false),
    FAN_EDIT("fan_edit", "Fan Edit", false),
    THEATRICAL("theatrical", "Theatrical", false),
    UNKNOWN("unknown", "", false);

    companion object {
        fun fromWire(raw: String?): Edition =
            values().firstOrNull { it.wire == raw?.trim()?.lowercase() } ?: UNKNOWN
    }
}

/** Print axis — how subtitles reach the viewer. No subtitle URL exists anywhere yet (G-1). */
enum class SubtitleMode(val wire: String) {
    EXTERNAL("external"),
    HARDCODED("hardcoded"),
    NONE("none"),
    UNKNOWN("unknown");

    companion object {
        fun fromWire(raw: String?): SubtitleMode =
            values().firstOrNull { it.wire == raw?.trim()?.lowercase() } ?: UNKNOWN
    }
}

/**
 * Link axis — what the URL *is* (`cat_links.kind`). `torrent` is NOT a kind: magnets and
 * .torrent files classify as DOWNLOAD_ONLY (API_V2.md §6.1). DEAD_END is the honest record
 * of an empty target URL, which the projector keeps instead of dropping.
 */
enum class LinkKind(val wire: String) {
    CDN_DIRECT("cdn_direct"),
    HLS_MANIFEST("hls_manifest"),
    CLOUD_PAGE("cloud_page"),
    BRIDGE("bridge"),
    EMBED("embed"),
    DOWNLOAD_ONLY("download_only"),
    DEAD_END("dead_end"),
    UNKNOWN("unknown");

    companion object {
        fun fromWire(raw: String?): LinkKind =
            values().firstOrNull { it.wire == raw?.trim()?.lowercase() } ?: UNKNOWN
    }
}

/**
 * Link axis — what a client can do with the link right now (`cat_links.playability`).
 * RESOLVE_REQUIRED means "the URL you have is not the media URL": a resolver round-trip
 * is mandatory before a player may be handed anything.
 */
enum class Playability(val wire: String) {
    STREAM("stream"),
    DOWNLOAD("download"),
    BOTH("both"),
    WEBVIEW("webview"),
    RESOLVE_REQUIRED("resolve_required"),
    NONE("none"),
    UNKNOWN("unknown");

    /** A player may be pointed at the URL as it stands. */
    val isDirectlyPlayable: Boolean
        get() = this == STREAM || this == BOTH

    companion object {
        fun fromWire(raw: String?): Playability = when (raw?.trim()?.lowercase()) {
            "stream" -> STREAM
            "download" -> DOWNLOAD
            "both" -> BOTH
            "webview" -> WEBVIEW
            "resolve_required" -> RESOLVE_REQUIRED
            "none" -> NONE
            "unknown", null, "" -> UNKNOWN
            else -> UNKNOWN
        }
    }
}

/** Link axis — `cat_links.state`, copied from the ledger `status`. */
enum class LinkState(val wire: String) {
    ACTIVE("active"),
    DEAD("dead"),
    EXPIRED("expired"),
    /** Named in the rank formula as a future value; nothing writes it yet. */
    UNCHECKED("unchecked"),
    UNKNOWN("unknown");

    val isDead: Boolean get() = this == DEAD || this == EXPIRED

    companion object {
        fun fromWire(raw: String?): LinkState = when (raw?.trim()?.lowercase()) {
            "active", "ok", "alive", "working", "live" -> ACTIVE
            "dead", "down", "broken", "offline", "fail", "failed", "unavailable" -> DEAD
            "expired" -> EXPIRED
            "unchecked" -> UNCHECKED
            "unknown", null, "" -> UNKNOWN
            else -> UNKNOWN
        }
    }
}

/** Link axis — which MediaSource the URL needs. */
enum class PlayProtocol(val wire: String) {
    HLS("hls"),
    DASH("dash"),
    PROGRESSIVE("progressive"),
    HTML("html"),
    UNKNOWN("unknown");

    companion object {
        fun fromWire(raw: String?): PlayProtocol =
            values().firstOrNull { it.wire == raw?.trim()?.lowercase() } ?: UNKNOWN
    }
}

/**
 * Entitlement model (API_V2.md §11.2 — IMDb/Gracenote delivery-channel vocabulary).
 * Only FREE is ever written today. `ads` is a labelling tier: there is no ad server, and
 * the app must not claim otherwise.
 */
enum class EntitlementModel(val wire: String, val displayPriority: Int) {
    FREE("free", 10),
    ADS("ads", 20),
    FLATRATE("flatrate", 30),
    RENTAL("rental", 40),
    PURCHASE("purchase", 50),
    UNKNOWN("unknown", 100);

    /** A gated offer: cannot be played on the cleartext host (§8.3), so never offered. */
    val needsLicence: Boolean get() = this == FLATRATE || this == RENTAL || this == PURCHASE

    companion object {
        fun fromWire(raw: String?): EntitlementModel = when (raw?.trim()?.lowercase()) {
            "free" -> FREE
            "ads", "ad_supported", "free_with_ads" -> ADS
            "flatrate", "subscription", "svod" -> FLATRATE
            "rental", "tvod_rent" -> RENTAL
            "purchase", "tvod" -> PURCHASE
            "unknown", null, "" -> UNKNOWN
            else -> UNKNOWN
        }
    }
}

/** Entitlement ownership rule — decides whether a cached offline copy may be kept. */
enum class Ownership(val wire: String) {
    NEVER("never"),
    UNTIL_EXPIRY("until_expiry"),
    PERMANENT("permanent"),
    UNKNOWN("unknown");

    /** `until_expiry` ⇒ the app MUST expire its offline copy (API_V2.md §7/§11.3). */
    val mustExpireOfflineCopy: Boolean get() = this == UNTIL_EXPIRY || this == NEVER

    companion object {
        fun fromWire(raw: String?): Ownership =
            values().firstOrNull { it.wire == raw?.trim()?.lowercase() } ?: UNKNOWN
    }
}

/**
 * Which scale a link score uses (API_V2.md §7.1). Comparing a prior against a measured
 * score without checking this is a ranking bug, so the scale travels with the number.
 */
enum class ScoreScale(val wire: String) {
    PROJECTION_PRIOR("projection_prior"),
    MEASURED("measured"),
    /** Client-side v1 fallback: no server score exists, so [LinkClassification] derived one. */
    CLIENT_V1_PRIOR("client_v1_prior"),
    UNKNOWN("unknown");

    companion object {
        fun fromWire(raw: String?): ScoreScale =
            values().firstOrNull { it.wire == raw?.trim()?.lowercase() } ?: UNKNOWN
    }
}

/** `cat_works.flags` / `GET /works/{id}` flags. Adult status is never a client-visible flag. */
enum class WorkFlag(val wire: String) {
    IDENTITY_SUSPECT("identity_suspect"),
    UNKNOWN("unknown");

    companion object {
        fun fromWire(raw: String?): WorkFlag =
            values().firstOrNull { it.wire == raw?.trim()?.lowercase() } ?: UNKNOWN

        fun listFromWire(raw: List<String?>?): List<WorkFlag> =
            (raw ?: emptyList()).map { fromWire(it) }.distinct()
    }
}

/** `cat_releases.flags` — kept-and-labelled prints, never silently dropped. */
enum class PrintFlag(val wire: String) {
    WATERMARKED("watermarked"),
    UNOFFICIAL("unofficial"),
    PACK("pack"),
    ALTERNATE_EDITION("alternate_edition"),
    UNKNOWN("unknown");

    companion object {
        fun fromWire(raw: String?): PrintFlag =
            values().firstOrNull { it.wire == raw?.trim()?.lowercase() } ?: UNKNOWN

        fun listFromWire(raw: List<String?>?): List<PrintFlag> =
            (raw ?: emptyList()).map { fromWire(it) }.distinct()
    }
}

/** Stable machine error codes (API_V2.md §16.4). Clients switch on `code`, never on text. */
enum class ProblemCode(val wire: String) {
    INVALID_PARAMS("invalid_params"),
    CURSOR_INVALID("cursor_invalid"),
    UNAUTHORISED("unauthorised"),
    FORBIDDEN("forbidden"),
    NOT_FOUND("not_found"),
    LICENCE_REQUIRED("licence_required"),
    NO_PLAYABLE_SOURCE("no_playable_source"),
    GONE("gone"),
    BUNDLE_EXPIRED("bundle_expired"),
    LICENCE_EXPIRED("licence_expired"),
    RATE_LIMITED("rate_limited"),
    TARGET_UNRESOLVABLE("target_unresolvable"),
    INTERNAL("internal"),
    UNAVAILABLE("unavailable"),
    UNKNOWN("unknown");

    companion object {
        fun fromWire(raw: String?): ProblemCode =
            values().firstOrNull { it.wire == raw?.trim()?.lowercase() } ?: UNKNOWN
    }
}

/** `/play` ordering preference — the two axes made explicit (API_V2.md §9). */
enum class Prefer(val wire: String) {
    QUALITY("quality"),
    SPEED("speed"),
    DATA_SAVER("data_saver");

    companion object {
        fun fromWire(raw: String?): Prefer = when (raw?.trim()?.lowercase()) {
            "speed" -> SPEED
            "data_saver" -> DATA_SAVER
            else -> QUALITY
        }
    }
}
