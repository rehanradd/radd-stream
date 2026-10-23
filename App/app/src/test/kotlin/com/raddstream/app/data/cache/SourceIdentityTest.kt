package com.raddstream.app.data.cache

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

class SourceIdentityTest {

    @Test
    fun `query params and rotating host do not change the path identity`() {
        val a = SourceIdentity.from(555L, "cdn_direct", "https://cdn-a.example/x/file.mp4?sig=1&exp=100")
        val b = SourceIdentity.from(555L, "cdn_direct", "https://cdn-b.example/x/file.mp4?sig=99&exp=999")
        assertEquals(SourceIdentity.normalizePath("https://cdn-a.example/x/file.mp4?sig=1"), "/x/file.mp4")
        assertEquals(a.key(), b.key())
        assertEquals(a.digestHex(), b.digestHex())
    }

    @Test
    fun `resource id wins over rotating path when present`() {
        val a = SourceIdentity.from(555L, "hls_manifest", "https://cdn/session-1/master.m3u8", resourceId = "RID-777")
        val b = SourceIdentity.from(555L, "hls_manifest", "https://cdn/session-2/whatever.m3u8", resourceId = "RID-777")
        assertEquals(a.key(), b.key())
    }

    @Test
    fun `different size under same release is a different identity`() {
        val a = SourceIdentity.from(9L, "cdn_direct", "https://c/f.mp4", expectedSizeBytes = 1000L)
        val b = SourceIdentity.from(9L, "cdn_direct", "https://c/f.mp4", expectedSizeBytes = 2000L)
        assertNotEquals(a.key(), b.key())
    }

    @Test
    fun `different release is a different identity even for same path`() {
        val a = SourceIdentity.from(1L, "cdn_direct", "https://c/f.mp4")
        val b = SourceIdentity.from(2L, "cdn_direct", "https://c/f.mp4")
        assertNotEquals(a.digestHex(), b.digestHex())
    }

    @Test
    fun `ephemeral source dies mid download - re-resolve adopts existing bytes`() {
        // First resolve: signed URL, we buffer [0, 420000).
        val firstUrl = "https://eph.example/vid/abc.mp4?token=AAA&exp=1"
        val identity1 = SourceIdentity.from(777L, "cdn_direct", firstUrl, expectedSizeBytes = 1_300_000L)
        val ledger = IntervalLedger().apply { add(0, 420_000) }
        val token = ResumeToken(identity1.digestHex(), 1_300_000L, 5L, ledger)

        // Mid-download the ephemeral URL rots. We re-resolve and get a NEW signed URL for the
        // SAME resource (same release, same path, same size) — different token only.
        val reResolvedUrl = "https://eph.example/vid/abc.mp4?token=BBB&exp=2"
        val identity2 = SourceIdentity.from(777L, "cdn_direct", reResolvedUrl, expectedSizeBytes = 1_300_000L)

        assertEquals(identity1.digestHex(), identity2.digestHex())

        // Resume against the new identity: adopt the 420000 already held, fetch only the tail.
        val ranges = ResumeToken.resumeRanges(token, expectedDigest = identity2.digestHex())
        assertEquals(listOf(ByteInterval(420_000, 1_300_000)), ranges)
        assertEquals(420_000L, ranges.first().start)
    }

    @Test
    fun `re-resolve to a DIFFERENT resource never adopts the old bytes`() {
        val identity1 = SourceIdentity.from(777L, "cdn_direct", "https://e/old.mp4", expectedSizeBytes = 1_000L)
        val ledger = IntervalLedger().apply { add(0, 500) }
        val token = ResumeToken(identity1.digestHex(), 1_000L, 1L, ledger)

        // Release differs -> different digest -> we must re-fetch from zero, not reuse.
        val identity2 = SourceIdentity.from(888L, "cdn_direct", "https://e/old.mp4", expectedSizeBytes = 1_000L)
        val ranges = ResumeToken.resumeRanges(token, expectedDigest = identity2.digestHex())
        assertEquals(listOf(ByteInterval(0, 1_000)), ranges)
    }

    @Test
    fun `pathless url normalizes to root and digest is stable`() {
        val a = SourceIdentity.from(1L, "cdn_direct", "https://host/")
        val b = SourceIdentity.from(1L, "cdn_direct", "https://host")
        assertEquals(a.normalizedPath, "/")
        assertEquals(a.digestHex(), b.digestHex())
    }
}
