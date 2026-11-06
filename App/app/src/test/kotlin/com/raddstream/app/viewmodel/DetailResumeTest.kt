package com.raddstream.app.viewmodel

import com.raddstream.app.data.local.WatchHistoryEntity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The Detail resume math: the latest resumable row is the button's target,
 * every watched episode carries its own mark, and a runtime is only ever a
 * plain "2 h 10 m" — never an invented number.
 */
class DetailResumeTest {

    private fun row(
        season: Int = 1,
        episode: Int = 3,
        positionMs: Long = 600_000L,
        durationMs: Long = 3_600_000L,
    ) = WatchHistoryEntity(
        workRef = "imdb:tt9999999",
        postId = 101,
        title = "Example Show",
        posterUrl = null,
        seasonNumber = season,
        episodeNumber = episode,
        positionMs = positionMs,
        durationMs = durationMs,
        updatedAt = 1L,
    )

    @Test
    fun `newest resumable row is the resume point`() {
        val rows = listOf(
            row(episode = 4, positionMs = 900_000L),
            row(episode = 3, positionMs = 600_000L),
        )

        val resume = resumePointFor(rows)!!

        assertEquals(1, resume.season)
        assertEquals(4, resume.episode)
        assertEquals("Resume S1:E4 · 45 min left", resume.label)
    }

    @Test
    fun `a movie row resumes without a season label`() {
        val resume = resumePointFor(listOf(row(season = 0, episode = 0)))!!

        assertEquals("Resume · 50 min left", resume.label)
    }

    @Test
    fun `finished rows and empty history give no resume`() {
        // Ran to within the end guard: watched, not resumable.
        assertNull(resumePointFor(listOf(row(positionMs = 3_595_000L))))
        assertNull(resumePointFor(emptyList()))
    }

    @Test
    fun `episode progress marks a half-watched episode`() {
        val marks = episodeProgressFor(listOf(row(positionMs = 1_800_000L)))

        val mark = marks[1 to 3]!!
        assertEquals(0.5f, mark.fraction)
        assertFalse(mark.watched)
        assertEquals("30 min left", mark.remainingLabel)
    }

    @Test
    fun `episode progress marks a watched episode and an unknown duration`() {
        val marks = episodeProgressFor(
            listOf(
                row(season = 1, episode = 1, positionMs = 3_595_000L),
                row(season = 1, episode = 2, durationMs = 0L),
            ),
        )

        val watched = marks[1 to 1]!!
        assertTrue(watched.watched)
        assertNull(watched.remainingLabel)

        val unknown = marks[1 to 2]!!
        assertNull(unknown.fraction)
        assertFalse(unknown.watched)
        assertNull(unknown.remainingLabel)
    }

    @Test
    fun `runtime formats as minutes under an hour and hours above`() {
        assertNull(formatRuntimeMinutes(null))
        assertNull(formatRuntimeMinutes(0))
        assertEquals("45 min", formatRuntimeMinutes(45))
        assertEquals("1 h", formatRuntimeMinutes(60))
        assertEquals("2 h 10 m", formatRuntimeMinutes(130))
    }
}
