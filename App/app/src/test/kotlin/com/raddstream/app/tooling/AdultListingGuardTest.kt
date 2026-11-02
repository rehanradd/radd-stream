package com.raddstream.app.tooling

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The cached surfaces are checked as text, because the failure this guards is a *wiring* failure
 * and no JVM test can see a `LazyColumn`.
 *
 * `AdultPolicy` is pure and thoroughly tested by [com.raddstream.app.viewmodel.AdultPolicyTest];
 * the hole it closes was never the absence of a rule but the absence of a call — My List drew
 * straight out of Room and handed the list to `items {}` with nothing in between, and Home did the
 * same with its resume rail. A unit test on the rule cannot catch someone deleting the call, and
 * the Robolectric suites that could are excluded on this aarch64 host (`app/build.gradle.kts`,
 * robolectric/robolectric#9166). So this scan asserts the call exists, at the one place each
 * cached surface builds its rows, and it fails if a surface stops naming the rule — which is the
 * mechanical form of "filter at render, not at the network edge".
 *
 * Every refusal below is paired with a positive control, because a scan whose file went missing or
 * whose regex matched nothing would be green by accident, and an accidental green is how
 * `adultFilterEnforced` came to be a literal.
 *
 * Scope, stated rather than implied: this file pins the two surfaces that filter today — My List
 * and Continue watching. Two more are known and not yet wired, and they are listed in
 * `docs/checkpoints` for this slice rather than silently dropped: a detail screen whose 404 arm
 * still reads as a connection error, and the stream door, whose `REASON_STREAM` value the ledger
 * declares but nothing writes. A guard that pretended those were covered would be the same kind
 * of lie as `= true`.
 */
class AdultListingGuardTest {

    private val srcRoot: File by lazy {
        var dir: File? = File("").absoluteFile
        while (dir != null) {
            val candidate = File(dir, "App/app/src/main/kotlin/com/raddstream/app")
            if (candidate.isDirectory) return@lazy candidate
            dir = dir.parentFile
        }
        error("no app source tree above ${File("").absolutePath}")
    }

    private fun source(vararg path: String): String {
        val file = File(srcRoot, path.joinToString("/"))
        assertTrue("${file.path} is gone — this guard has been looking at nothing", file.isFile)
        return file.readText()
    }

    /** Every production Kotlin file, for a rule that must hold wherever it is written. */
    private fun mainSources(): List<File> =
        srcRoot.walkTopDown().filter { it.isFile && it.extension == "kt" }.toList().also {
            assertTrue("positive control: the scan found no production sources at all", it.size > 20)
        }

    @Test
    fun `my list filters its Room rows through the policy before they become tiles`() {
        val viewModel = source("viewmodel", "MyListViewModel.kt")
        assertTrue(
            "positive control: MyListViewModel no longer builds the grid's row list at all",
            viewModel.contains("favorites = sorted.map(FavoritePost::toPost)"),
        )
        assertTrue(
            "a cached favourite reaches a LazyColumn only through AdultPolicy",
            viewModel.contains("AdultPolicy.listableRows("),
        )
        assertTrue(
            "the filter must be applied to the stored rows, not to a copy someone made after sorting",
            viewModel.contains("rows = list"),
        )
        assertTrue("and the refusal ledger is one of its inputs", viewModel.contains("observeRefusedIds()"))
        assertFalse(
            "no branch of this screen may draw from the unfiltered list",
            viewModel.contains("favorites = list.map(FavoritePost::toPost)"),
        )
    }

    @Test
    fun `continue watching is filtered like any other cached surface`() {
        val home = source("viewmodel", "HomeViewModel.kt")
        assertTrue(
            "a resume row names a work this device watched, and the ledger may have refused it since",
            home.contains("AdultPolicy.listableRows("),
        )
        assertTrue(home.contains("favoritesRepository.observeRefusedIds()"))
        assertTrue(
            "positive control: the rail is still built from the merged rows",
            home.contains("rows.mapNotNull { ResumeTile.of(it) }"),
        )
        assertTrue(
            "the rail keys its check on the post id the resume row carries, not on a title",
            home.contains("refusedOf = { it.postId in refused }"),
        )
    }

    @Test
    fun `the refusal ledger records on an answer and writes nothing on silence`() {
        val repo = source("repository", "FavoritesRepository.kt")
        val gone = repo.substringAfter("AdultPolicy.ServerAnswer.GONE ->")
            .substringBefore("AdultPolicy.ServerAnswer.UNANSWERED ->")
        assertTrue("a refusal must mark the row", gone.contains("unavailableDao.record("))
        assertTrue("and stamp when it happened, or the row is due again next frame", gone.contains("favoriteDao.recordAnswer("))
        val listed = repo.substringAfter("AdultPolicy.ServerAnswer.LISTED ->")
            .substringBefore("AdultPolicy.ServerAnswer.GONE ->")
        assertTrue("a served row clears its own refusal", listed.contains("unavailableDao.clear("))
        val unanswered = repo.substringAfter("AdultPolicy.ServerAnswer.UNANSWERED ->")
            .substringBefore("}")
        assertTrue(
            "an outage may not write a refusal: $unanswered",
            unanswered.isBlank() || unanswered.trim() == "Unit",
        )
        assertTrue(
            "positive control: the scan found the three arms it claims to have read",
            repo.contains("AdultPolicy.ServerAnswer.LISTED ->") &&
                repo.contains("AdultPolicy.ServerAnswer.GONE ->") &&
                repo.contains("AdultPolicy.ServerAnswer.UNANSWERED ->"),
        )
    }

    @Test
    fun `the revalidation pass is bounded and its caller does not await it`() {
        val repo = source("repository", "FavoritesRepository.kt")
        val pass = repo.substringAfter("suspend fun revalidateSavedRows()")
            .substringBefore("/** Best effort")
        assertTrue("positive control: the pass body was parsed", pass.isNotBlank())
        assertTrue(
            "a pass that walked the whole library would be throttled by its own compliance check",
            pass.contains("AdultPolicy.selectForRevalidation("),
        )
        assertFalse(
            "the pass must not invent a flag answer the payload never gave",
            pass.contains("flag = false"),
        )

        val viewModel = source("viewmodel", "MyListViewModel.kt")
        val init = viewModel.substringAfter("init {").substringBefore("    fun setSort")
        assertTrue("opening the screen asks, bounded", init.contains("revalidateSavedRows()"))
        assertTrue(
            "and never blocks the list the viewer came to read",
            init.contains("catch (cancelled: CancellationException)"),
        )
        assertFalse(
            "an answer-less probe may not be recorded as a refusal",
            viewModel.contains("ServerAnswer.GONE"),
        )
    }

    @Test
    fun `adultFilterEnforced is computed from the rule and never returned as a literal`() {
        val brand = source("brand", "Brand.kt")
        val body = brand.substringAfter("val adultFilterEnforced")
            .substringBefore("\n")
        assertTrue(
            "the flag must read the policy it is claiming: $body",
            body.contains("AdultPolicy.enforcesAdultListing"),
        )
        assertFalse(
            "a hardcoded `= true` here is the exact lie this guard exists to keep retired",
            Regex("""val adultFilterEnforced[^=]*=\s*true""").containsMatchIn(brand),
        )
        val policy = source("viewmodel", "AdultPolicy.kt")
        assertTrue(
            "positive control: the probe the flag reads still exists",
            policy.contains("val enforcesAdultListing"),
        )
    }

    /**
     * The flag is modelled in exactly one place, and it is not the wire.
     *
     * Measured 2026-11-01 against the live public edge: `post_brief` and `post_detail` both send
     * `is_animated` and neither sends `is_18_plus` — and that is not a gap in the projection, it is
     * the design: a flagged row is answered 404, so a row that arrives at all arrived unflagged. A
     * `Post.is18Plus` field would therefore be permanently null, which is the shape `App/AGENTS.md`
     * §6 already retired once ("they mapped keys the API never returns, so they were permanently
     * null and silently killed season/episode grouping").
     *
     * If a projection ever does publish the key, this test is the door: add the field to the wire
     * model, drop the refusal below, and carry the flag into `FavoritePost.fromPost` — the rest of
     * the rule already reads the column and needs nothing else.
     */
    @Test
    fun `the flag is a stored answer, never a phantom wire field or an invented default`() {
        val entity = source("data", "local", "FavoritePost.kt")
        assertTrue(
            "positive control: the column is declared, nullable and undefaulted",
            entity.contains("val is18Plus: Boolean? = null,"),
        )
        assertFalse(
            "a non-nullable flag column would silently un-hide every row this server has ever 404d",
            Regex("""val is18Plus: Boolean = """).containsMatchIn(entity),
        )

        val models = source("network", "models", "Models.kt")
        // This scans code shapes on purpose. `Models.kt`'s own header rule (item 4) spells the key
        // out to forbid it, so a bare "the string must not appear in the file" pin fails on the
        // documentation of the very rule it is enforcing — which is what this assertion did on
        // hosted CI at `98933db`. What must be absent is a field, and a field has two shapes.
        assertFalse(
            "the public projection sends no is_18_plus key, so a @SerializedName for it would be a " +
                "permanently-null phantom field — see the KDoc on this test",
            Regex("""@SerializedName\(\s*"is_18_plus\b""").containsMatchIn(models),
        )
        assertFalse(
            "and no property carries the flag onto the wire either",
            Regex("""\bis18Plus\b""").containsMatchIn(models),
        )
        assertTrue(
            "positive control: the two scans above reject a real phantom field, they are not " +
                "matching nothing",
            Regex("""@SerializedName\(\s*"is_18_plus\b""").containsMatchIn(
                """@SerializedName("is_18_plus") val is18Plus: Boolean? = null,""",
            ),
        )
        mainSources().forEach { file ->
            val text = file.readText()
            assertFalse(
                "${file.name} passes is18Plus = false, which turns \"the server never told us\" into " +
                    "\"the server cleared it\"",
                text.contains("is18Plus = false"),
            )
        }
    }
}
