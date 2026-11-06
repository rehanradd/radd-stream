package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Chapter ticks (plan §5 step 11, P14): pack episode boundaries → tick fractions
 * on the scrubber. Only a known offset strictly inside the file is a chapter.
 */
class ChapterTicksTest {

    private fun episode(number: Int, offsetSeconds: Int?, title: String? = null) =
        EpisodeCoverage(number = number, offsetSeconds = offsetSeconds, chapterTitle = title)

    @Test
    fun `offsets become fractions in play order`() {
        val ticks = chapterTicks(
            listOf(
                episode(1, 0),
                episode(2, 600, "Second"),
                episode(3, 1200),
            ),
            durationMs = 1_800_000L,
        )
        assertEquals(2, ticks.size)
        assertEquals(600_000L, ticks[0].offsetMs)
        assertEquals("Second", ticks[0].title)
        assertEquals(1f / 3f, ticks[0].fraction, 0.001f)
        assertEquals(1_200_000L, ticks[1].offsetMs)
        assertEquals("Episode 3", ticks[1].title)
        assertEquals(2f / 3f, ticks[1].fraction, 0.001f)
    }

    @Test
    fun `no duration means no ticks`() {
        assertTrue(chapterTicks(listOf(episode(2, 600)), durationMs = 0L).isEmpty())
    }

    @Test
    fun `offsets outside the file are not chapters`() {
        val ticks = chapterTicks(
            listOf(episode(2, 600), episode(3, 3600), episode(4, -30), episode(5, null)),
            durationMs = 1_800_000L,
        )
        assertEquals(listOf(600_000L), ticks.map { it.offsetMs })
    }

    @Test
    fun `duplicate offsets collapse and server order does not matter`() {
        val ticks = chapterTicks(
            listOf(episode(3, 1200), episode(2, 600), episode(2, 600, "Again")),
            durationMs = 1_800_000L,
        )
        assertEquals(listOf(600_000L, 1_200_000L), ticks.map { it.offsetMs })
    }
}
