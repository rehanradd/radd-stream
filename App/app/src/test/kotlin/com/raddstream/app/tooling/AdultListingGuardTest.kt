package com.raddstream.app.tooling

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The cached surfaces are checked as text, because the failure this guards is a *wiring* failure
 * and no JVM test can see a `LazyColumn`.
 *
 * `AdultPolicy` is pure and thoroughly tested; the hole it closes was never the absence of a rule
 * but the absence of a call — `MyListViewModel` drew My List straight out of Room and handed the
 * list to `items {}` with nothing in between. A unit test on the rule cannot catch someone
 * deleting the call, and the Robolectric suites that could are excluded on this aarch64 host
 * (`app/build.gradle.kts`, robolectric/robolectric#9166). So this scan asserts the call exists, at
 * the one place each cached surface builds its rows, and it fails if a surface stops naming the
 * rule — which is the mechanical form of "filter at render, not at the network edge".
 *
 * Every refusal below is paired with a positive control, because a scan whose file went missing or
 * whose regex matched nothing would be green by accident, and an accidental green is how
 * `adultFilterEnforced` came to be a literal.
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
    }

    @Test
    fun `a flagged list row cannot become a browse tile`() {
        val mapper = source("network", "models", "V1CatalogMapper.kt")
        assertTrue(
            "defence in depth: the v1 -> v2 door drops a positively-flagged row",
            mapper.contains("filter { it.is18Plus != true }"),
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

    @Test
    fun `a refused detail is called unavailable, not a network hiccup`() {
        val detail = source("viewmodel", "DetailViewModel.kt")
        val catchBlock = detail.substringAfter("catch (ex: HttpException)")
            .substringBefore("} catch (ex: Exception)")
        assertTrue("positive control: the refusal branch was parsed as empty", catchBlock.isNotBlank())
        val goneArm = catchBlock.substringAfter("if (answer == AdultPolicy.ServerAnswer.GONE)")
            .substringBefore("} else {")
        assertTrue("a 404 on a saved id must be recorded as a refusal", goneArm.contains("recordAnswer("))
        assertTrue("and worded as unavailable", goneArm.contains("TITLE_NOT_AVAILABLE"))
        val elseArm = catchBlock.substringAfter("} else {")
        assertFalse(
            "an HTTP status that is not a refusal may not hide a saved row",
            elseArm.contains("recordAnswer("),
        )
        assertTrue("it stays the connection error it always was", elseArm.contains("friendlyNetworkError"))
    }

    @Test
    fun `the flag is modelled and an absent flag is never read as a granted one`() {
        val models = source("network", "models", "Models.kt")
        assertTrue("the flag is modelled now", models.contains("@SerializedName(\"is_18_plus\")"))
        assertFalse(
            "and nothing may read an absent flag as a granted one",
            models.contains("val is18Plus: Boolean = false"),
        )
    }
}
