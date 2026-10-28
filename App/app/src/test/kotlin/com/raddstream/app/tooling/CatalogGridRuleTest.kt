package com.raddstream.app.tooling

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * A placeholder that is shaped differently from the content it stands in for is a page that
 * jumps: the skeleton grid used to be `Fixed(3)` while both real catalog grids were
 * `Adaptive(minSize = 120.dp)`, so on a wide phone the shimmers filled three columns and the
 * posters arrived in four. The fix was one shared value, and a shared value is only an owner if
 * nobody re-declares it — which is exactly what an agent adding the next grid will do, because
 * a literal column count is the shape every Compose tutorial shows.
 *
 * A text scan can answer this without guessing: find every grid, read what it passes for
 * columns.
 */
class CatalogGridRuleTest {

    private fun mainSources(): List<File> =
        File("src/main/kotlin").walkTopDown()
            .filter { it.isFile && it.extension == "kt" }
            .toList()
            .also { assertTrue("must run from the app module directory", it.isNotEmpty()) }

    @Test
    fun `one file owns the catalog grid column rule and no grid re-declares it`() {
        val sources = mainSources()
        val declarations = sources.flatMap { file ->
            Regex("""GridCells\.(Fixed|Adaptive)""")
                .findAll(file.readText())
                .map { "${file.path}:${it.value}" }
                .toList()
        }
        assertEquals(
            "a second column rule is a second answer to how many posters fit, and the skeleton " +
                "will disagree with a grid again: $declarations",
            listOf("src/main/kotlin/com/raddstream/app/ui/components/CommonUi.kt:GridCells.Adaptive"),
            declarations,
        )

        val grids = sources.flatMap { file ->
            file.readText().lines().mapIndexedNotNull { index, line ->
                if ("LazyVerticalGrid(" in line) "${file.path}:${index + 1}" else null
            }
        }
        assertTrue("the app must actually have grids to check", grids.isNotEmpty())

        val unsourced = sources.flatMap { file ->
            val text = file.readText()
            Regex("""LazyVerticalGrid\(""").findAll(text)
                .filter { match ->
                    // The arguments of a grid are the few lines after the call opens.
                    val args = text.substring(match.range.last, minOf(text.length, match.range.last + 220))
                    !"""columns = CatalogGridColumns""".toRegex().containsMatchIn(args)
                }
                .map { match ->
                    "${file.path}:${text.substring(0, match.range.last).count { it == '\n' } + 1}"
                }
                .toList()
        }
        assertTrue(
            "every poster grid draws its columns from the shared rule, or the skeleton cannot " +
                "match it: $unsourced",
            unsourced.isEmpty(),
        )
    }

    /** The guard needs a guard: these shapes must be told apart, not guessed at. */
    @Test
    fun `the scanner separates a re-declared rule from the shared one`() {
        val declarations = Regex("""GridCells\.(Fixed|Adaptive)""")
        assertTrue("a grid that names its own column count is found", declarations.containsMatchIn(GRID_WITH_FIXED))
        assertTrue("a grid fed the shared value is not a declaration", !declarations.containsMatchIn(GRID_WITH_RULE))
        assertTrue("an import line is neither", !declarations.containsMatchIn(IMPORT_ONLY))
        assertTrue("a grid fed the shared rule passes", argsOf(GRID_WITH_RULE).contains("columns = CatalogGridColumns"))
        assertTrue("a grid fed its own count fails", !argsOf(GRID_WITH_FIXED).contains("columns = CatalogGridColumns"))
    }

    private fun argsOf(source: String): String {
        val start = source.indexOf("LazyVerticalGrid(")
        assertTrue("the fixture must contain a grid call", start >= 0)
        return source.substring(start, minOf(source.length, start + 220))
    }

    private companion object {
        const val IMPORT_ONLY = "import androidx.compose.foundation.lazy.grid.LazyVerticalGrid"
        const val GRID_WITH_RULE =
            "@Composable fun Grid() {\n    LazyVerticalGrid(\n        columns = CatalogGridColumns,\n" +
                "        modifier = Modifier.fillMaxSize(),\n    )\n}"
        const val GRID_WITH_FIXED =
            "@Composable fun Grid() {\n    LazyVerticalGrid(\n        columns = GridCells.Fixed(3),\n" +
                "        modifier = Modifier.fillMaxSize(),\n    )\n}"
    }
}
