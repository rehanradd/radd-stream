package com.raddstream.app.tooling

import com.raddstream.app.viewmodel.CatalogScale
import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * What a stored total is allowed to be called.
 *
 * `GET /api/v1/stats` answers the ledger's own counts, and the live deployment proves those counts
 * are not a browsable catalog: `posts: 116922` while the projection holds `13342` works flagged
 * `is_18_plus`, every one of which `/api/v1/posts` refuses in its own SQL. `sources` counts stored
 * link rows, dead included. So a screen that labels those numbers "Titles", "Streams" or "N
 * catalog titles available" is promising content the app is forbidden to show — and no client-side
 * filter can repair it, because the rows being hidden are precisely the ones we cannot count.
 *
 * The fix is one wording owner (`CatalogScale`) plus this scan, which checks the screens actually
 * use it. The positive controls are the load-bearing part: a test that only asserts a phrase is
 * absent is green when a file is renamed, when the stats block is deleted, and when the whole
 * screen stops showing numbers at all. Every refusal below is paired with a fact that must still
 * be present.
 */
class StatsHonestyTest {

    private val repoRoot: File by lazy {
        var dir: File? = File("").absoluteFile
        while (dir != null) {
            if (File(dir, "brand.properties").isFile) return@lazy dir
            dir = dir.parentFile
        }
        error("brand.properties not found above ${File("").absolutePath}")
    }

    private fun source(path: String): File = File(repoRoot, path).also {
        assertTrue("the audit has nothing to read at $path", it.isFile)
    }

    private val settingsScreen = source(
        "App/app/src/main/kotlin/com/raddstream/app/ui/screens/SettingsScreen.kt",
    )
    private val setupViewModel = source(
        "App/app/src/main/kotlin/com/raddstream/app/viewmodel/SetupViewModel.kt",
    )
    private val settingsViewModel = source(
        "App/app/src/main/kotlin/com/raddstream/app/viewmodel/SettingsViewModel.kt",
    )

    // ── the wording owner itself ──────────────────────────────────────────────

    @Test
    fun `every stats label names the number as stored, never as something to browse`() {
        for (label in listOf(
            CatalogScale.WORKS_LABEL,
            CatalogScale.RELEASES_LABEL,
            CatalogScale.LINKS_LABEL,
        )) {
            assertTrue("'$label' must say stored", label.endsWith("stored"))
            assertFalse("'$label' promises a title the app may not show", label.contains("Title"))
            assertFalse("'$label' promises a stream that may be dead", label.contains("Stream"))
        }
        assertTrue(CatalogScale.WORKS_LABEL.startsWith("Works"))
        assertTrue(CatalogScale.LINKS_LABEL.startsWith("Links"))
    }

    /**
     * The notice must keep the server's figure and refuse to size it against the catalog. The
     * direction is the load-bearing half: 2026-10-28 measured `stats.posts` as the LARGER number
     * (the projection carries adult-flagged rows the list route refuses), 2026-10-29 measured it as
     * the SMALLER one (`116922` against a browsable `total` of `131559`, then `134815`) because the
     * endpoint answers from `cat_projection_meta` while the list route counts the live table. Both
     * sentences were confident and one of them was wrong on the day it shipped, so an arrow of either
     * sign is now a failure rather than a wording preference.
     */
    @Test
    fun `the connection notice keeps the server figure and never compares its size`() {
        for (posts in listOf(116_922, 0)) {
            val notice = CatalogScale.connectionNotice(posts)

            assertTrue(notice.contains(posts.toString()))
            assertTrue("the number is the server's stored count", notice.contains("stores"))
            assertTrue(
                "and the viewer is told it is not what the grid answers with",
                notice.contains("not the count you can browse"),
            )
            assertFalse(notice.contains("available"))
            assertFalse(notice.contains("title"))
            for (arrow in listOf("smaller", "larger", "bigger", "fewer", "more works", "above", "below")) {
                assertFalse(
                    "a $posts-work server must not be described as $arrow the browsable catalog",
                    notice.contains(arrow),
                )
            }
        }
    }

    @Test
    fun `the scope note names what a stored tally can contain without claiming a direction`() {
        val note = CatalogScale.SCOPE_NOTE

        assertTrue(note.contains("Stored totals"))
        assertTrue("the adult rows the ledger holds and the app hides", note.contains("must not show"))
        assertTrue("the dead link rows", note.contains("no longer play"))
        // Staleness is the second reason the number is not a browsable count, and the only one
        // that survived the 2026-10-29 re-measurement, so it has to be said out loud.
        assertTrue("a projection tally can lag the table the list route counts", note.contains("lag"))
        // "can", never "does": the note describes possibilities, not an ordering.
        assertTrue(note.contains("can include"))
        assertFalse(note.contains("are larger"))
        assertFalse(note.contains("are smaller"))
    }

    // ── the surfaces, which must actually speak with that one owner ───────────

    @Test
    fun `no stats surface calls a stored total a title or a stream`() {
        val forbidden = listOf("catalog titles available", "label = \"Titles\"", "\"Streams\"")
        for (file in listOf(settingsScreen, setupViewModel, settingsViewModel)) {
            val code = file.readText()
            forbidden.forEach { phrase ->
                assertFalse("${file.name} still says $phrase", code.contains(phrase))
            }
        }
    }

    @Test
    fun `the three surfaces all ask the single owner and the numbers are still on screen`() {
        // Positive controls: the refusal above would also pass on a file that renders nothing.
        assertTrue(
            "Settings draws its totals through the owner",
            settingsScreen.readText().contains("CatalogScale.WORKS_LABEL"),
        )
        assertTrue(
            "and the server counts are still painted, not quietly removed",
            settingsScreen.readText().contains("stats.posts.toString()"),
        )
        assertTrue(settingsScreen.readText().contains("CatalogScale.SCOPE_NOTE"))
        assertTrue(
            "setup speaks through the owner",
            setupViewModel.readText().contains("CatalogScale.connectionNotice(stats.posts)"),
        )
        assertTrue(
            "so does the settings connection test",
            settingsViewModel.readText().contains("CatalogScale.connectionNotice(stats.posts)"),
        )
    }

    @Test
    fun `the wire model still carries the counts this screen is not allowed to overclaim`() {
        // A guard against the easy wrong fix: deleting the field, or trusting `active_sources`
        // because it sounds like a live count. The projection tally is not adult-scoped on either
        // path of the endpoint (App/AGENTS.md §5), so no field here may be renamed into a promise.
        val models = source("App/app/src/main/kotlin/com/raddstream/app/network/models/Models.kt")
            .readText()

        assertTrue(models.contains("val posts: Int = 0"))
        assertTrue(models.contains("val releases: Int = 0"))
        assertTrue(models.contains("val sources: Int = 0"))
        assertFalse(
            "the wire type keeps the server's name for the number",
            models.contains("val browsableTitles"),
        )
    }
}
