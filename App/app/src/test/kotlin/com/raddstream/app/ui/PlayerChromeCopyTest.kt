package com.raddstream.app.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * Every word the player paints now lives in `res/values/strings.xml` as a `player_*` entry, and
 * `PlayerScreen.kt` paints it from there. That is the right home for functional chrome vocabulary:
 * a `values-*` folder can carry it without touching code, and there is exactly one copy of the
 * English. `Brand.copy` stays the home for brand VOICE — the product's name, the share template,
 * the update and offline notices — which is a different question from what a button is called.
 *
 * Moving 118 strings by hand is exactly the kind of edit that silently loses a label or mis-numbers
 * a placeholder, and none of it fails a compile. These are the rules that would catch that, in the
 * `BrandDriftTest` pattern: a plain JVM scan of the two files, no device, no Robolectric.
 */
class PlayerChromeCopyTest {

    private val repoRoot: File by lazy {
        var dir: File? = File("").absoluteFile
        while (dir != null) {
            if (File(dir, "brand.properties").isFile) return@lazy dir
            dir = dir.parentFile
        }
        error("brand.properties not found above ${File("").absolutePath}")
    }

    private val mainSrc: File get() = File(repoRoot, "App/app/src/main")
    private val playerScreen: File get() = File(
        mainSrc,
        "kotlin/com/raddstream/app/ui/screens/PlayerScreen.kt",
    )

    private val source: String by lazy {
        assertTrue("PlayerScreen.kt is missing at ${playerScreen.path}", playerScreen.isFile)
        playerScreen.readText()
    }
    private val xml: String by lazy { File(mainSrc, "res/values/strings.xml").readText() }

    // ── the two files, read as the pairs they actually are ────────────────────

    private data class Entry(val name: String, val raw: String, val value: String)

    private val entryPattern = Regex("""<string name="([^"]+)">(.*)</string>""")

    private val entries: List<Entry> by lazy {
        xml.lines().mapNotNull { line ->
            val match = entryPattern.matchEntire(line.trim()) ?: return@mapNotNull null
            val raw = match.groupValues[2]
            Entry(match.groupValues[1], raw, decode(raw))
        }
    }

    private val chromeEntries: List<Entry> get() = entries.filter { it.name.startsWith("player_") }

    /** Unwraps aapt's quoting convention and turns the five XML entities back into text. */
    private fun decode(raw: String): String {
        var value = raw
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", "\"")
            .replace("&apos;", "'")
            .replace("\\'", "'")
            .replace("&amp;", "&") // last, so "&amp;lt;" cannot double-decode
        if (value.length > 1 && value.startsWith("\"") && value.endsWith("\"")) {
            value = value.substring(1, value.length - 1)
        }
        return value
    }

    /** Literals only, comments removed: a KDoc may quote the UI all it likes. */
    private fun codeOf(text: String): String {
        val out = StringBuilder()
        var i = 0
        var inLine = false
        var inBlock = false
        var inString = false
        while (i < text.length) {
            val c = text[i]
            val next = if (i + 1 < text.length) text[i + 1] else ' '
            when {
                inLine -> {
                    if (c == '\n') { inLine = false; out.append(c) }
                }
                inBlock -> if (c == '*' && next == '/') { inBlock = false; i++ }
                inString -> {
                    out.append(c)
                    if (c == '\\') { out.append(next); i++ } else if (c == '"') inString = false
                }
                c == '/' && next == '/' -> inLine = true
                c == '/' && next == '*' -> inBlock = true
                else -> {
                    out.append(c)
                    if (c == '"') inString = true
                }
            }
            i++
        }
        return out.toString()
    }

    private val literalPattern = Regex(""""(?:[^"\\]|\\.)*"""")

    /**
     * Every `R.string.player_*` reference and how many format arguments its call site passes.
     * The id sits inside the call's own parentheses, so the enclosing call is found by walking
     * back to that `(` and forward to the `)` that closes it, counting only top-level commas.
     */
    private data class CallSite(val name: String, val args: Int, val line: Int)

    private fun callSites(): List<CallSite> {
        val found = mutableListOf<CallSite>()
        Regex("""R\.string\.(player_[A-Za-z0-9_]+)""").findAll(source).forEach { match ->
            val at = match.range.first
            val open = source.lastIndexOf('(', at)
            assertTrue("a player_ string reference is not inside a call", open >= 0)
            var depth = 0
            var close = -1
            var index = open
            var inString = false
            while (index < source.length) {
                val c = source[index]
                if (inString) {
                    if (c == '\\') index++ else if (c == '"') inString = false
                } else when (c) {
                    '"' -> inString = true
                    '(', '[', '{' -> depth++
                    ')', ']', '}' -> {
                        depth--
                        if (depth == 0) { close = index; break }
                    }
                }
                index++
            }
            assertTrue("unbalanced parentheses around a player_ string call", close > open)
            val inner = source.substring(open + 1, close).trim().trimEnd(',').trim()
            val commas = topLevelCommas(inner)
            found += CallSite(match.groupValues[1], commas, source.substring(0, at).count { it == '\n' } + 1)
        }
        return found
    }

    private fun topLevelCommas(inner: String): Int {
        var depth = 0
        var count = 0
        var inString = false
        var i = 0
        while (i < inner.length) {
            val c = inner[i]
            if (inString) {
                if (c == '\\') i++ else if (c == '"') inString = false
            } else when (c) {
                '"' -> inString = true
                '(', '[', '{' -> depth++
                ')', ']', '}' -> depth--
                ',' -> if (depth == 0) count++
            }
            i++
        }
        return count
    }

    private fun highestPlaceholder(value: String): Int {
        val stripped = value.replace("%%", "")
        return Regex("""%(\d+)\$[a-zA-Z]""").findAll(stripped)
            .map { it.groupValues[1].toInt() }
            .maxOrNull() ?: 0
    }

    // ── 1. the two halves agree ───────────────────────────────────────────────

    @Test
    fun `every player string is painted and nothing paints a string that does not exist`() {
        val defined = chromeEntries.map { it.name }.toSet()
        val used = callSites().map { it.name }.toSet()
        assertTrue("the player's chrome vocabulary must be the one being tested", defined.size >= 100)
        assertEquals(
            "a player_* string nobody paints is a label waiting to be mistaken for live UI",
            emptySet<String>(), defined - used,
        )
        assertEquals(
            "PlayerScreen asks resources do not define — the screen would paint nothing",
            emptySet<String>(), used - defined,
        )
    }

    @Test
    fun `no two player strings say the same thing`() {
        val shared = chromeEntries.groupBy { it.value }.filterValues { it.size > 1 }
        assertEquals(
            "two names for one phrase means one of them will drift: " +
                shared.entries.joinToString { (value, list) -> "'$value' <- ${list.joinToString { it.name }}" },
            emptyList<String>(), shared.keys.toList(),
        )
    }

    // ── 2. the placeholder contract ───────────────────────────────────────────

    @Test
    fun `every placeholder is positional`() {
        val bare = chromeEntries.filter {
            val stripped = it.value.replace("%%", "")
            Regex("""%[a-zA-Z]""").containsMatchIn(stripped) ||
                Regex("""%""").findAll(stripped).count() != Regex("""%\d+\$[a-zA-Z]""").findAll(stripped).count()
        }.map { it.name }
        assertEquals(
            "a bare %s or %d cannot be reordered by a translator — every placeholder in a " +
                "player_* string must be numbered (%1${'$'}s, %2${'$'}d)",
            emptyList<String>(), bare,
        )
    }

    @Test
    fun `every call site passes exactly the arguments its string asks for`() {
        val byName = chromeEntries.associate { it.name to it.value }
        val wrong = callSites().filter { site -> site.args != highestPlaceholder(byName.getValue(site.name)) }
            .map { "${it.name} on line ${it.line}: passes ${it.args}, the string asks ${highestPlaceholder(byName.getValue(it.name))}" }
        assertEquals(
            "a format string fed the wrong number of arguments throws at runtime, on a screen " +
                "nobody can look at",
            emptyList<String>(), wrong,
        )
    }

    @Test
    fun `a name is always called with the same number of arguments`() {
        val split = callSites().groupBy { it.name }
            .filterValues { sites -> sites.map { it.args }.distinct().size > 1 }
            .map { (name, sites) -> "$name: " + sites.joinToString { "line ${it.line} -> ${it.args} args" } }
        assertEquals(
            "one string, two shapes means one of them is wrong",
            emptyList<String>(), split,
        )
    }

    @Test
    fun `a value that needs its spaces keeps them quoted`() {
        // aapt collapses runs of whitespace unless the whole value is wrapped in double quotes.
        val unquoted = chromeEntries.filter {
            (it.value.contains("  ") || it.value.first() == ' ' || it.value.last() == ' ') &&
                !(it.raw.startsWith("\"") && it.raw.endsWith("\""))
        }.map { it.name }
        assertEquals(
            "these values would lose a space at compile time — wrap them in double quotes",
            emptyList<String>(), unquoted,
        )
    }

    @Test
    fun `the resource file stays well formed`() {
        val stray = Regex("""&(?!amp;|lt;|gt;|quot;|apos;|#)""").findAll(xml).count()
        assertEquals("a raw '&' breaks the resource compiler", 0, stray)
        assertTrue("every entry must close on its own line", !Regex("""<string name="[^"]*"$""").containsMatchIn(xml))
    }

    // ── 3. the ratchet: the prose must not creep back into the screen ─────────

    @Test
    fun `the player holds no prose of its own`() {
        val prose = literalPattern.findAll(codeOf(source))
            .map { it.value }
            .filter { literal ->
                val body = literal.trim('"')
                body.any { it.isLetter() } && body.any { it.isWhitespace() }
            }
            .sorted()
            .distinct()
            .toList()
        assertEquals(
            "user-visible words belong in res/values/strings.xml (positional placeholders) — " +
                "one copy of the English, and a locale folder can reach them",
            emptyList<String>(), prose,
        )
    }

    @Test
    fun `the chrome vocabulary is resources and the brand voice stays Brand copy`() {
        assertFalse(
            "player chrome is functional vocabulary, not brand copy — a re-skin must not rename " +
                "'Retry' or 'Sleep timer'. Brand.copy is for what the product calls ITSELF.",
            source.contains("Brand.copy("),
        )
        assertTrue("the player still speaks the brand's name through Brand", source.contains("Brand.name"))
    }

    @Test
    fun `the helper that names the subtitles control still owns no word`() {
        val screen = codeOf(source)
        val start = screen.indexOf("internal fun subtitleStatusLabel(")
        assertTrue("subtitleStatusLabel must stay a helper the screen feeds words to", start >= 0)
        val body = screen.substring(start).lines().take(8).joinToString("\n")
        assertTrue(
            "subtitleStatusLabel answers with the off-word it is GIVEN, so the word can come from " +
                "resources and the rule stays testable on the JVM",
            body.contains("?: offWord"),
        )
    }
}
