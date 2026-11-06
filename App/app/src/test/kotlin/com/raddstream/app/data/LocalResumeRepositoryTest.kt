package com.raddstream.app.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class LocalResumeRepositoryTest {

    @Test
    fun keyIsStablePerUriAndDistinctPerFile() {
        val key = localResumeKey("content://media/external/video/media/42")
        assertTrue(key.startsWith("local_resume_"))
        assertEquals(key, localResumeKey("content://media/external/video/media/42"))
        assertFalse(key == localResumeKey("content://media/external/video/media/43"))
    }

    @Test
    fun sha256MatchesTheKnownVector() {
        assertEquals(
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            sha256Hex("abc"),
        )
    }

    @Test
    fun formatAndParseRoundTrip() {
        val stored = formatLocalResume(123_456L, 1_700_000_000_000L)
        assertEquals(123_456L, parseLocalResume(stored))
        assertEquals(1_700_000_000_000L, parseLocalResumeUpdatedAt(stored))
    }

    @Test
    fun parseRejectsMissingAndMalformedValues() {
        assertNull(parseLocalResume(null))
        assertNull(parseLocalResume(""))
        assertNull(parseLocalResume("abc"))
        assertNull(parseLocalResume("0|123"))
        assertNull(parseLocalResume("-5|123"))
        assertNull(parseLocalResumeUpdatedAt(null))
        assertNull(parseLocalResumeUpdatedAt("123456"))
    }

    @Test
    fun pruneKeepsOnlyTheNewestEntries() {
        val entries = mapOf(
            "local_resume_a" to formatLocalResume(1L, 100L),
            "local_resume_b" to formatLocalResume(1L, 200L),
            "local_resume_c" to formatLocalResume(1L, 300L),
        )
        assertEquals(setOf("local_resume_a"), localResumeKeysToPrune(entries, keep = 2))
        assertEquals(emptySet<String>(), localResumeKeysToPrune(entries, keep = 3))
        assertEquals(emptySet<String>(), localResumeKeysToPrune(entries, keep = 100))
    }

    @Test
    fun pruneTreatsAnUnreadableWriteTimeAsOldest() {
        val entries = mapOf(
            "local_resume_a" to "broken",
            "local_resume_b" to formatLocalResume(1L, 200L),
        )
        assertEquals(setOf("local_resume_a"), localResumeKeysToPrune(entries, keep = 1))
    }

    @Test
    fun onlyDeviceAddressesCountAsLocalResumeKeys() {
        assertTrue(isLocalResumeUri("content://media/external/video/media/42"))
        assertTrue(isLocalResumeUri("file:///storage/emulated/0/Movies/clip.mp4"))
        assertFalse(isLocalResumeUri("direct-123e4567-e89b-12d3-a456-426614174000"))
        assertFalse(isLocalResumeUri("radd://detail/42"))
        assertFalse(isLocalResumeUri(""))
    }
}
