package com.raddstream.app.brand

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.io.FileInputStream
import java.util.Properties

/**
 * BrandDriftTest — guards the promise that /brand.properties is the ONE brand file.
 *
 * Plain JUnit4 on the JVM: no Robolectric, no Android runtime, no generated
 * classes. It reads the repo from disk (walking up from the Gradle working
 * directory until it finds brand.properties) and inspects the sources, so it is
 * runnable anywhere a JDK + junit4 exist.
 *
 * Only STRING LITERALS are searched — comments legitimately name the product.
 *
 * It fails when:
 *  1. a Kotlin source hardcodes a brand display name outside the brand files;
 *  2. a Kotlin source writes a raw Color(0x…) outside ui/theme/Color.kt;
 *  3. a Kotlin source hardcodes the deep-link scheme instead of Brand.deepLinkUri;
 *  4. a theme token in Color.kt references a BuildConfig field no brand key
 *     produces, or a brand ramp key that is not a valid hex;
 *  5. res/values/colors.xml re-declares a generated colour, or resources.colors.*
 *     invents paint that is not in the ramps;
 *  6. AndroidManifest.xml stops using the generated label / ${brandScheme};
 *  7. a [copy] string still names a brand other than identity.name (a re-skin
 *     must not silently leave the old name in prose);
 *  8. the documented "pending migration" lists grow — or shrink without being
 *     updated. They are a ratchet, not a parking lot.
 */
class BrandDriftTest {

    // ── Repo discovery ───────────────────────────────────────────────────────
    private val repoRoot: File by lazy {
        var dir: File? = File("").absoluteFile
        while (dir != null) {
            if (File(dir, "brand.properties").isFile) return@lazy dir
            dir = dir.parentFile
        }
        error("brand.properties not found above ${File("").absolutePath}")
    }

    private val appDir: File get() = File(repoRoot, "App")
    private val mainSrc: File get() = File(appDir, "app/src/main")
    private val brandProps: Properties by lazy {
        Properties().apply { FileInputStream(File(repoRoot, "brand.properties")).use { load(it) } }
    }

    private fun brandKeys(): List<String> =
        brandProps.stringPropertyNames().filter { !it.startsWith("[") }.sorted()

    private fun brandValue(key: String): String = (brandProps.getProperty(key) ?: "").trim()

    private fun kotlinSources(): List<File> =
        mainSrc.walkTopDown().filter { it.isFile && it.extension == "kt" }.toList()

    /** Repo-relative, '/'-separated path (kept dependency-free: no java.nio Path API). */
    private fun File.relativeToRoot(): String {
        val prefix = repoRoot.absolutePath.replace(File.separatorChar, '/') + "/"
        val path = absolutePath.replace(File.separatorChar, '/')
        return if (path.startsWith(prefix)) path.removePrefix(prefix) else path
    }

    /** Quoted string literals only (comments may name the product freely). */
    private val literalPattern = Regex(""""(?:[^"\\\n]|\\.)*"""")
    private fun File.stringLiterals(): List<String> = literalPattern.findAll(readText()).map { it.value }.toList()

    // ── Allowlists (explicit and small) ──────────────────────────────────────

    /** Files that legitimately define or re-state the brand. */
    private val brandOwners = setOf(
        "App/app/src/main/kotlin/com/raddstream/app/brand/Brand.kt",
        "App/app/src/main/kotlin/com/raddstream/app/ui/theme/RaddMark.kt",
    )

    /**
     * Files still hardcoding the brand name, owned by the player/detail/cache
     * workstream. The fix for each is one line: read `Brand.name` or
     * `Brand.copy("offline_notice", …)`. This set must only ever shrink.
     */
    private val pendingBrandNameMigration = setOf(
        "App/app/src/main/kotlin/com/raddstream/app/player/CacheAffordance.kt",
        "App/app/src/main/kotlin/com/raddstream/app/player/PlaybackService.kt",
        "App/app/src/main/kotlin/com/raddstream/app/ui/screens/DetailScreen.kt",
        "App/app/src/main/kotlin/com/raddstream/app/ui/screens/DownloadsScreen.kt",
        "App/app/src/main/kotlin/com/raddstream/app/ui/screens/PlayerScreen.kt",
        "App/app/src/main/kotlin/com/raddstream/app/ui/screens/SetupScreen.kt",
        "App/app/src/main/kotlin/com/raddstream/app/viewmodel/PlayerViewModel.kt",
    )

    /** Files that legitimately contain raw paints: the brand palette itself. */
    private val colorOwners = setOf(
        "App/app/src/main/kotlin/com/raddstream/app/ui/theme/Color.kt",
    )

    /** ~29 raw paints (incl. AccentOrange 0xFFFF8552) awaiting theme-token migration. */
    private val pendingColorMigration = setOf(
        "App/app/src/main/kotlin/com/raddstream/app/ui/screens/PlayerScreen.kt",
    )

    private val deepLinkOwners = brandOwners

    private val pendingDeepLinkMigration = setOf(
        "App/app/src/main/kotlin/com/raddstream/app/ui/navigation/NavGraph.kt",
    )

    private fun assertRatchet(label: String, offenders: List<String>, owners: Set<String>, pending: Set<String>) {
        val unexpected = offenders.filter { it !in owners && it !in pending }
        assertEquals("$label: new hardcoded brand data — read it from Brand / theme tokens.", emptyList<String>(), unexpected)
        assertEquals(
            "$label: the pending-migration list is a ratchet. Either a file was migrated " +
                "(remove it from the list in this test) or a new violation appeared.",
            pending.sorted(),
            offenders.filter { it !in owners }.sorted(),
        )
    }

    // ── 1. brand name ────────────────────────────────────────────────────────
    @Test
    fun brandNameIsNeverHardcodedOutsideTheBrandFiles() {
        val needles = listOf(
            brandValue("identity.name"),
            brandValue("identity.name.short"),
            brandValue("server.project.name"),
            "Radd Stream", "RADD Stream", "radd-stream",
        ).filter { it.isNotBlank() }.map { it.lowercase() }.distinct()

        val offenders = kotlinSources().filter { file ->
            file.stringLiterals().any { literal -> needles.any { literal.lowercase().contains(it) } }
        }.map { it.relativeToRoot() }.sorted()

        assertRatchet("brand name", offenders, brandOwners, pendingBrandNameMigration)
    }

    // ── 2. raw paints ────────────────────────────────────────────────────────
    @Test
    fun rawColorLiteralsStayInsideTheBrandPalette() {
        val offenders = kotlinSources()
            .filter { Regex("""Color\(\s*0x""").containsMatchIn(it.readText()) }
            .map { it.relativeToRoot() }
            .sorted()

        assertRatchet("raw Color(0x…) paint", offenders, colorOwners, pendingColorMigration)
        assertTrue("Color.kt must read brand hexes from BuildConfig", brandColorRefs().isNotEmpty())
    }

    // ── 3. deep-link scheme ──────────────────────────────────────────────────
    @Test
    fun deepLinkSchemeIsNeverHardcoded() {
        val scheme = brandValue("deeplink.scheme")
        val needle = "$scheme://"
        val offenders = kotlinSources()
            .filter { file -> file.stringLiterals().any { it.contains(needle) } }
            .map { it.relativeToRoot() }
            .sorted()
        assertRatchet("deep-link scheme", offenders, deepLinkOwners, pendingDeepLinkMigration)
    }

    // ── 4. theme tokens resolve from the brand ramps ─────────────────────────
    @Test
    fun themeTokensResolveFromBrandRamps() {
        val keys = brandKeys()
        val generatedFields = keys.map { "BRAND_" + it.uppercase().replace('.', '_') }.toSet()
        val refs = brandColorRefs()
        val unresolved = refs.filter { it !in generatedFields }.distinct()
        assertEquals("Color.kt references BuildConfig fields no brand key produces", emptyList<String>(), unresolved)

        val fieldToKey = keys.associateBy { "BRAND_" + it.uppercase().replace('.', '_') }
        val hexPattern = Regex("^#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$")
        val invalid = refs.mapNotNull { fieldToKey[it] }
            .filter { !hexPattern.matches(brandValue(it)) }
            .distinct()
        assertEquals("referenced brand ramps must be #RRGGBB or #AARRGGBB", emptyList<String>(), invalid)

        // The four documented roles must exist in both ramps.
        listOf("colors.dark", "colors.light").forEach { section ->
            val roles = keys.filter { it.startsWith("$section.") }.map { it.removePrefix("$section.") }.toSet()
            listOf("background", "surface", "primary", "text").forEach { role ->
                assertTrue("$section.$role is missing from brand.properties", roles.contains(role))
            }
            // and every role actually referenced by Color.kt belongs to that section
            refs.mapNotNull { fieldToKey[it] }
                .filter { it.startsWith("$section.") }
                .forEach { assertTrue("$it is not a ramp role", roles.contains(it.removePrefix("$section."))) }
        }
        assertTrue(
            "light and dark primary must differ, or one scheme is unreadable",
            brandValue("colors.light.primary") != brandValue("colors.dark.primary"),
        )
        assertTrue(
            "dark text must differ from dark background",
            brandValue("colors.dark.text") != brandValue("colors.dark.background"),
        )
    }

    private fun brandColorRefs(): List<String> =
        Regex("""brandColor\(BuildConfig\.(\w+)\)""")
            .findAll(File(mainSrc, "kotlin/com/raddstream/app/ui/theme/Color.kt").readText())
            .map { it.groupValues[1] }
            .toList()

    // ── 5. resource-side colours ─────────────────────────────────────────────
    @Test
    fun resourceColorsAreGeneratedAndInventNothingNew() {
        val rampValues = brandKeys().filter { it.startsWith("colors.") }
            .map { brandValue(it).uppercase() }.toSet()

        val resourceKeys = brandKeys().filter { it.startsWith("resources.colors.") }
        assertTrue("brand.properties declares no resources.colors.* keys", resourceKeys.isNotEmpty())
        resourceKeys.forEach { key ->
            val name = key.removePrefix("resources.colors.")
            assertTrue("'$name' is not a valid Android resource name", Regex("^[a-z][a-z0-9_]*$").matches(name))
            val hex = brandValue(key).uppercase()
            assertTrue("$key='$hex' must reuse a [colors.*] ramp value", rampValues.contains(hex))
        }

        val declared = Regex("""<color\s+name="([^"]+)"""")
            .findAll(File(mainSrc, "res/values/colors.xml").readText())
            .map { it.groupValues[1] }.toList()
        assertEquals(
            "res/values/colors.xml duplicates generated brand colours — use resources.colors.* " +
                "in brand.properties instead (same names = duplicate resource error).",
            emptyList<String>(), declared,
        )
    }

    // ── 6. manifest is brand-driven ─────────────────────────────────────────
    @Test
    fun manifestUsesGeneratedLabelAndScheme() {
        val manifest = File(mainSrc, "AndroidManifest.xml").readText()
        assertTrue("android:label must be @string/brand_app_name (generated)", manifest.contains("@string/brand_app_name"))
        val placeholder = "$" + "{brandScheme}"
        val schemes = Regex("""android:scheme="([^"]*)"""").findAll(manifest).map { it.groupValues[1] }.toList()
        assertEquals(
            "the deep-link <data android:scheme> must be the generated placeholder; the value " +
                "itself comes from deeplink.scheme in brand.properties",
            listOf(placeholder), schemes,
        )
    }

    // ── 7. copy strings follow the name ─────────────────────────────────────
    @Test
    fun copyStringsMatchTheBrandedName() {
        val name = brandValue("identity.name")
        val legacyNames = listOf("RADD Stream", "Radd Stream", "radd-stream", "RADD STREAM").distinct()
        brandKeys().filter { it.startsWith("copy.") }.forEach { key ->
            val value = brandValue(key)
            val stale = legacyNames.filter {
                it.contains(name, ignoreCase = true).not() &&
                    value.contains(it, ignoreCase = true) &&
                    value.contains(name, ignoreCase = true).not()
            }
            assertEquals("$key still names $stale after re-branding to '$name'", emptyList<String>(), stale)
        }
        assertTrue("copy.share_template must keep the {title} token", brandValue("copy.share_template").contains("{title}"))
        assertTrue("copy strings must not be empty", brandKeys().count { it.startsWith("copy.") } >= 5)
    }

    // ── 8. shared reader contract ───────────────────────────────────────────
    @Test
    fun brandFileKeysAreFullyQualifiedAndUnique() {
        val keys = brandKeys()
        assertEquals("duplicate brand keys", keys.size, keys.distinct().size)
        assertEquals(
            "every brand key must carry its section prefix (dots)",
            emptyList<String>(), keys.filter { !it.contains('.') },
        )
        assertEquals(
            "brand keys must contain no '%' or spaces (two parsers share this file)",
            emptyList<String>(), keys.filter { it.contains('%') || it.contains(' ') },
        )
        listOf(
            "identity.name", "identity.application.id", "identity.namespace", "identity.version.name",
            "identity.version.code", "deeplink.scheme", "network.user_agent.product",
            "server.project.name", "colors.dark.primary", "colors.light.primary",
        ).forEach { assertTrue("$it must be set", brandValue(it).isNotBlank()) }
        assertTrue("identity.version.code must be numeric", brandValue("identity.version.code").toLongOrNull() != null)
        assertTrue(
            "features.adult_filter_enforced is policy and must stay true",
            brandValue("features.adult_filter_enforced") == "true",
        )
    }

    /** The generated asset (present once :app:generateBrandAssets ran) must be complete. */
    @Test
    fun generatedBrandJsonCoversEveryKey() {
        val json = File(appDir, "app/build/generated/assets/brand/brand.json")
        if (!json.isFile) return // a clean tree may run unit tests before the asset task
        val body = json.readText()
        assertEquals(
            "brand.json is missing brand keys",
            emptyList<String>(), brandKeys().filter { !body.contains("\"$it\":") },
        )
        assertTrue(
            "brand.json must be generated under build/, never hand-maintained in src/main/assets",
            !File(mainSrc, "assets/brand.json").exists(),
        )
    }
}
