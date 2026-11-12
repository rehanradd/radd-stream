package com.raddstream.app.viewmodel

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * UI-fix P1-H5/P1-S2: the language filter the server already answers
 * (`language=hindi`) but the app never exposed. Pins the wire values and
 * that a language counts as an active server filter (so a blank query with
 * a language still searches, and the "Filtered" pill lights).
 */
class SearchLanguageFilterTest {

    @Test
    fun `language wire values are the server lowercase names`() {
        assertEquals("hindi", LanguageFilter.HINDI.wireValue)
        assertEquals("urdu", LanguageFilter.URDU.wireValue)
        assertEquals("tamil", LanguageFilter.TAMIL.wireValue)
        assertEquals("english", LanguageFilter.ENGLISH.wireValue)
        assertNull(LanguageFilter.ALL.wireValue)
    }

    @Test
    fun `no language selected is the default`() {
        assertEquals(LanguageFilter.ALL, SearchFilters().language)
        assertFalse(SearchFilters().anyServerFilterActive)
    }

    @Test
    fun `a language counts as an active server filter`() {
        val filters = SearchFilters(language = LanguageFilter.HINDI)
        assertTrue(filters.anyServerFilterActive)
        assertTrue(SearchUiState(filters = filters).hasSearchIntent)
        assertTrue(SearchUiState(filters = filters).hasFacetFilters)
    }
}
