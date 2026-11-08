package com.raddstream.app.network.models

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Session 114: the app re-sorts seasons itself in [V1CatalogMapper.work], so
 * the server cannot fix season order — the flip lives here. The latest season
 * comes first (S04 before S01); episodes inside a season stay oldest-first.
 */
class V1CatalogMapperSeasonsTest {

    private fun release(id: Int, title: String, season: String, episode: String) =
        ReleaseDetail(
            id = id,
            releaseTitle = title,
            season = season,
            episode = episode,
        )

    @Test
    fun `later seasons sort before earlier ones and episodes stay ascending`() {
        val detail = PostDetail(
            id = 1,
            title = "Alpha",
            contentType = "series",
            releases = listOf(
                release(1, "Alpha S01 E01", "1", "1"),
                release(2, "Alpha S01 E02", "1", "2"),
                release(3, "Alpha S04 E01", "4", "1"),
            ),
        )
        val work = V1CatalogMapper.work(detail)
        assertEquals(listOf(4, 1), work.seasons.map { it.number })
        val s1 = work.seasons.first { it.number == 1 }
        assertEquals(listOf(1, 2), s1.episodes.map { it.number })
    }
}
