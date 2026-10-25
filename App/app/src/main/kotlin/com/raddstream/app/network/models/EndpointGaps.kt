package com.raddstream.app.network.models

/*
 * THE NOT-SERVED-YET REGISTRY — scoped to what THIS INSTALL can reach.
 *
 * Every capability this app is designed against but cannot call from a real install today,
 * listed in one place so no future reader mistakes a target contract for a live endpoint.
 *
 * Read the header carefully: it is about what OUR INSTALL can reach, not about what the
 * server implements. `Fast_Fetch/api_v2.py` is mounted in `viewer.py` and answers
 * `/api/v2/manifest|browse|search|suggest|works|episodes|releases|sync|stats`, plus
 * `POST /play`, `POST /links/{id}/report`, `resolve` and `offset`. None of it is usable yet
 * because every v2 route requires the `cat_*` projection, and the database the public service
 * runs on has none — so the honest answer to a v2 request today is
 * `unavailable` ("The catalog projection has not been built yet", with `Retry-After: 60`).
 * What remains genuinely unimplemented server-side is tracked in `Fast_Fetch/API_V2.md` §17,
 * not here.
 *
 * The rule for the rest of the app: code that would call one of these must be marked with a
 * [EndpointGaps.require] comment at the call site and must degrade to the v1 path, never
 * fail and never fabricate a response. Dropping an entry here means "this install can now
 * reach it and the call site has been switched over", never "the route file exists".
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
