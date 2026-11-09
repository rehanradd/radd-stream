package com.raddstream.app.ui.navigation

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** DeepLinks is the one owner of deep-link URIs: build and parse must agree. */
class DeepLinksTest {

    @Test
    fun `detail link builds under the brand scheme and parses back`() {
        val uri = DeepLinks.detailUri(42)
        assertEquals(DeepLink.Detail(42), DeepLinks.parse(uri))
    }

    @Test
    fun `stream link round-trips a handle and a title with spaces`() {
        val uri = DeepLinks.streamUri("s-abc123", "Avengers Endgame")
        assertEquals(DeepLink.Stream("s-abc123", "Avengers Endgame"), DeepLinks.parse(uri))
    }

    @Test
    fun `browse link parses its type`() {
        assertEquals(DeepLink.Browse("series"), DeepLinks.parse(DeepLinks.browseUri("series")))
    }

    @Test
    fun `an unknown path parses to nothing`() {
        assertNull(DeepLinks.parse("radd://settings"))
    }

    @Test
    fun `a stream link missing its title parses to nothing`() {
        // NAV-5: a half-formed share is a dead link, not a player with no title.
        assertNull(DeepLinks.parse("radd://stream/s-abc123"))
    }

    @Test
    fun `a bare scheme parses to nothing`() {
        assertNull(DeepLinks.parse("radd://"))
    }

    @Test
    fun `a detail link with a non-numeric id parses to nothing`() {
        assertNull(DeepLinks.parse("radd://detail/abc"))
    }

    @Test
    fun `a foreign scheme parses to nothing`() {
        assertNull(DeepLinks.parse("https://example.com/detail/42"))
    }
}
