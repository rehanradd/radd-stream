package com.raddstream.app.tooling

import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Sweep #10: the in-run resume map `resumeByTarget` is READ by the stream-id handle
 * (`beginBundle`'s and `seedResumeFromStoredPositions`'s `resumeKey`, which `peekWorkRef`
 * resolves handle → scope), so every WRITE must land under that same key. It used to be that
 * `rememberResume` and `playFrom` keyed by `target.workKey` instead — pause/destroy progress
 * went into an entry no reader consults, and the stale handle-keyed seed kept offering
 * "Resume from X" after a re-open inside the same ViewModel.
 *
 * A source scan is the honest offline proof: instantiating `PlayerViewModel` needs a Media3
 * controller and a Hilt graph, which no suite on this repo has; the invariant, though, is a
 * property of the text. Each refusal is anchored to the declaration it governs and paired
 * with a positive control in the same file, so a rename or deletion fails loudly instead of
 * passing an empty scan (the pattern `AdCadenceGuardTest` and `StatsHonestyTest` exist for).
 */
class ResumeKeyGuardTest {

    private val source: File by lazy {
        var dir: File? = File("").absoluteFile
        while (dir != null) {
            val candidate = File(dir, "App/app/src/main/kotlin/com/raddstream/app/viewmodel/PlayerViewModel.kt")
            if (candidate.isFile) return@lazy candidate
            dir = dir.parentFile
        }
        error("PlayerViewModel.kt not found above ${File("").absolutePath}")
    }

    private val lines: List<String> by lazy { source.readLines() }

    private fun block(start: String): List<String> {
        val from = lines.indexOfFirst { start in it }
        assertTrue("no declaration containing \"$start\" — the guard's subject moved or vanished", from >= 0)
        var depth = 0
        var seenBody = false
        for (index in from until lines.size) {
            val line = lines[index]
            depth += line.count { it == '{' } - line.count { it == '}' }
            if ('{' in line) seenBody = true
            if (seenBody && depth <= 0) return lines.subList(from, index + 1)
        }
        error("unbalanced body starting at \"$start\"")
    }

    @Test
    fun `the read side still keys by the opened handle`() {
        // Positive controls: if either reader stops using `resumeKey`, this whole guard is
        // asserting about a file that no longer has the rule it protects.
        assertTrue(
            "beginBundle must offer from resumeByTarget[resumeKey]",
            block("private fun beginBundle").any { "resumeByTarget[resumeKey]" in it },
        )
        assertTrue(
            "the seed path must consult and write the same handle key",
            block("private suspend fun seedResumeFromStoredPositions")
                .count { "resumeByTarget[resumeKey]" in it } >= 2,
        )
    }

    @Test
    fun `rememberResume writes under the opened handle, never the work key first`() {
        val body = block("private fun rememberResume(")
        val keyLine = body.firstOrNull { Regex("""\bval key\s*=""").containsMatchIn(it) }
        assertTrue("rememberResume lost its key resolution line", keyLine != null)
        assertTrue(
            "rememberResume must prefer activeResumeKey (the read key) over target.workKey — " +
                "sweep #10's orphaned-progress bug: <$keyLine>",
            keyLine!!.indexOf("activeResumeKey") in 0 until keyLine.indexOf("workKey").let {
                if (it < 0) keyLine.length else it
            },
        )
    }

    @Test
    fun `playFrom resolves its load key through activeResumeKey too`() {
        val body = block("fun playFrom(")
        assertTrue(
            "playFrom must load under the opened handle, not the work key (sweep #10)",
            body.any { "val key = activeResumeKey" in it },
        )
    }

    @Test
    fun `the opened key is recorded on every bundle entry and every load`() {
        assertTrue(
            "beginBundle must record activeResumeKey = resumeKey",
            block("private fun beginBundle").any { "activeResumeKey = resumeKey" in it },
        )
        assertTrue(
            "loadNow must record it too, so resolveResume/playFrom paths agree",
            block("private fun loadNow").any { "activeResumeKey = resumeKey" in it },
        )
    }

    @Test
    fun `no dead work-key-only write survives in the resume declarations`() {
        // The old bug was a write site that keyed ONLY by workKey. `activeResumeKey ?:` is the
        // allowed fallback order; a bare `resumeByTarget[bundle.target.workKey` is the bug.
        for (name in listOf("private fun rememberResume(", "fun playFrom(")) {
            val body = block(name)
            assertTrue(
                "$name must not write/read resumeByTarget under a bare target.workKey key",
                body.none { Regex("""resumeByTarget\[\s*(bundle\.)?target\.workKey""").containsMatchIn(it) },
            )
        }
    }
}
