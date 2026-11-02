package com.raddstream.app.player

import com.raddstream.app.player.QualityChoice.CopyCandidate
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * The picture-quality rule, pinned on the JVM.
 *
 * Four branches carry the whole spec section: a first-ever play uses 720p; a saved choice wins
 * afterwards; the menu offers only bands this title has; and when the asked-for band is missing the
 * app steps to the nearest LOWER one, then the nearest HIGHER, and says which picture arrived. Plus
 * the copy inside a band: alive, resumable and measured beats fast-but-rotting, and CAM sorts last.
 *
 * Each of those was a branch an author could silently invert, and none of them can be checked by
 * looking at a screen — a title that happens to have every band hides the fallback rule entirely,
 * and the fallback is the case the viewer remembers. The sentence the substitution earns is pinned
 * here too, in the file that owns it: see [the note sentence is the owners words].
 */
class QualityChoiceTest {

    private val ladder = listOf("360p", "480p", "720p", "1080p")

    // ── what a play tap asks for ──────────────────────────────────────────────

    @Test
    fun `a first ever play asks for 720p`() {
        assertEquals("720p", QualityChoice.FIRST_RUN_BAND)
        val plan = QualityChoice.planFor(savedBand = null, present = ladder)
        assertEquals("720p", plan.band)
        assertTrue("the default exists here, so nothing was substituted", plan.isExact)
        assertNull("a note about a substitution that did not happen is noise", plan.playedLabel)
    }

    @Test
    fun `a saved choice outranks the default`() {
        val plan = QualityChoice.planFor(savedBand = "480p", present = ladder)
        assertEquals("480p", plan.band)
        assertTrue(plan.isExact)
    }

    @Test
    fun `a saved choice is read whatever way it was spelled`() {
        // The preference survives a restart and a different switch's vocabulary: `4K` saved by a
        // build that spelled the rung that way must still match a title whose band is `2160p`.
        val plan = QualityChoice.planFor(savedBand = " 4K ", present = listOf("720p", "2160p"))
        assertEquals("2160p", plan.band)
        assertTrue("synonyms are one picture, so this is not a substitution", plan.isExact)
    }

    @Test
    fun `a blank saved choice is the same as never having been asked`() {
        assertEquals("720p", QualityChoice.planFor(savedBand = "   ", present = ladder).band)
    }

    // ── the menu ──────────────────────────────────────────────────────────────

    @Test
    fun `the menu lists only bands this title has`() {
        assertEquals(
            listOf("480p"),
            QualityChoice.bandsPresent(listOf("480p", null, "480p", "  ", "")),
        )
    }

    @Test
    fun `the menu is ordered cheapest picture first`() {
        assertEquals(
            listOf("360p", "480p", "720p", "1080p"),
            QualityChoice.bandsPresent(listOf("1080p", "480p", "720p", "360p")),
        )
    }

    @Test
    fun `two spellings of one picture are one menu row`() {
        assertEquals(
            listOf("1080p", "2160p"),
            QualityChoice.bandsPresent(listOf("Full HD", "fhd", "1080p", "4K", "uhd", "2160p")),
        )
    }

    @Test
    fun `a band word this file does not know is still offered, last`() {
        // Dropping a rung the server sent would hide a picture the viewer could watch; ranking it
        // anywhere in the known order would guess at a height nobody measured.
        assertEquals(
            listOf("480p", "720p", "hdr-unknown"),
            QualityChoice.bandsPresent(listOf("hdr-unknown", "720p", "480p")),
        )
    }

    // ── the fallback ──────────────────────────────────────────────────────────

    @Test
    fun `a missing band steps to the nearest lower one first`() {
        val plan = QualityChoice.fallbackFrom(requested = "1080p", present = listOf("360p", "480p", "720p"))
        assertEquals("720p", plan.band)
        assertEquals(QualityChoice.Step.LOWER, plan.step)
        assertEquals("720p", plan.playedLabel)
        assertEquals("1080p", plan.missingLabel)
    }

    @Test
    fun `nearest lower means nearest, not lowest`() {
        val plan = QualityChoice.fallbackFrom(requested = "720p", present = listOf("360p", "480p"))
        assertEquals("480p", plan.band)
        assertEquals(QualityChoice.Step.LOWER, plan.step)
    }

    @Test
    fun `with nothing lower it steps to the nearest higher one`() {
        val plan = QualityChoice.fallbackFrom(requested = "360p", present = listOf("480p", "720p", "1080p"))
        assertEquals("480p", plan.band)
        assertEquals(QualityChoice.Step.HIGHER, plan.step)
        assertEquals("480p", plan.playedLabel)
        assertEquals("360p", plan.missingLabel)
    }

    @Test
    fun `a nearer higher band does not beat a lower one`() {
        // 1080p is one rung above 720p and 360p is two below, so the nearer option is the step UP.
        // The spec's order is not "whichever is closest overall": a viewer whose connection cannot
        // hold the picture they chose gets fewer bytes, not more.
        val plan = QualityChoice.fallbackFrom(requested = "720p", present = listOf("360p", "1080p"))
        assertEquals("360p", plan.band)
        assertEquals(QualityChoice.Step.LOWER, plan.step)
    }

    @Test
    fun `an exact match produces no note at all`() {
        val plan = QualityChoice.fallbackFrom(requested = "720p", present = ladder)
        assertTrue(plan.isExact)
        assertNull(plan.playedLabel)
        assertNull(plan.missingLabel)
    }

    @Test
    fun `nothing present promises nothing`() {
        val plan = QualityChoice.planFor(savedBand = null, present = emptyList())
        assertNull(plan.band)
        assertNull(plan.playedLabel)
    }

    @Test
    fun `a word this file cannot place never earns a substitution note`() {
        // An unrecognised saved band is "no preference", not "a preference we failed to honour".
        // Saying which picture the viewer asked for, in a word we cannot read, would be a guess.
        val plan = QualityChoice.planFor(savedBand = "hd", present = listOf("360p", "480p"))
        assertEquals("480p", plan.band)
        assertTrue("the middle of what exists is the honest no-preference answer", plan.isExact)
        assertNull(plan.playedLabel)
    }

    @Test
    fun `a picture this file cannot name is never described in the note`() {
        val plan = QualityChoice.fallbackFrom(requested = "720p", present = listOf("unspecified"))
        assertEquals("unspecified", plan.band)
        assertEquals(QualityChoice.Step.LOWER, plan.step)
        assertNull("no invented words about a band nobody measured", plan.playedLabel)
    }

    // ── which copy inside the band ────────────────────────────────────────────

    private fun copy(
        handle: String,
        alive: Boolean = true,
        resumable: Boolean = true,
        sizeKnown: Boolean = true,
        ephemeral: Boolean = false,
        speedMbps: Double? = 5.0,
        rankScore: Int = 0,
        camCopy: Boolean = false,
    ) = CopyCandidate(
        handle = handle,
        alive = alive,
        resumable = resumable,
        sizeKnown = sizeKnown,
        ephemeral = ephemeral,
        speedMbps = speedMbps,
        rankScore = rankScore,
        camCopy = camCopy,
    )

    @Test
    fun `the winner is the copy this app can start and restart`() {
        val winner = QualityChoice.bestCopy(
            listOf(
                copy("dead-fast", alive = false, speedMbps = 90.0),
                copy("no-resume", resumable = false, speedMbps = 60.0),
                copy("measured", speedMbps = 4.0),
            ),
        )
        assertEquals("measured", winner?.handle)
    }

    @Test
    fun `raw speed never outranks being able to resume`() {
        val winner = QualityChoice.bestCopy(
            listOf(copy("slow-resumable", resumable = true, speedMbps = 1.0), copy("fast-fragile", resumable = false, speedMbps = 500.0)),
        )
        assertEquals("slow-resumable", winner?.handle)
    }

    @Test
    fun `a copy whose address rots loses to one that holds`() {
        val winner = QualityChoice.bestCopy(
            listOf(copy("signed-today", ephemeral = true), copy("stable", ephemeral = false)),
        )
        assertEquals("stable", winner?.handle)
    }

    @Test
    fun `a cam copy is last when anything clean exists`() {
        val ordered = QualityChoice.sortedForFailover(
            listOf(copy("cam", camCopy = true, speedMbps = 80.0), copy("clean", camCopy = false, speedMbps = 2.0)),
        )
        assertEquals(listOf("clean", "cam"), ordered.map { it.handle })
    }

    @Test
    fun `speed and the servers own rank break a tie between equal copies`() {
        assertEquals("quick", QualityChoice.bestCopy(listOf(copy("slow", speedMbps = 2.0), copy("quick", speedMbps = 9.0)))?.handle)
        assertEquals("ranked", QualityChoice.bestCopy(listOf(copy("plain", rankScore = 100), copy("ranked", rankScore = 9000)))?.handle)
    }

    @Test
    fun `failover keeps every copy it was given`() {
        val copies = listOf(copy("a"), copy("b", resumable = false), copy("c", alive = false))
        val ordered = QualityChoice.sortedForFailover(copies)
        assertEquals(copies.map { it.handle }.sorted(), ordered.map { it.handle }.sorted())
        assertEquals("a", ordered.first().handle)
        // Equal scores keep the order the ladder served them in: the trail has to be readable
        // against the response it came from, so nothing here re-shuffles a tie.
        assertEquals(
            listOf("x", "y"),
            QualityChoice.sortedForFailover(listOf(copy("x"), copy("y"))).map { it.handle },
        )
    }

    @Test
    fun `no copies means no winner`() {
        assertNull(QualityChoice.bestCopy(emptyList()))
        assertEquals(emptyList<CopyCandidate>(), QualityChoice.sortedForFailover(emptyList()))
    }

    // ── the sentence itself ───────────────────────────────────────────────────

    @Test
    fun `the note sentence is the owners words`() {
        // The rule is tested two ways on purpose: this file pins WHICH two words go in the blanks,
        // and the resource file owns how the sentence reads. If a screen ever assembles its own
        // sentence from the band names, the English drifts and nothing fails.
        val xml = File(repoRoot, "App/app/src/main/res/values/strings.xml").readText()
        val line = xml.lines().firstOrNull { it.trim().startsWith("""<string name="detail_quality_note">""") }
        assertTrue("the substitution sentence must live in res/values, not in a composable", line != null)
        assertTrue(
            "the sentence needs both halves as positional arguments: $line",
            line!!.contains("%1${'$'}s") && line.contains("%2${'$'}s"),
        )
        val text = line.trim()
            .removePrefix("""<string name="detail_quality_note">""")
            .removeSuffix("</string>")
            .replace("&#8212;", "—").replace("&amp;", "&")
        assertEquals(
            "Playing in %1\$s — %2\$s is not available for this title.",
            text,
        )
    }

    private val repoRoot: File by lazy {
        var dir: File? = File("").absoluteFile
        while (dir != null) {
            if (File(dir, "brand.properties").isFile) return@lazy dir
            dir = dir.parentFile
        }
        error("brand.properties not found above ${File("").absolutePath}")
    }
}
