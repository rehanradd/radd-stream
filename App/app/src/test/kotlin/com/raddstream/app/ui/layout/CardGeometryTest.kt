package com.raddstream.app.ui.layout

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * CardGeometryTest — guards idea #7 ("one fixed card aspect ratio everywhere") on the JVM.
 *
 * Plain JUnit4, no Robolectric, no Android runtime: like [com.raddstream.app.brand.BrandDriftTest]
 * it reads the sources from disk and inspects them, so it runs anywhere a JDK + junit4 exist and
 * it fails in CI rather than on a phone nobody has here.
 *
 * Why a source scan and not a layout assertion: nothing on these screens is *wrong* when a rail
 * placeholder is 190dp and the card that replaces it is 194dp. The row looks fine, reflows on the
 * frame the data lands on, and the drift is invisible to every other test in the fleet. The only
 * honest gate is the one that says a second copy of a geometry number may not be written.
 *
 * It fails when:
 *  1. an `aspectRatio(…)` call in the UI sources passes a number instead of a [CardGeometry]
 *     constant (a per-screen decision about a shared shape);
 *  2. a poster ratio, a rail tile width or a rail tile height is written outside [CardGeometry];
 *  3. the rail placeholder stops being built from [CardGeometry.RAIL_CARD_WIDTH_DP] and
 *     [CardGeometry.POSTER_ASPECT], i.e. someone pins a height or a width of their own and lets
 *     the placeholder jump under the thumb when the real cards land.
 */
class CardGeometryTest {

    private val repoRoot: File by lazy {
        var dir: File? = File("").absoluteFile
        while (dir != null) {
            if (File(dir, "App/app/src/main").isDirectory) return@lazy dir
            dir = dir.parentFile
        }
        error("App/app/src/main not found above ${File("").absolutePath}")
    }

    private val uiDir: File get() = File(repoRoot, "App/app/src/main/kotlin/com/raddstream/app/ui")

    private val geometryPath = "App/app/src/main/kotlin/com/raddstream/app/ui/layout/CardGeometry.kt"

    private val commonUiPath = "App/app/src/main/kotlin/com/raddstream/app/ui/components/CommonUi.kt"

    private fun File.relativeToRoot(): String {
        val prefix = repoRoot.absolutePath.replace(File.separatorChar, '/') + "/"
        val path = absolutePath.replace(File.separatorChar, '/')
        return if (path.startsWith(prefix)) path.removePrefix(prefix) else path
    }

    /** Every UI source, comments already stripped so prose about a number is not read as the number. */
    private fun sourcesByPath(): Map<String, String> =
        uiDir.walkTopDown()
            .filter { it.isFile && it.extension == "kt" }
            .associate { it.relativeToRoot() to it.readText().withoutComments() }

    /** A float literal, optionally as a division like `16f / 9f`. */
    private val numberLiteral = Regex("""[0-9]+(?:\.[0-9]+)?f?(?:\s*/\s*[0-9]+f?)?""")

    // ── 1. no screen decides its own shape ───────────────────────────────────
    @Test
    fun everyAspectRatioComesFromCardGeometry() {
        val offenders = sourcesByPath()
            .filter { (path, body) ->
                path != geometryPath &&
                    Regex("""aspectRatio\(([^)]*)\)""")
                        .findAll(body)
                        .any { numberLiteral.containsMatchIn(it.groupValues[1]) }
            }
            .keys
            .sorted()
        assertEquals(
            "a screen wrote a card shape of its own — name a CardGeometry constant instead " +
                "(see design/DESIGN_SYSTEM.md §8)",
            emptyList<String>(),
            offenders,
        )
        // Show the scan reads what it claims to read: the call sites exist, one of them a variable
        // (a skeleton's own parameter) and the rest tokens.
        val calls = sourcesByPath().values.sumOf { Regex("""aspectRatio\(""").findAll(it).count() }
        assertTrue(
            "the aspectRatio scan found $calls call sites; if that ever drops to 0 this test " +
                "passes over nothing",
            calls >= 3,
        )
    }

    // ── 2. each geometry number has exactly one owner ────────────────────────
    @Test
    fun eachShapeIsWrittenOnceInWholeSources() {
        val sources = sourcesByPath()

        fun pathsMatching(needle: Regex, excludeGeometry: Boolean = true): List<String> =
            sources.filter { (path, body) ->
                (!excludeGeometry || path != geometryPath) && needle.containsMatchIn(body)
            }.keys.sorted()

        assertEquals(
            "the poster ratio must be written once, in CardGeometry",
            emptyList<String>(),
            pathsMatching(Regex("""0\.68f""")),
        )
        assertEquals(
            "rail tile width must come from CardGeometry.RAIL_CARD_WIDTH_DP, not a per-screen dp",
            emptyList<String>(),
            pathsMatching(Regex("""width\(\s*132\s*\.dp""")),
        )
        assertEquals(
            "a rail placeholder height must be derived, not pinned — a pinned 190dp skeleton box " +
                "is a cell that jumps when the real card lands",
            emptyList<String>(),
            pathsMatching(Regex("""height\(\s*19[0-9]\s*\.dp""")),
        )
        assertTrue(
            "CardGeometry must still own the rail width, or the dp scan above is vacuous",
            Regex("""const val RAIL_CARD_WIDTH_DP: Int = 132""").containsMatchIn(sources.getValue(geometryPath)),
        )
    }

    // ── 3. the placeholder is the card's box, not an impression of it ─────────
    @Test
    fun railPlaceholderIsBuiltFromTheSameTwoNumbersAsTheCard() {
        val body = railPlaceholderBody()
        assertTrue(
            "PosterRailSkeleton must size its cell from CardGeometry.RAIL_CARD_WIDTH_DP — the " +
                "width MediaRail gives the real tiles",
            Regex("""RAIL_CARD_WIDTH_DP""").containsMatchIn(body),
        )
        assertTrue(
            "PosterRailSkeleton must shape its image box from CardGeometry.POSTER_ASPECT, not a " +
                "pinned height — a 190dp placeholder box above a 194dp card is the row that jumps",
            Regex("""aspectRatio\(\s*CardGeometry\.POSTER_ASPECT\s*\)""").containsMatchIn(body),
        )
    }

    /**
     * The `PosterRailSkeleton` source, comments already stripped: from its signature to the next
     * `@Composable`, which is where the next component starts.
     */
    private fun railPlaceholderBody(): String {
        val commonUi = sourcesByPath().getValue(commonUiPath)
        return Regex("""fun PosterRailSkeleton\([\s\S]*?(?=\n@Composable|\z)""")
            .find(commonUi)
            ?.value
            ?: error("PosterRailSkeleton is gone from $commonUiPath: a rail that fills in with no " +
                "stand-in above it is idea #84 un-implemented")
    }

    // ── 4. the artwork classes stay distinct ─────────────────────────────────
    @Test
    fun artworkClassesStayDistinctAndSane() {
        assertTrue("a poster is a tall box", CardGeometry.POSTER_ASPECT < 1f)
        assertTrue("backdrops and episode stills are the wide class", CardGeometry.WIDE_ART_ASPECT > 1f)
        assertTrue(
            "the season band is wider than a 16:9 still, or it is one class wearing two names",
            CardGeometry.SEASON_ART_ASPECT > CardGeometry.WIDE_ART_ASPECT,
        )
        assertEquals("16:9 within a hundredth", 1.78, CardGeometry.WIDE_ART_ASPECT.toDouble(), 0.01)
    }

    private fun String.withoutComments(): String =
        Regex("""/\*[\s\S]*?\*/""").replace(Regex("""//[^\n]*""").replace(this, ""), "")
}
