package com.raddstream.app.viewmodel

import com.raddstream.app.data.local.FavoritePost
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The My List order: unwatched-first puts titles with no finished watch
 * row ahead of finished ones, then recently-added inside each half. A
 * half-watched title still counts as unwatched.
 */
class MyListSortTest {

    private fun fav(id: Int, title: String, addedAt: Long) =
        FavoritePost(id = id, title = title, cleanTitle = title, addedAt = addedAt)

    @Test
    fun `unwatched first, then recently added inside each half`() {
        val rows = listOf(
            fav(1, "Watched Old", addedAt = 100L),
            fav(2, "Unwatched New", addedAt = 300L),
            fav(3, "Watched New", addedAt = 400L),
            fav(4, "Unwatched Old", addedAt = 200L),
        )
        val sorted = sortMyList(rows, ListSort.UNWATCHED, setOf("Watched Old", "Watched New"))
        assertEquals(listOf(2, 4, 3, 1), sorted.map { it.id })
    }

    @Test
    fun `recent and title orders are unchanged`() {
        val rows = listOf(
            fav(1, "Beta", addedAt = 100L),
            fav(2, "Alpha", addedAt = 300L),
        )
        assertEquals(listOf(2, 1), sortMyList(rows, ListSort.RECENT, emptySet()).map { it.id })
        assertEquals(listOf(2, 1), sortMyList(rows, ListSort.TITLE, emptySet()).map { it.id })
    }
}
