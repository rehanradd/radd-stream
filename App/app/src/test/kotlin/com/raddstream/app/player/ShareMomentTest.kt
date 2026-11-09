package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** JVM tests for [ShareMoment] (SC.24): the shared text carries title, time, link. */
class ShareMomentTest {

    @Test
    fun `share text names the title, the timestamp and the deep link`() {
        val text = ShareMoment.shareText("Nashtar", 754_000L, "radd://stream/abc/Nashtar")
        assertEquals("Nashtar — 12:34\nradd://stream/abc/Nashtar", text)
    }

    @Test
    fun `a negative position is shared as zero, never a minus time`() {
        val text = ShareMoment.shareText("Nashtar", -500L, "radd://stream/abc/Nashtar")
        assertTrue(text.contains("0:00"))
    }

    @Test
    fun `a blank title still shares a readable sentence`() {
        val text = ShareMoment.shareText("   ", 0L, "radd://stream/abc/x")
        assertTrue(text.startsWith("this moment — 0:00\n"))
    }
}
