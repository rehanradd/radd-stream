package com.raddstream.app.viewmodel

/**
 * The app's one listing rule for adult-flagged work, and the one classifier of what a server
 * answer means for a row this device stored.
 *
 * Why this file exists. The invariant (root `AGENTS.md`) is "no public surface may LIST or PLAY a
 * flagged row". The server enforces its half in SQL, so a phone never sees a flagged row in a
 * fresh catalog read — but this app also *keeps* rows: favourites in `favorite_posts`, resume
 * points in `watch_history`, kept-file tasks. Those are rendered from local storage with no
 * network in the loop, and a row that was public when it was saved can be flipped hidden afterwards
 * (the `canonical_key` twin reconciliation the backend is mid-way through is exactly that: today's
 * unflagged twin becomes tomorrow's 404). A cached row that outlives its own clearance is the app
 * half of the hole, and no `WHERE` clause on the server can reach it.
 *
 * What the wire can and cannot tell us, measured 2026-10-29: the flag NEVER arrives on the public
 * port. `api_v1_get_post_detail` bails before building a body when `post["is_18_plus"]` is set
 * (`Fast_Fetch/viewer.py:2677`), `redact.project(row, "post_detail")` whitelists only
 * `_IDENTITY | _TITLE | {releases, option_groups}` (`Fast_Fetch/redact.py:208`), and the un-redacted
 * `full` view is switched on by the *server instance*, never by a request parameter
 * (`viewer.py:3109` and `:3465`, both `full = bool(getattr(self.server, "operator", False))`). So
 * [is18Plus] is modelled as the nullable it must be — a fact the app records whenever a payload
 * does carry it (an operator-port probe, a future projection that publishes the flag) and never
 * invents — and the enforcement that works against today's server is the refusal: an id the public
 * route answers 404 for is, by the ledger's own design, indistinguishable from a flagged one and
 * treated the same way here.
 *
 * Two consequences that are decisions, not omissions:
 *  - A hidden cached row is **not deleted**. The refusal is an answer about the server's state, not
 *    about the viewer's intent; a purge would cost a saved list to a flag flip that may be reversed
 *    by the next reconciliation. The row is marked, marked rows never reach a `LazyColumn`, and a
 *    later 200 un-marks them. "Cannot persist" in the invariant means *cannot be listed*.
 *  - A row is hidden only on an **answer**. A timeout, a DNS failure or a 5xx says nothing about the
 *    row's clearance, so it must never hide or un-hide anything: an outage that emptied My List
 *    would be a different bug wearing a compliance badge.
 */
object AdultPolicy {

    /** What this rule decided about one stored row. */
    enum class Listing {
        /** May be rendered. */
        LISTABLE,

        /** A payload positively told us it is adult-flagged. Never rendered, never badged. */
        HIDDEN_FLAGGED,

        /** The public route 404s the id: flagged or gone, and either way not ours to list. */
        HIDDEN_REFUSED,
    }

    /** What a server round-trip about a saved id actually established. */
    enum class ServerAnswer {
        /** The row is served: it may be listed, and any earlier refusal of it is void. */
        LISTED,

        /** The row is refused by name (404/410, or a body that says so). Hide it. */
        GONE,

        /** No answer, or an answer that does not speak about this row. Change nothing. */
        UNANSWERED,
    }

    /** Status codes that mean "this id is not offered to you", and nothing else may imply it. */
    private val REFUSING_STATUSES = setOf(404, 410)

    /**
     * The whole listing rule, in one call. `is18Plus == null` is **not** `false`: an undetermined
     * row is listable, because the rows this app has never been told about are the ordinary bulk of
     * a viewer's library and hiding them would "fix" the hole by breaking the feature.
     *
     * A positive flag outranks a later 200, on purpose: if a payload ever says `is_18_plus = 1`
     * while the ledger says the id is fine, the flag is the stricter fact and the invariant is not
     * the place to prefer the friendlier one.
     */
    fun listingFor(is18Plus: Boolean?, refusedByServer: Boolean): Listing = when {
        is18Plus == true -> Listing.HIDDEN_FLAGGED
        refusedByServer -> Listing.HIDDEN_REFUSED
        else -> Listing.LISTABLE
    }

    fun mayList(is18Plus: Boolean?, refusedByServer: Boolean): Boolean =
        listingFor(is18Plus, refusedByServer) == Listing.LISTABLE

    /**
     * The same rule, applied to a whole cached surface, so every screen that draws from local
     * storage filters through one function instead of one `if` per screen. `refusedOf` is a
     * predicate rather than a `Set<Int>` + id getter because the two cached tables name their row
     * differently (`favorite_posts.id` is a post id; a resume row is keyed by work handle and only
     * *carries* a post id) — and a surface that has nothing to check passes the default.
     */
    fun <Row> listableRows(
        rows: List<Row>,
        flagOf: (Row) -> Boolean?,
        refusedOf: (Row) -> Boolean = { false },
    ): List<Row> = rows.filter { mayList(flagOf(it), refusedByServer = refusedOf(it)) }

    /**
     * Whether this rule is, right now, actually enforcing the invariant — three questions asked of
     * [listingFor] itself rather than asserted about it.
     *
     * This exists because `Brand.adultFilterEnforced` used to be `get() = true` with nothing behind
     * it, and a name like that gets read as evidence. A probe that returns a literal cannot be
     * wrong; this one can, and it goes false the moment any of the three answers moves: a
     * positively flagged row must never list, a row the server refused must never list, and a plain
     * row must still list (the third is what stops the rule from being "hide everything", which
     * would satisfy the first two and delete the product).
     */
    val enforcesAdultListing: Boolean
        get() = !mayList(is18Plus = true, refusedByServer = false) &&
            !mayList(is18Plus = null, refusedByServer = true) &&
            mayList(is18Plus = null, refusedByServer = false)

    /**
     * Classify a `/api/v1/posts/{id}` round-trip. Deliberately fed primitives rather than a
     * Retrofit type, so the rule that decides whether a viewer's saved list survives an outage is
     * testable without a network, a mock server or a device.
     *
     * Order matters: [noAnswer] is checked first, because a transport failure has no status and a
     * reader that reached for `httpStatus == null -> GONE` would empty My List on a plane flight.
     */
    fun serverAnswerFor(
        httpStatus: Int?,
        bodyClaimsSuccess: Boolean?,
        noAnswer: Boolean = false,
    ): ServerAnswer = when {
        noAnswer -> ServerAnswer.UNANSWERED
        httpStatus in REFUSING_STATUSES -> ServerAnswer.GONE
        bodyClaimsSuccess == false -> ServerAnswer.GONE
        bodyClaimsSuccess == true && (httpStatus == null || httpStatus in 200..299) ->
            ServerAnswer.LISTED
        else -> ServerAnswer.UNANSWERED
    }

    // ── Revalidation ─────────────────────────────────────────────────────────

    /**
     * How old a saved row's last server answer must be before it is worth asking again. A day,
     * because the fact being re-checked changes on the cadence of a catalog reconciliation, not of
     * a screen visit — and because the same server puts every request in a token bucket
     * (`Fast_Fetch/viewer.py:_bucket_for`), so a re-check on every navigation is both impolite and
     * the first thing to get a viewer throttled.
     */
    const val REVALIDATE_AFTER_MS: Long = 24L * 60L * 60L * 1000L

    /**
     * How many rows one pass may ask about. My List can hold hundreds of rows; a pass that walked
     * all of them would be a self-inflicted denial-of-service on the only server this app has, so
     * the stalest rows are checked first and the rest wait for the next time the screen is open.
     */
    const val MAX_REVALIDATION_CHECKS_PER_PASS: Int = 12

    /** True when we have never asked, or the last answer is older than the TTL. */
    fun needsRevalidation(
        lastCheckedAtMs: Long?,
        nowMs: Long,
        ttlMs: Long = REVALIDATE_AFTER_MS,
    ): Boolean = lastCheckedAtMs == null || nowMs - lastCheckedAtMs >= ttlMs

    /**
     * The rows one pass should ask about, stalest first, capped at
     * [MAX_REVALIDATION_CHECKS_PER_PASS]. A row whose answer is in the future (a clock that moved
     * backwards) is treated as needing no check rather than hammering it every visit.
     */
    fun <Row> selectForRevalidation(
        rows: List<Row>,
        checkedAtOf: (Row) -> Long?,
        nowMs: Long,
        ttlMs: Long = REVALIDATE_AFTER_MS,
        limit: Int = MAX_REVALIDATION_CHECKS_PER_PASS,
    ): List<Row> = rows
        .filter { needsRevalidation(checkedAtOf(it), nowMs, ttlMs) }
        .sortedBy { checkedAtOf(it) ?: Long.MIN_VALUE }
        .take(limit.coerceAtLeast(0))

    // ── What the viewer is told ──────────────────────────────────────────────

    /**
     * The only sentence this app may say about hidden rows, and it names a number because a number
     * is the only thing that can be said without listing something. A hidden title must not come
     * back on screen as "unavailable: <title>" — that is a list of one.
     */
    fun hiddenNotice(hiddenCount: Int): String? = when {
        hiddenCount <= 0 -> null
        hiddenCount == 1 -> "1 saved title is no longer offered by this server."
        else -> "$hiddenCount saved titles are no longer offered by this server."
    }
}
