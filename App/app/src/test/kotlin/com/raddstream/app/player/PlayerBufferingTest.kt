package com.raddstream.app.player

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The buffering policy is the difference between a player that starts when you tap and a player
 * that shows a spinner, and it is four numbers whose *relationship* is what makes them work.
 * Media3 checks that relationship by throwing while the service is building the player — so a
 * mistyped pair is a crash at the first play, on a phone, in front of a viewer.
 *
 * `DefaultLoadControl.Builder` takes them positionally (`min, max, forPlayback, afterRebuffer`),
 * which means two of them can be swapped in a call site and still compile. That is the second
 * thing under test here: not the values, but that the service reads them from the one owner and
 * in the order the method expects.
 */
class PlayerBufferingTest {

    @Test
    fun `the startup buffers fit inside the holding buffers the way Media3 requires`() {
        // Builder.build() asserts each of these on the device; failing them here is the point.
        assertTrue(
            "playback must not start on more media than the player is asked to hold",
            PlayerBuffering.BUFFER_FOR_PLAYBACK_MS <= PlayerBuffering.MIN_BUFFER_MS,
        )
        assertTrue(
            "a re-buffered start may wait longer than a cold one, but never longer than the " +
                "player is holding",
            PlayerBuffering.BUFFER_FOR_PLAYBACK_AFTER_REBUFFER_MS <= PlayerBuffering.MIN_BUFFER_MS,
        )
        assertTrue(
            "the minimum the player aims for cannot exceed the ceiling it is allowed to reach",
            PlayerBuffering.MIN_BUFFER_MS <= PlayerBuffering.MAX_BUFFER_MS,
        )
    }

    @Test
    fun `starting is a fraction of a second and recovery is not the same fraction`() {
        assertEquals(
            "half a second of media is the whole instant-start promise; a bigger number here is " +
                "a spinner by another name",
            500,
            PlayerBuffering.BUFFER_FOR_PLAYBACK_MS,
        )
        assertTrue(
            "a cold start and a post-stall start must not be the same threshold, or a player " +
                "that just stalled starts again into the next one",
            PlayerBuffering.BUFFER_FOR_PLAYBACK_AFTER_REBUFFER_MS > PlayerBuffering.BUFFER_FOR_PLAYBACK_MS,
        )
        assertTrue(
            "the holding target has to be long enough to survive a slow segment: a five-second " +
                "buffer is a re-buffer per scene on a mobile link",
            PlayerBuffering.MIN_BUFFER_MS >= 10_000,
        )
        assertTrue(PlayerBuffering.PRIORITIZE_TIME_OVER_SIZE)
    }

    /**
     * The census is the part that cannot be answered by reading one file: the numbers have to be
     * handed to Media3 in the order the method takes them, and a second load control built
     * somewhere else is a second buffering policy that nobody is changing when this one is.
     */
    @Test
    fun `one file owns the buffer durations and the service feeds them to load control in order`() {
        val sources = mainSources()
        val names = Regex(
            """const val (MIN_BUFFER_MS|MAX_BUFFER_MS|BUFFER_FOR_PLAYBACK_MS""" +
                """|BUFFER_FOR_PLAYBACK_AFTER_REBUFFER_MS|PRIORITIZE_TIME_OVER_SIZE)\b""",
        )
        val declarations = sources.flatMap { file ->
            names.findAll(file.readText()).map { "${file.path}:${it.groupValues[1]}" }.toList()
        }
        assertEquals(
            "a duration declared twice is two answers to how much media the player holds",
            listOf(
                "$OWNER_PATH:MIN_BUFFER_MS",
                "$OWNER_PATH:MAX_BUFFER_MS",
                "$OWNER_PATH:BUFFER_FOR_PLAYBACK_MS",
                "$OWNER_PATH:BUFFER_FOR_PLAYBACK_AFTER_REBUFFER_MS",
                "$OWNER_PATH:PRIORITIZE_TIME_OVER_SIZE",
            ).sorted(),
            declarations.sorted(),
        )

        val builders = sources.filter { Regex("""DefaultLoadControl\.Builder\(\)""").containsMatchIn(it.readText()) }
            .map { it.path }
        assertEquals(
            "exactly one place may construct the load control, and it must read from the owner",
            listOf(SERVICE_PATH),
            builders,
        )

        val service = File(SERVICE_PATH).readText()
        assertEquals(
            "setBufferDurationsMs is positional: a pair swapped here compiles and changes when " +
                "the first frame appears",
            listOf(
                "MIN_BUFFER_MS",
                "MAX_BUFFER_MS",
                "BUFFER_FOR_PLAYBACK_MS",
                "BUFFER_FOR_PLAYBACK_AFTER_REBUFFER_MS",
            ),
            orderedOwners(service).map { it.groupValues[1] },
        )
        assertTrue(
            "a load control that is built and never installed is a policy on a dead object",
            Regex("""\.setLoadControl\(loadControl\(\)\)""").containsMatchIn(service),
        )
        assertTrue(
            "the time-over-size switch has to be the owner's value, not a second literal",
            Regex("""setPrioritizeTimeOverSizeThresholds\(PlayerBuffering\.PRIORITIZE_TIME_OVER_SIZE\)""")
                .containsMatchIn(service),
        )
    }

    /**
     * Seeking is the other half of feeling instant, and it is the half that was written once in a
     * live tree, never landed, and therefore shipped as nothing: `ExoPlayer` defaults to
     * [androidx.media3.exoplayer.SeekParameters.DEFAULT], which decodes forward from the previous
     * sync frame. A text scan is the only gate available here — building a real player needs an
     * Android `Context`, and the Robolectric suites that could are excluded on this architecture —
     * so the scan asserts both the call and the object it is called on.
     */
    @Test
    fun `the service sets the seek parameters on the player it just built`() {
        val service = File(SERVICE_PATH).readText()
        val built = service.substringAfter("ExoPlayer.Builder(this)").substringBefore("player = exo")
        assertTrue(
            "positive control: the builder block was still found — an empty slice would make " +
                "every assertion below pass over nothing",
            built.isNotBlank() && built.contains(".build()"),
        )
        assertTrue(
            "a scrub must land on the nearest sync frame, not decode forward from the last one",
            built.contains("exo.setSeekParameters(SeekParameters.CLOSEST_SYNC)"),
        )
        assertTrue(
            "and the value must be installed, not computed: ExoPlayer exposes this as a setter " +
                "whose getter returns a different type, so an assignment would not even compile",
            !built.contains("exo.seekParameters ="),
        )

        val installed = "        val exo = ExoPlayer.Builder(this)\n            .build()\n" +
            "        exo.setSeekParameters(SeekParameters.CLOSEST_SYNC)\n        player = exo"
        val computedAndDropped = "        val exo = ExoPlayer.Builder(this)\n            .build()\n" +
            "        val parameters = SeekParameters.CLOSEST_SYNC\n        player = exo"
        val assigned = "        val exo = ExoPlayer.Builder(this)\n            .build()\n" +
            "        exo.seekParameters = SeekParameters.CLOSEST_SYNC\n        player = exo"
        val slice = { text: String -> text.substringAfter("ExoPlayer.Builder(this)").substringBefore("player = exo") }
        assertTrue("a wired player matches", slice(installed).contains("exo.setSeekParameters(SeekParameters.CLOSEST_SYNC)"))
        assertTrue("a value nobody installs does not", !slice(computedAndDropped).contains("setSeekParameters"))
        assertTrue(
            "and the detector is shown to see the assignment shape when it is present, so its " +
                "absence above is a refusal rather than blindness",
            slice(assigned).contains("exo.seekParameters ="),
        )
    }

    /**
     * `SeekParameters` is `androidx.media3.exoplayer.SeekParameters`. There is no
     * `androidx.media3.common.SeekParameters` at Media3 1.3.1, and importing the non-existent one is
     * exactly what broke that build once; the wrong package compiles nowhere, so the guard is the
     * only place the mistake can be caught before a runner does.
     */
    @Test
    fun `the seek parameter type is imported from the package that actually ships it`() {
        val service = File(SERVICE_PATH).readText()
        assertTrue(
            "the shipped package is androidx.media3.exoplayer.SeekParameters",
            service.contains("import androidx.media3.exoplayer.SeekParameters"),
        )
        assertFalse(
            "androidx.media3.common.SeekParameters does not exist and must never be imported",
            service.contains("import androidx.media3.common.SeekParameters"),
        )
        // The guard needs its own guard: the two strings differ only in one word, so prove the
        // scan tells them apart rather than matching any import that mentions the type.
        val correct = "import androidx.media3.exoplayer.SeekParameters\n"
        val wrong = "import androidx.media3.common.SeekParameters\n"
        assertTrue(
            "one accepts the real package and refuses the phantom, the other does the reverse",
            correct.contains("androidx.media3.exoplayer.SeekParameters") &&
                !correct.contains("androidx.media3.common.SeekParameters") &&
                wrong.contains("androidx.media3.common.SeekParameters") &&
                !wrong.contains("androidx.media3.exoplayer.SeekParameters"),
        )
        val census = mainSources().filter {
            Regex("""import androidx\.media3\.common\.SeekParameters""").containsMatchIn(it.readText())
        }.map { it.path }
        assertTrue("no file anywhere may import the phantom type: $census", census.isEmpty())
    }

    /** The guard needs a guard: the scans must be shown to tell these shapes apart. */
    @Test
    fun `the scanners separate a wired-up policy from one that only looks configured`() {
        val wired = "private fun loadControl(): DefaultLoadControl =\n" +
            "    DefaultLoadControl.Builder()\n" +
            "        .setBufferDurationsMs(\n" +
            "            PlayerBuffering.MIN_BUFFER_MS, PlayerBuffering.MAX_BUFFER_MS,\n" +
            "            PlayerBuffering.BUFFER_FOR_PLAYBACK_MS,\n" +
            "            PlayerBuffering.BUFFER_FOR_PLAYBACK_AFTER_REBUFFER_MS,\n" +
            "        ).build()"
        val installed = "        val exo = ExoPlayer.Builder(this)\n" +
            "            .setLoadControl(loadControl())\n" +
            "            .build()"
        val swapped = "        .setBufferDurationsMs(\n" +
            "            PlayerBuffering.MAX_BUFFER_MS, PlayerBuffering.MIN_BUFFER_MS,\n" +
            "            PlayerBuffering.BUFFER_FOR_PLAYBACK_MS,\n" +
            "            PlayerBuffering.BUFFER_FOR_PLAYBACK_AFTER_REBUFFER_MS,\n" +
            "        )"
        val nothing = "// just prose about buffering, no builder at all"

        assertTrue(
            "the four names in order are what the call needs",
            orderedOwners(wired).map { it.groupValues[1] } == listOf(
                "MIN_BUFFER_MS",
                "MAX_BUFFER_MS",
                "BUFFER_FOR_PLAYBACK_MS",
                "BUFFER_FOR_PLAYBACK_AFTER_REBUFFER_MS",
            ),
        )
        assertTrue("a swapped pair is caught by the order, not by luck",
            orderedOwners(swapped).firstOrNull()?.groupValues[1] == "MAX_BUFFER_MS")
        assertTrue("prose is not configuration", orderedOwners(nothing).isEmpty())
        assertTrue(
            "installation is a separate fact from construction",
            Regex("""\.setLoadControl\(loadControl\(\)\)""").containsMatchIn(installed) &&
                !Regex("""\.setLoadControl\(loadControl\(\)\)""").containsMatchIn(wired),
        )
        assertTrue(
            "a scan that matches nothing must not be mistaken for a passing scan",
            orderedOwners(wired).isNotEmpty() &&
                Regex("""DefaultLoadControl\.Builder\(\)""").containsMatchIn(wired) &&
                !Regex("""DefaultLoadControl\.Builder\(\)""").containsMatchIn(nothing),
        )
    }

    /** The four owner references inside one `setBufferDurationsMs` call, in the order they appear. */
    private fun orderedOwners(text: String): List<MatchResult> =
        Regex("""setBufferDurationsMs\(([^)]*)\)""").find(text)
            ?.groupValues
            ?.get(1)
            ?.let { block ->
                Regex("""PlayerBuffering\.(\w+)""").findAll(block).toList()
            }
            ?: emptyList()

    private fun mainSources(): List<File> =
        File("src/main/kotlin").walkTopDown()
            .filter { it.isFile && it.extension == "kt" }
            .toList()
            .also { assertTrue("must run from the app module directory", it.isNotEmpty()) }

    private companion object {
        const val SERVICE_PATH = "src/main/kotlin/com/raddstream/app/player/PlaybackService.kt"
        const val OWNER_PATH = "src/main/kotlin/com/raddstream/app/player/PlayerBuffering.kt"
    }
}
