package com.raddstream.app.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SearchRecentsTest {

    @Test
    fun newestQueryLeadsAndDuplicatesMoveUp() {
        val next = normalizeSearchRecents(listOf("batman", "inception", "Batman 2022", "batman"))
        assertEquals(listOf("batman", "inception", "Batman 2022"), next)
    }

    @Test
    fun blankQueriesAndWhitespaceAreDropped() {
        val next = normalizeSearchRecents(listOf("", "   ", "  inception  ", "\t"))
        assertEquals(listOf("inception"), next)
    }

    @Test
    fun listIsCappedAtTwentyFromTheNewestEnd() {
        val input = (1..30).map { "query $it" }
        val next = normalizeSearchRecents(input)
        assertEquals(SEARCH_RECENTS_MAX, next.size)
        assertEquals(20, next.size)
        assertEquals("query 1", next.first())
        assertEquals("query 20", next.last())
    }

    @Test
    fun separatorInsideAQueryCannotSplitTheStoredList() {
        val hostile = "a${'\u001F'}b"
        val normalized = normalizeSearchRecents(listOf(hostile))
        assertEquals(listOf("ab"), normalized)
        assertEquals(listOf("ab"), decodeSearchRecents(normalized.joinToString("\u001F")))
    }

    @Test
    fun decodeOfEmptyOrAbsentValueIsAnEmptyRail() {
        assertTrue(decodeSearchRecents(null).isEmpty())
        assertTrue(decodeSearchRecents("").isEmpty())
        assertTrue(decodeSearchRecents("\u001F\u001F").isEmpty())
    }

    @Test
    fun decodeKeepsOrderAcrossTheSeparator() {
        val stored = listOf("first", "second", "third").joinToString("\u001F")
        assertEquals(listOf("first", "second", "third"), decodeSearchRecents(stored))
    }

    @Test
    fun dedupeIsCaseSensitiveLikeTheRailItReplaces() {
        val next = normalizeSearchRecents(listOf("Inception", "inception"))
        assertEquals(2, next.size)
    }
}
