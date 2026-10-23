package com.raddstream.app.network.models

/*
 * THE NOT-SERVED-YET REGISTRY.
 *
 * Every capability the app is designed for but the CURRENT server cannot answer, listed in
 * one place so no future reader mistakes a target contract for a live endpoint. Verified by
 * reading `Fast_Fetch/viewer.py::do_GET` (2026-10-22): the only routes that exist are
 * `/api/v1/posts`, `/api/v1/posts/{id}`, `/api/v1/stream`, `/api/v1/rules`, `/api/v1/stats`,
 * plus the non-contract dashboard routes (`/api/data`, `/api/sitemap`, `/api/fetch`,
 * `/api/m3u`, `/api/health-check`, `/api/heal`, `/client`, `/`). There is no `do_POST`, so
 * anything that needs a POST cannot exist at all yet.
 *
 * The rule for the rest of the app: code that would call one of these must be marked with a
 * [EndpointGaps.require] comment at the call site and must degrade to the v1 path, never
 * fail and never fabricate a response.
 */
enum class EndpointGaps(
    /** The endpoint the v2 contract wants. */
    val needed: String,
    /** What the app cannot do without it. */
    val blockedCapability: String,
    /** The v1 path that stands in for it today, or null when nothing can. */
    val v1Fallback: String?,
    /** API_V2.md gap id, when the doc already tracks it. */
    val docGap: String? = null,
) {
    PLAY(
        needed = "/api/v2/play",
        blockedCapability = "server-ranked play bundle (print quality + link health + " +
            "entitlement decided in one place)",
        v1Fallback = "/api/v1/posts/{id} then client-side PrintDescriptor + LinkClassification",
        docGap = "G-7",
    ),
    RESOLVE(
        needed = "/api/v2/links/{link_id}/resolve",
        blockedCapability = "resolver round-trip for cloud_page/resolve_required links",
        v1Fallback = "/api/v1/stream?id={source_id}&redirect=0",
    ),
    REPORT(
        needed = "POST /api/v2/links/{link_id}/report",
        blockedCapability = "client dead-link reporting (and the server's own /api/heal, " +
            "which currently never writes a response body)",
        v1Fallback = null,
    ),
    OFFSET(
        needed = "/api/v2/episodes/{episode_id}/offset",
        blockedCapability = "pack offsets: where in a season-pack file episode N starts",
        v1Fallback = null,
    ),
    SYNC(
        needed = "/api/v2/sync?since=",
        blockedCapability = "delta sync keyed by work_key (no /api/v1/sync exists)",
        v1Fallback = "re-fetch /api/v1/posts?page=n",
    ),
    MANIFEST(
        needed = "/api/v2/works/{work_key}",
        blockedCapability = "one stable-keyed manifest for a work (episodes, prints, links)",
        v1Fallback = "/api/v1/posts/{numericId} — the id churns across re-projections",
    ),
    PRINT_FIELDS(
        needed = "cat_releases print columns on the wire",
        blockedCapability = "server-authoritative resolution / source_tag / hdr / codec / " +
            "quality_score / coverage_type",
        v1Fallback = "client-side ReleaseLabelParsing (this package)",
        docGap = "G-4",
    ),
    LINK_FIELDS(
        needed = "cat_links rank_score / accepts_ranges / expires_at / speed_mbps on the wire",
        blockedCapability = "measured link quality, TTL and resumability of a listed link",
        v1Fallback = "client-side LinkClassification prior; TTL only from /api/v1/stream",
        docGap = "G-5",
    ),
    SUBTITLES(
        needed = "subtitle track URLs",
        blockedCapability = "offering subtitles as selectable tracks (only 'ESub' in a label)",
        v1Fallback = "none — the flag is descriptive only",
        docGap = "G-1",
    ),
    ENTITLEMENT(
        needed = "cat_entitlements rows beyond the implicit free/default",
        blockedCapability = "ads / flatrate / rental / purchase offers and pricing",
        v1Fallback = "Entitlement.freeDefault for every work",
        docGap = "G-6",
    );

    companion object {
        /**
         * The marker every call site that needs an unserved endpoint must carry, so `grep`
         * finds all of them: `// NOT SERVED YET — needs /api/v2/play (see EndpointGaps.PLAY)`.
         */
        const val MARKER: String = "NOT SERVED YET"

        fun needs(gap: EndpointGaps): String = "$MARKER - needs ${gap.needed}"
    }
}
