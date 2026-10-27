package com.raddstream.app.network.models

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * `WireText.listOf` is the only reader for the three v1 columns that are TEXT but hold a
 * list, so every presentation surface (genres chips, language pills, backdrop art) stands
 * or falls on it. These cases are the wire shapes verified against the live ledger, plus
 * the one that a self-referencing `listOf` call used to turn into a StackOverflowError on
 * any value that was not a JSON array.
 */
class WireTextTest {

    @Test
    fun readsCsvColumns() {
        assertEquals(
            listOf("Action", "Adventure", "Drama", "Fantasy"),
            WireText.listOf("Action, Adventure, Drama, Fantasy"),
        )
        assertEquals(listOf("Drama"), WireText.listOf("Drama"))
    }

    @Test
    fun readsTheOtherSeparatorsTheScrapersLeaveBehind() {
        assertEquals(listOf("Hindi", "English", "Japanese"), WireText.listOf("Hindi + English + Japanese"))
        assertEquals(listOf("Tamil", "Telugu"), WireText.listOf("Tamil / Telugu"))
        assertEquals(listOf("A", "B"), WireText.listOf("A;B"))
        assertEquals(listOf("A", "B"), WireText.listOf("A|B"))
    }

    @Test
    fun readsJsonArrayStringsAndBareUrls() {
        assertEquals(
            listOf("https://a.jpg", "https://b.jpg"),
            WireText.listOf("[\"https://a.jpg\", \"https://b.jpg\"]"),
        )
        assertEquals(listOf("https://a.jpg"), WireText.listOf("https://a.jpg"))
        // A half-written array still has to read as items, not as one broken string.
        assertEquals(listOf("Action", "Drama"), WireText.listOf("[Action, Drama"))
        assertEquals(listOf("Sci-Fi", "Noir"), WireText.listOf("Sci-Fi / Noir"))
    }

    @Test
    fun answersAnEmptyListForNothingAndForMalformedJson() {
        assertTrue(WireText.listOf(null).isEmpty())
        assertTrue(WireText.listOf("").isEmpty())
        assertTrue(WireText.listOf("   ").isEmpty())
        assertTrue(WireText.listOf("[]").isEmpty())
        assertTrue(WireText.listOf("[null]").isEmpty())
        assertEquals(listOf("a", "b"), WireText.listOf("[\"a\", \"\", \"b\"]"))
    }

    @Test
    fun dropsBlanksAndDuplicatesFromAnyShape() {
        assertEquals(listOf("English", "Hindi"), WireText.listOf("English,,  , Hindi, English"))
    }

    @Test
    fun splitOnAnySplitsEveryGivenSeparatorAtOnce() {
        assertEquals(listOf("a", "b", "c", "d"), WireText.splitOnAny("a,b c;d", ",", " ", ";"))
        assertTrue(WireText.splitOnAny(null, ",").isEmpty())
        assertTrue(WireText.splitOnAny("  ", ",").isEmpty())
    }
}
