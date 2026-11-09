package com.raddstream.app.network.models

/*
 * THE NOT-SERVED-YET REGISTRY — scoped to what THIS INSTALL can reach.
 *
 * Every capability this app is designed against but cannot call from a real install today,
 * listed in one place so no future reader mistakes a target contract for a live endpoint.
 *
 * Phase 7 (D2): the premise this header was written under is gone. The rev-7 projection
 * IS built and live (2026-11-10), and v2 IS served: `POST /api/v2/play`,
 * `GET /api/v2/suggest`, `POST /api/v2/links/`, `POST /api/v2/episodes/` and
 * `/api/v2/account` are allow-listed in live nginx, and the GET catalog routes
 * (`/api/v2/browse`, `/api/v2/search`, `/api/v2/works/{id}`) are served by
 * `catalog_api.py` — the app calls them through `V2CatalogWire.kt`, with v1 as the
 * fallback until the gate adds the three nginx locations (see the
 * ORACLE_DEPLOYMENT.md addendum in this branch). The blocker is now migration +
 * nginx, not server absence. What remains genuinely unimplemented server-side is
 * tracked in `Fast_Fetch/API_V2.md` §17, not here.
 *
 * The rule for the rest of the app: code that would call one of these must be marked with a
 * [EndpointGaps.require] comment at the call site and must degrade to the v1 path, never
 * fail and never fabricate a response. Dropping an entry here means "this install can now
 * reach it and the call site has been switched over", never "the route file exists".
 * Phase 7 dropped four on that rule: PLAY (live via `playV2`), MANIFEST (live as
 * `GET /api/v2/works/{id}` via `getWorkDetailV2` — the `{work_key}` form it named
 * never existed), PRINT_FIELDS and LINK_FIELDS (both served on the v2 detail and
 * mapped by `WireDetailPrint`/`WireDetailLink`).
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
    RESOLVE(
        // Phase 7 (M3): the route this used to name, `/api/v2/links/{link_id}/resolve`,
        // does not exist. The real route is GET /api/v2/resolve/{handle} (the
        // handle is the same opaque stream id the player already carries), served
        // by `catalog_api.py` and called by `CatalogRepository.resolveV2`. It is
        // still a gap only because live nginx has no location for it yet — the
        // gate deploy must add one, or the call 403s at the catch-all. The player
        // already gets the same facts (size/resumable/expiry) through the v1
        // `resolveStream`, so nothing blocks on this.
        needed = "/api/v2/resolve/{handle}",
        blockedCapability = "resolver round-trip for cloud_page/resolve_required links",
        v1Fallback = "/api/v1/stream?id={source_id}&redirect=0",
    ),
    SYNC(
        needed = "/api/v2/sync?since=",
        blockedCapability = "delta sync keyed by work_key (no /api/v1/sync exists)",
        v1Fallback = "re-fetch /api/v1/posts?page=n",
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
