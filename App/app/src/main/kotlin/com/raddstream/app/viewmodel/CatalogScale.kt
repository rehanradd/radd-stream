package com.raddstream.app.viewmodel

/**
 * The only wording this app may use for the numbers `GET /api/v1/stats` answers.
 *
 * WHY THIS EXISTS. The route reports the ledger's own stored totals, and those totals are not a
 * count of what a viewer can browse here. Measured on the live deployment (2026-10-28) the answer
 * was `posts: 116922` while the projection holds `13342` works flagged `is_18_plus`, and
 * `/api/v1/posts` refuses every flagged row in its own SQL `WHERE` — so the browsable catalog is
 * structurally smaller than the number the server prints. `sources` is a step further: it counts
 * stored link rows, dead ones included, and a dead row has never played anything. The two counts
 * the endpoint answers on two different scopes are recorded in `App/AGENTS.md` §5 and in
 * `App/docs/PARITY_BACKEND_BLOCKED.md`, and the rule that follows from them lives here.
 *
 * THE FIX IS A WORD, NOT A FILTER. A client cannot make a stored total honest by subtracting rows
 * it has not been shown: the adult rows are refused to us, so we could only guess their size. The
 * honest move is to stop calling the number a browsable count — "stored" is exactly what it is,
 * and "works" is the ledger's own word. A surface that genuinely wants "titles you can browse"
 * must ask the list route for its `total` (`/api/v1/posts?limit=1` answers it adult-scoped), not
 * reskin this one.
 *
 * One owner for the phrase, because the same three numbers appear on two screens and in two
 * connection notices: a viewer who reads "Works stored" in Settings and "titles available" in the
 * setup notice has been told two different things by one server.
 */
object CatalogScale {

    /** `stats.posts` — every work in the ledger, including the ones this app must not show. */
    const val WORKS_LABEL: String = "Works stored"

    /** `stats.releases` — release rows on file, which is what the number actually counts. */
    const val RELEASES_LABEL: String = "Releases stored"

    /** `stats.sources` — link rows on file, dead or alive, none of them a promise to play. */
    const val LINKS_LABEL: String = "Links stored"

    /** The line that says what the three numbers below it are not. */
    const val SCOPE_NOTE: String =
        "Stored totals, not a browsable count: they include works this app must not show and " +
            "links that no longer play. Live counts reflect the connected server only."

    /**
     * The notice a successful connection prints. It keeps the server's own figure — a viewer
     * choosing between two servers wants to know which one holds more — and says plainly that
     * what they will find in the grid is fewer.
     */
    fun connectionNotice(posts: Int): String =
        "Connected. This server stores $posts works — the catalog you can browse here is smaller."
}
