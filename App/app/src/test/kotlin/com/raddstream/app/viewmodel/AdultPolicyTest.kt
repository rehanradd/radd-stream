package com.raddstream.app.viewmodel

import com.raddstream.app.data.local.FavoritePost
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The app half of the adult invariant, on the JVM.
 *
 * root `AGENTS.md` states the rule as "no public surface may LIST or PLAY a flagged row". The
 * server enforces its half in SQL and cannot reach this file's subject: a row this device already
 * stored. So everything below is about a *cached* row — which is exactly the case Robolectric would
 * cover on a hosted runner but cannot here (`app/build.gradle.kts` excludes those suites on
 * aarch64), and the reason the rule is a pure object with no Android types rather than a modifier.
 */
class AdultPolicyTest {

    private fun favorite(
        id: Int,
        is18Plus: Boolean? = null,
        checkedAt: Long? = null,
    ) = FavoritePost(
        id = id,
        title = "Title $id",
        cleanTitle = null,
        year = "2024",
        contentType = "movie",
        posterUrl = null,
        imdbRating = null,
        addedAt = 1_000L + id,
        is18Plus = is18Plus,
        checkedAt = checkedAt,
    )

    // ── the listing rule ─────────────────────────────────────────────────────

    @Test
    fun `a cached favourite the payload flagged is never listable`() {
        assertEquals(
            AdultPolicy.Listing.HIDDEN_FLAGGED,
            AdultPolicy.listingFor(is18Plus = true, refusedByServer = false),
        )
        assertFalse(AdultPolicy.mayList(is18Plus = true, refusedByServer = false))
    }

    @Test
    fun `a row the server refused by name is hidden even with no flag on it`() {
        assertEquals(
            AdultPolicy.Listing.HIDDEN_REFUSED,
            AdultPolicy.listingFor(is18Plus = null, refusedByServer = true),
        )
        assertFalse(AdultPolicy.mayList(is18Plus = null, refusedByServer = true))
    }

    @Test
    fun `an undetermined flag is not a true flag`() {
        // This is the case that decides whether My List works at all: the public edge sends no
        // is_18_plus key, so every row this app has ever saved reads null here. Treating null as
        // false would be fine; treating null as true would empty the feature.
        assertTrue(AdultPolicy.mayList(is18Plus = null, refusedByServer = false))
        assertEquals(AdultPolicy.Listing.LISTABLE, AdultPolicy.listingFor(false, false))
    }

    @Test
    fun `a positive flag outranks a friendly answer`() {
        // If a payload ever says flagged while the route serves the id, the stricter fact wins.
        assertEquals(
            AdultPolicy.Listing.HIDDEN_FLAGGED,
            AdultPolicy.listingFor(is18Plus = true, refusedByServer = false),
        )
        assertTrue(AdultPolicy.mayList(is18Plus = false, refusedByServer = false))
    }

    @Test
    fun `listableRows drops a flagged favourite from what a LazyColumn would draw`() {
        val rows = listOf(favorite(1), favorite(2, is18Plus = true), favorite(3))
        val visible = AdultPolicy.listableRows(rows, flagOf = FavoritePost::is18Plus)
        assertEquals(listOf(1, 3), visible.map(FavoritePost::id))
    }

    @Test
    fun `listableRows drops a refused favourite too, and both together`() {
        val rows = listOf(
            favorite(1),
            favorite(2, is18Plus = true),
            favorite(3),
            favorite(4, checkedAt = 9L),
        )
        val refused = setOf(3, 4)
        val visible = AdultPolicy.listableRows(
            rows = rows,
            flagOf = FavoritePost::is18Plus,
            refusedOf = { it.id in refused },
        )
        assertEquals("only the two rows with an answer in their favour survive", listOf(1), visible.map(FavoritePost::id))
    }

    @Test
    fun `the enforcement probe is true while the rule holds and names which leg broke`() {
        assertTrue(
            "Brand.adultFilterEnforced reads this — it must be a fact, not a literal",
            AdultPolicy.enforcesAdultListing,
        )
    }

    // ── what a server round-trip established ────────────────────────────────

    @Test
    fun `a 404 or 410 on a saved id is an answer that hides it`() {
        listOf(404, 410).forEach { status ->
            assertEquals(
                "$status is the refusal the public route gives a flagged row",
                AdultPolicy.ServerAnswer.GONE,
                AdultPolicy.serverAnswerFor(httpStatus = status, bodyClaimsSuccess = null),
            )
        }
    }

    @Test
    fun `a body that says success false is a refusal at any 2xx-shaped status`() {
        assertEquals(
            AdultPolicy.ServerAnswer.GONE,
            AdultPolicy.serverAnswerFor(httpStatus = 200, bodyClaimsSuccess = false),
        )
    }

    @Test
    fun `a served row un-hides itself`() {
        assertEquals(
            AdultPolicy.ServerAnswer.LISTED,
            AdultPolicy.serverAnswerFor(httpStatus = 200, bodyClaimsSuccess = true),
        )
    }

    @Test
    fun `an outage writes nothing`() {
        // The sharpest case in the file. A transport failure has no status, and a reader that
        // inferred "no status means gone" would empty a viewer's list on a plane flight.
        assertEquals(
            AdultPolicy.ServerAnswer.UNANSWERED,
            AdultPolicy.serverAnswerFor(httpStatus = null, bodyClaimsSuccess = null, noAnswer = true),
        )
        listOf(401, 403, 429, 500, 503).forEach { status ->
            assertEquals(
                "$status says nothing about this row's clearance",
                AdultPolicy.ServerAnswer.UNANSWERED,
                AdultPolicy.serverAnswerFor(httpStatus = status, bodyClaimsSuccess = null),
            )
        }
    }

    // ── the revalidation pass ───────────────────────────────────────────────

    @Test
    fun `a row that has never been asked about is due immediately`() {
        assertTrue(AdultPolicy.needsRevalidation(lastCheckedAtMs = null, nowMs = 0L))
        assertFalse(AdultPolicy.needsRevalidation(nowMs = 1_000L, lastCheckedAtMs = 1_000L))
    }

    @Test
    fun `a row is due once its answer is older than the ttl and not before`() {
        val day = AdultPolicy.REVALIDATE_AFTER_MS
        assertFalse(AdultPolicy.needsRevalidation(lastCheckedAtMs = 0L, nowMs = day - 1))
        assertTrue(AdultPolicy.needsRevalidation(lastCheckedAtMs = 0L, nowMs = day))
    }

    @Test
    fun `one pass checks the stalest rows and stops at its cap`() {
        // Positive control built from a library larger than the cap: a scan that selected nothing
        // would also "not exceed the cap" and prove nothing.
        val rows = (1..(AdultPolicy.MAX_REVALIDATION_CHECKS_PER_PASS + 5)).map { index ->
            favorite(index, checkedAt = index.toLong())
        }
        val selected = AdultPolicy.selectForRevalidation(rows, checkedAtOf = FavoritePost::checkedAt, nowMs = Long.MAX_VALUE / 2)
        assertEquals(AdultPolicy.MAX_REVALIDATION_CHECKS_PER_PASS, selected.size)
        assertEquals(
            "stalest first, so the least-recently-answered rows are the ones asked",
            (1..AdultPolicy.MAX_REVALIDATION_CHECKS_PER_PASS).toList(),
            selected.map(FavoritePost::id),
        )
    }

    @Test
    fun `a never-checked row sorts ahead of a checked one`() {
        val rows = listOf(favorite(7, checkedAt = 5L), favorite(8), favorite(9, checkedAt = 1L))
        val selected = AdultPolicy.selectForRevalidation(
            rows,
            checkedAtOf = FavoritePost::checkedAt,
            nowMs = AdultPolicy.REVALIDATE_AFTER_MS + 100L,
        )
        assertEquals(
            "an unanswered row sorts ahead of every answered one, then oldest answer first",
            listOf(8, 9, 7),
            selected.map(FavoritePost::id),
        )
    }

    @Test
    fun `a clock that moved backwards does not make a row due forever`() {
        val rows = listOf(favorite(1, checkedAt = Long.MAX_VALUE))
        assertTrue(
            "a future stamp is treated as fresh, not as the stalest row in the library",
            AdultPolicy.selectForRevalidation(rows, checkedAtOf = FavoritePost::checkedAt, nowMs = 0L).isEmpty(),
        )
    }

    // ── what the viewer is told ─────────────────────────────────────────────

    @Test
    fun `the hidden notice counts and never names`() {
        assertNull(AdultPolicy.hiddenNotice(0))
        val one = AdultPolicy.hiddenNotice(1)!!
        val many = AdultPolicy.hiddenNotice(3)!!
        listOf(one, many).forEach { line ->
            assertFalse("a notice that quotes a title is a list of one: $line", line.contains("Title"))
            assertTrue(line, line.contains("1") || line.contains("3"))
        }
        assertTrue(one, one.startsWith("1 "))
        assertTrue(many, many.startsWith("3 "))
    }
}
