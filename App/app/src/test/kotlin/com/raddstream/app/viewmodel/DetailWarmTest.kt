package com.raddstream.app.viewmodel

import com.raddstream.app.data.UserRegion
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Audit #1 — the detail load warms the auto tier (`?warm=1`) and names the
 * viewer's preferred audio, so the Play press answers from the resolved
 * cache and the ladder leads with their language. The audio word is the
 * region card's own promise: a region with no stance sends nothing.
 */
class DetailWarmTest {

    @Test
    fun `desi region warms with Hindi`() {
        assertEquals("Hindi", detailWarmAudio(UserRegion.DESI_DUBS))
    }

    @Test
    fun `east asian region sends no audio word`() {
        assertNull(detailWarmAudio(UserRegion.EAST_ASIAN))
    }

    @Test
    fun `international region warms with English`() {
        assertEquals("English", detailWarmAudio(UserRegion.INTERNATIONAL))
    }

    @Test
    fun `unknown region falls back to the default card`() {
        assertEquals("Hindi", detailWarmAudio("nowhere"))
    }
}
