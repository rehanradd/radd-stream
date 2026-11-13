package com.raddstream.app.viewmodel

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Session 158 (S5): an identical search whose results are already on
 * screen must not be fetched twice. Typing fires a debounced search and
 * pressing Search (IME) fires an immediate one for the SAME query — the
 * S5 log shows "Tarzan" submitted twice 2 s apart and "Tarzan's Revenge"
 * twice the same way — and the second fetch re-emits the whole list in
 * exactly the window the viewer taps a result in. The first tap dropped;
 * the second (after everything settled) always worked. These tests pin
 * the skip rule itself, not the ViewModel wiring: only an exact match
 * with results showing and no error skips.
 */
class SearchResubmitDedupTest {

    private val key = CompletedSearchKey("Tarzan", SearchFilters(), SearchSort.DEFAULT)

    @Test
    fun `an identical search with results showing and no error skips`() {
        assertTrue(
            shouldSkipIdenticalSearch(key, "Tarzan", SearchFilters(), SearchSort.DEFAULT, hasResults = true, hasError = false),
        )
    }

    @Test
    fun `a different query still searches`() {
        assertFalse(
            shouldSkipIdenticalSearch(key, "Salaar", SearchFilters(), SearchSort.DEFAULT, hasResults = true, hasError = false),
        )
    }

    @Test
    fun `a different filter still searches`() {
        assertFalse(
            shouldSkipIdenticalSearch(
                key, "Tarzan", SearchFilters().copy(type = "series"), SearchSort.DEFAULT,
                hasResults = true, hasError = false,
            ),
        )
    }

    @Test
    fun `a different sort still searches`() {
        assertFalse(
            shouldSkipIdenticalSearch(key, "Tarzan", SearchFilters(), SearchSort.MOST_SOURCES, hasResults = true, hasError = false),
        )
    }

    @Test
    fun `no results on screen still searches`() {
        assertFalse(
            shouldSkipIdenticalSearch(key, "Tarzan", SearchFilters(), SearchSort.DEFAULT, hasResults = false, hasError = false),
        )
    }

    @Test
    fun `an error on screen still searches`() {
        assertFalse(
            shouldSkipIdenticalSearch(key, "Tarzan", SearchFilters(), SearchSort.DEFAULT, hasResults = true, hasError = true),
        )
    }

    @Test
    fun `no completed search still searches`() {
        assertFalse(
            shouldSkipIdenticalSearch(null, "Tarzan", SearchFilters(), SearchSort.DEFAULT, hasResults = true, hasError = false),
        )
    }
}
