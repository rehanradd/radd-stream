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

    @Test
    fun `the connection notice keeps the server figure and says the catalog is smaller`() {
        val notice = CatalogScale.connectionNotice(116_922)

        assertTrue(notice.contains("116922"))
        assertTrue("the number is the server's stored count", notice.contains("stores"))
        assertTrue("and the viewer is told it is not what they will see", notice.contains("smaller"))
        assertFalse(notice.contains("available"))
        assertFalse(notice.contains("title"))
    }

    @Test
    fun `the scope note states the two ways the totals exceed the catalog`() {
        val note = CatalogScale.SCOPE_NOTE

        assertTrue(note.contains("Stored totals"))
        assertTrue("the adult rows the ledger holds and the app hides", note.contains("must not show"))
        assertTrue("the dead link rows", note.contains("no longer play"))
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
