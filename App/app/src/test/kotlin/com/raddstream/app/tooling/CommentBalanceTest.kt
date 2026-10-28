package com.raddstream.app.tooling

import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * A Kotlin block comment OPENS AGAIN inside itself: an opener sequence found while a block
 * comment is already running starts a nested comment, and the first closer sequence ends only
 * that nested one. A file glob written into a doc comment therefore leaves the outer comment
 * open until end of file, every declaration below it is orphaned, and the compiler reports
 * about 150 unrelated "Unresolved reference" errors in the files that merely import them —
 * naming no file and no line for the cause. That is how this tree lost 271 errors to one
 * string, once.
 *
 * This guard walks every source file with a real depth scanner and names the line where the
 * depth never came back to zero. The prose above deliberately spells the marker sequences out
 * in words: writing them here would trip exactly what this test looks for.
 */
class CommentBalanceTest {

    @Test
    fun `every kotlin source file has balanced block comments`() {
        val roots = listOf(
            File("src/main/kotlin"),
            File("src/test/kotlin"),
        ).filter { it.isDirectory }
        assertTrue("must run from the app module directory", roots.isNotEmpty())

        val broken = roots.flatMap { root ->
            root.walkTopDown().filter { it.isFile && it.extension == "kt" }
                .mapNotNull { file -> scan(file.readText())?.let { "${file.path}:$it" } }
        }

        assertTrue(
            "unbalanced block comment (a nested opener swallowed the closer): $broken",
            broken.isEmpty(),
        )
    }

    /** The guard needs a guard: these shapes must be told apart, not guessed at. */
    @Test
    fun `the scanner separates comment nesting from strings and line comments`() {
        assertTrue("a glob inside a doc comment must be flagged",
            scan(NESTED_IN_DOC) != null)
        assertTrue("a plain doc comment must not be flagged", scan(PLAIN_DOC) == null)
        assertTrue("a glob inside a string is not a comment", scan(GLOB_IN_STRING) == null)
        assertTrue("nesting must be counted, not matched first-close",
            scan(NESTED_IN_CODE) != null)
        assertTrue("an opener inside a string must not open a comment",
            scan(OPENER_IN_STRING) == null)
        assertTrue("a character literal must not start a string", scan(CHAR_LITERAL) == null)
        assertTrue("an apostrophe inside a comment is not a string",
            scan(APOSTROPHE_IN_DOC) == null)
        assertTrue("a raw string ending in a quote must not leak a phantom opener",
            scan(RAW_ENDS_IN_QUOTE) == null)
        assertTrue("the run rule must not blind the scanner to a real nested opener",
            scan(RAW_THEN_NESTED) != null)
    }

    /** Returns the 1-based line where block-comment depth was still open at EOF, else null. */
    internal fun scan(text: String): Int? {
        var depth = 0
        var line = 1
        var i = 0
        var inString: String? = null
        while (i < text.length) {
            val c = text[i]
            if (c == '\n') line++
            val quote = inString
            if (quote != null) {
                if (c == '\\' && quote != TRIPLE) {
                    i += 2
                    continue
                }
                if (quote == TRIPLE && c == '"') {
                    // A raw string ends at the LAST three quotes of a run, so `}""""` is a
                    // string whose content ends in a quote. Closing at the first three would
                    // leave one quote behind to open a phantom string and desynchronise
                    // every line below it.
                    var run = 0
                    while (i + run < text.length && text[i + run] == '"') run++
                    if (run >= 3) inString = null
                    i += run
                    continue
                }
                if (text.startsWith(quote, i)) {
                    inString = null
                    i += quote.length
                    continue
                }
                i++
                continue
            }
            if (depth > 0) {
                // Inside a comment no quote opens a string; only the nesting markers count.
                when {
                    text.startsWith(OPEN, i) -> {
                        depth++
                        i += 2
                    }
                    text.startsWith(CLOSE, i) -> {
                        depth--
                        i += 2
                    }
                    else -> i++
                }
                continue
            }
            when {
                text.startsWith(LINE, i) -> {
                    while (i < text.length && text[i] != '\n') i++
                }
                text.startsWith(OPEN, i) -> {
                    depth++
                    i += 2
                }
                text.startsWith(TRIPLE, i) -> {
                    inString = TRIPLE
                    i += TRIPLE.length
                }
                c == '"' -> {
                    inString = "\""
                    i++
                }
                c == '\'' -> {
                    var j = i + 1
                    while (j < text.length && text[j] != '\'') {
                        if (text[j] == '\\') j++
                        if (text[j] == '\n') return line
                        j++
                    }
                    i = j + 1
                }
                else -> i++
            }
        }
        return if (depth > 0) line else null
    }

    private companion object {
        const val TRIPLE = "\"\"\""
        // Assembled rather than written: this file has to satisfy its own check.
        val OPEN = "/" + "*"
        val CLOSE = "*" + "/"
        val LINE = "/" + "/"
        val STAR = "*"

        val NESTED_IN_DOC = OPEN + STAR + " Reads from data/cache" + OPEN + STAR +
            " every pass. " + CLOSE + "\nclass CacheEngine"
        val PLAIN_DOC = OPEN + STAR + " ordinary doc. " + CLOSE + "\nclass Ok"
        val GLOB_IN_STRING = "val glob = \"cache" + STAR + STAR + "\" " + LINE + " not a comment"
        val NESTED_IN_CODE = OPEN + " outer " + OPEN + " inner " + CLOSE + " still open"
        val OPENER_IN_STRING = "val s = \"a " + OPEN + " not a comment\"\nclass Ok"
        val CHAR_LITERAL = "val c = '" + "/" + "'\nclass Ok"
        val APOSTROPHE_IN_DOC = OPEN + STAR + " doc with an apostrophe: don't do this " +
            CLOSE + "\nclass Ok"
        // `val s = """{"a": 1}""""` — four closing quotes: content ends in one, Kotlin
        // closes at the last three, and an opener on the following line is still real code.
        val RAW_ENDS_IN_QUOTE = "val s = " + TRIPLE + "{\"a\": 1}" + TRIPLE + "\"\nclass Ok"
        val RAW_THEN_NESTED = RAW_ENDS_IN_QUOTE + "\n" + OPEN + STAR + " doc " +
            OPEN + STAR + " again " + CLOSE
    }
}
