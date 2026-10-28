package com.raddstream.app.tooling

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * Dead code is not neutral: every unreferenced declaration is a place a future agent can edit and
 * believe they changed behaviour, a name a re-brand has to reason about, and a rule that looks
 * owned by the app when nothing calls it. `res/values/strings.xml` proved it here — eleven legacy
 * strings sat in the file for months while every screen painted hardcoded prose, so the resources
 * claimed a vocabulary the app never used.
 *
 * These checks are deliberately narrow. They do NOT try to find every unreferenced Kotlin symbol,
 * because the honest answer for many of those is "framework, Gson, Hilt or a documented seam" —
 * reflection and generated code are invisible to a text scan, and a guard that cries wolf gets
 * ignored. What a text scan can answer without guessing: is a declared resource reachable, and
 * does production code expose an API that exists only for a test.
 */
class DeadCodeGuardTest {

    private val mainDir: File get() = File("src/main")
    private val resDir: File get() = File(mainDir, "res")

    private fun ktTexts(): List<String> =
        File(mainDir, "kotlin").walkTopDown()
            .filter { it.isFile && it.extension == "kt" }
            .map { it.readText() }
            .toList()

    /** Every declaration the app itself writes in a values folder, as kind + name + file. */
    private fun declaredResources(): List<Resource> {
        val pattern = Regex("""<(string|color|dimen|integer|bool)\s+name="([^"]+)"""")
        return resDir.walkTopDown()
            .filter { it.isFile && it.extension == "xml" && it.parentFile.name.startsWith("values") }
            .flatMap { file ->
                pattern.findAll(file.readText())
                    .map { Resource(it.groupValues[1], it.groupValues[2], file) }
            }
            .toList()
    }

    private data class Resource(val kind: String, val name: String, val declaredIn: File)

    /** A name is live when Kotlin, another resource, or the manifest can actually reach it. */
    private fun isLive(kind: String, name: String, kotlin: List<String>, xmls: List<Pair<File, String>>): Boolean {
        val boundary = "(?![A-Za-z0-9_])" // @string/play must not match inside @string/player_x
        return kotlin.any { Regex("""\bR\.$kind\.$name\b""").containsMatchIn(it) } ||
            xmls.any { (_, text) -> Regex("""@$kind/$name$boundary""").containsMatchIn(text) }
    }

    @Test
    fun `every declared resource value is reachable from code or another resource`() {
        val kotlin = ktTexts()
        val xmls = resDir.walkTopDown().filter { it.isFile && it.extension == "xml" }
            .map { it to it.readText() }
            .toList()
        val manifest = File(mainDir, "AndroidManifest.xml").readText()

        val declared = declaredResources()
        assertTrue("the guard must actually be reading something", declared.isNotEmpty())

        val orphans = declared.filter { (kind, name, _) ->
            !isLive(kind, name, kotlin, xmls) && !Regex("""@$kind/$name(?![A-Za-z0-9_])""").containsMatchIn(manifest)
        }.map { (kind, name, file) -> "$kind/$name (${file.path})" }

        assertEquals(
            "an unreferenced resource is a vocabulary the app does not have — delete it, or wire " +
                "the screen that was supposed to paint it",
            emptyList<String>(), orphans,
        )
    }

    @Test
    fun `production code exposes no API that exists only for a test`() {
        val shims = File(mainDir, "kotlin").walkTopDown()
            .filter { it.isFile && it.extension == "kt" }
            .flatMap { file ->
                Regex("""\b(?:fun|val)\s+([A-Za-z0-9_]*ForTest)\b""").findAll(file.readText())
                    .map { "${file.path}:${it.groupValues[1]}" }
            }
            .toList()

        assertEquals(
            "a helper named for a test is a second owner of a rule the real code already owns — " +
                "call the real one from the test and delete the shim",
            emptyList<String>(), shims,
        )
    }

    /**
     * The guard needs a guard: both scans are fed shapes they must tell apart, or a green run
     * would only prove the scanner looks at nothing.
     */
    @Test
    fun `the reachability rule itself separates a live name from an orphan`() {
        val kotlin = listOf("""val x = stringResource(R.string.live_label)""")
        val xmls = listOf(
            File("res/values/themes.xml") to
                """<style name="T"><item name="windowBackground">@color/plate</item></style>""",
        )
        assertTrue("a name only Kotlin reaches is live", isLive("string", "live_label", kotlin, xmls))
        assertTrue("a name another resource reaches is live", isLive("color", "plate", emptyList(), xmls))
        assertTrue("a name nothing reaches is an orphan", !isLive("color", "plate", kotlin, emptyList()))
        assertTrue("a shorter name is not matched inside a longer one",
            !isLive("string", "play", listOf("val x = R.string.player_brightness"), emptyList()))
        assertTrue("a resource reference is not matched as a prefix either",
            !isLive("string", "play", emptyList(), listOf(File("a.xml") to """text>@string/player_x<""")))
    }
}
