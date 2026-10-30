package com.raddstream.app.tooling

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * An intent-filter is a promise made in XML about behaviour written in Kotlin, and there is no
 * compiler between them. Widen the filter and the app starts receiving addresses the rule refuses
 * — a file opened from a file manager that does nothing, which looks like a broken player. Narrow
 * the rule and the filter keeps advertising a file type the app quietly declines. Either way the
 * mistake is invisible until a viewer tries it.
 *
 * So the two files are compared here, in both directions, by a scan that is itself shown to tell
 * a matched pair from a mismatch.
 */
class LocalVideoIntentCensusTest {

    private val manifestText: String get() = File(MANIFEST_PATH).readText()
    private val ruleText: String get() = File(RULE_PATH).readText()

    /**
     * Every `<data>` element that carries both a scheme and a MIME type. The element is read as a
     * whole and the attributes picked out of it, because XML attribute order is not a thing anyone
     * is holding still — a scan that requires scheme-before-type would silently drop an entry
     * someone reformatted, and a dropped entry is this guard going green over nothing.
     */
    private fun manifestVideoEntries(text: String): List<Pair<String, String>> =
        Regex("""<data\b[^>]*""")
            .findAll(text)
            .map { it.value }
            .mapNotNull { element ->
                val scheme = Regex("""android:scheme="([^"]+)"""").find(element)?.groupValues?.get(1)
                val mime = Regex("""android:mimeType="([^"]+)"""").find(element)?.groupValues?.get(1)
                if (scheme != null && mime != null) scheme to mime else null
            }
            .toList()

    /** The schemes the pure rule accepts, read out of its own set. */
    private fun ruleSchemes(text: String): List<String> =
        Regex("""localSchemes\s*=\s*setOf\(([^)]*)\)""")
            .find(text)
            ?.groupValues
            ?.get(1)
            // Four quotes on each side: a raw string closes at the LAST three of a run, so the
            // content here is the pattern `"([^"]+)"` and a three-quote close silently eats the
            // closing quote out of it. Measured in CI — the broken form matched `content`, `, `,
            // `file` and this guard's own positive control is what caught it.
            ?.let { body -> Regex(""""([^"]+)"""").findAll(body).map { it.groupValues[1] }.toList() }
            ?: emptyList()

    @Test
    fun `the advertised filter and the accepted schemes are the same list`() {
        val declared = manifestVideoEntries(manifestText)
        assertTrue(
            "the scan must be reading a filter that exists — an empty list here is a green run " +
                "over nothing",
            declared.isNotEmpty(),
        )
        val accepted = ruleSchemes(ruleText)
        assertTrue("the rule must accept something, or nothing plays", accepted.isNotEmpty())

        val advertisedButRefused = declared.map { it.first }.distinct().filterNot { it in accepted }
        assertTrue(
            "the manifest invites schemes the rule refuses, so a file opened from outside the " +
                "app arrives and does nothing: $advertisedButRefused",
            advertisedButRefused.isEmpty(),
        )
        val acceptedButNotAdvertised = accepted.filterNot { scheme -> declared.any { it.first == scheme } }
        assertTrue(
            "the rule is ready for schemes no filter advertises, which is dead code waiting to " +
                "be mistaken for a feature: $acceptedButNotAdvertised",
            acceptedButNotAdvertised.isEmpty(),
        )
        assertEquals(
            "every advertised entry is a video wildcard — the containers are decided by the " +
                "reader that sniffs the bytes, not by a list this app cannot keep current",
            declared.map { it.first },
            declared.filter { it.second.startsWith("video/") }.map { it.first },
        )
    }

    /**
     * The one promise that must not be made: a remote address arriving through the local-file
     * door. Both halves are checked, because either alone is enough to open it — the XML if the
     * rule were permissive, the rule if the filter were widened later.
     */
    @Test
    fun `no network scheme is offered to the local player by either half`() {
        val remote = manifestVideoEntries(manifestText).map { it.first }.filter { it in remoteSchemes }
        assertTrue("the local filter must not advertise a network scheme: $remote", remote.isEmpty())
        val allowed = ruleSchemes(ruleText)
        assertTrue("and the rule must not accept one either: $allowed", allowed.none { it in remoteSchemes })
    }

    /**
     * A filter is only a promise that something will be played. The destination it lands on has
     * to exist, in the route form the rule builds.
     */
    @Test
    fun `the route the local open navigates to is a route the graph registers`() {
        val graph = File(GRAPH_PATH).readText()
        assertTrue(
            "the graph must register the finished-download route the rule composes, or the " +
                "navigate call throws at the first file opened",
            Regex("""route = Screen\.PlayerLocal\.route""").containsMatchIn(graph),
        )
        assertTrue(
            "and the rule must compose exactly that route rather than a string that merely looks " +
                "like it",
            Regex("""Screen\.PlayerLocal\.createRoute\(uri, title\)""").containsMatchIn(ruleText),
        )
        assertTrue(
            "no hand-built route prefix in the rule either: a second composer is a second answer " +
                "to how the arguments are escaped",
            !Regex(""""player_local/""").containsMatchIn(ruleText),
        )
    }

    /** The guard needs a guard: every scan above must be shown to tell these shapes apart. */
    @Test
    fun `the scans separate a matched pair from a filter that promises more than the rule allows`() {
        val good = "<data android:scheme=\"content\" android:mimeType=\"video/star\" />\n" +
            "<data\n    android:scheme=\"file\"\n    android:mimeType=\"video/star\" />"
        val reordered = "<data android:mimeType=\"video/star\" android:scheme=\"file\" />"
        val widened = "<data android:scheme=\"https\" android:mimeType=\"video/star\" />\n" +
            "<data android:scheme=\"content\" android:mimeType=\"video/star\" />"
        val noMime = "<data android:scheme=\"radd\" />"
        val rule = "private val localSchemes = setOf(\"content\", \"file\")"

        assertEquals(listOf("content", "file"), manifestVideoEntries(good).map { it.first })
        assertEquals(listOf("file"), manifestVideoEntries(reordered).map { it.first })
        assertEquals(listOf("content", "file"), ruleSchemes(rule))
        assertEquals(
            "a scheme the rule does not name is found as a mismatch, not skipped",
            listOf("https"),
            manifestVideoEntries(widened).map { it.first }.distinct().filterNot { it in ruleSchemes(rule) },
        )
        assertTrue(
            "and a network scheme is caught by the promise test even inside a tidy pair",
            manifestVideoEntries(widened).map { it.first }.any { it in remoteSchemes },
        )
        assertTrue("an entry with no MIME type is not an offer to play video", manifestVideoEntries(noMime).isEmpty())
        assertTrue("an empty rule is not silently a pass", ruleSchemes("private val localSchemes = setOf()").isEmpty())
    }

    private companion object {
        const val MANIFEST_PATH = "src/main/AndroidManifest.xml"
        const val RULE_PATH = "src/main/kotlin/com/raddstream/app/ui/navigation/LocalVideoOpen.kt"
        const val GRAPH_PATH = "src/main/kotlin/com/raddstream/app/ui/navigation/NavGraph.kt"
        val remoteSchemes = setOf("http", "https", "ftp")
    }
}
