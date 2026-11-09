package com.raddstream.app.images

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Phase 7 (M4): the art-URL gate — which hosts Coil may fetch directly.
 * The server already vets catalog art through `/api/v1/art`, so this is the
 * client-side second lock: a scraped-site host must never learn a viewer
 * opened a title, while our own server, the public CDNs and neutral upload
 * hosts keep loading.
 */
class ArtUrlPolicyTest {

    private val serverHost = "raddstream.duckdns.org"

    @Test
    fun `our own server art-ref is allowed`() {
        assertTrue(
            ArtUrlPolicy.isAllowed(
                "https://raddstream.duckdns.org/api/v1/art?id=abc&k=poster&n=0",
                serverHost,
            ),
        )
    }

    @Test
    fun `a public CDN poster is allowed`() {
        assertTrue(ArtUrlPolicy.isAllowed("https://image.tmdb.org/t/p/w500/abc.jpg", serverHost))
        assertTrue(ArtUrlPolicy.isAllowed("https://m.media-amazon.com/images/abc.jpg", serverHost))
    }

    @Test
    fun `a scraped-site host is blocked`() {
        assertFalse(ArtUrlPolicy.isAllowed("https://hindilinks4u.example/poster.jpg", serverHost))
        assertFalse(ArtUrlPolicy.isAllowed("https://some-random-host.net/img.png", serverHost))
    }

    @Test
    fun `a neutral upload host is allowed`() {
        assertTrue(ArtUrlPolicy.isAllowed("https://i.imgur.com/abc.jpg", serverHost))
        assertTrue(ArtUrlPolicy.isAllowed("https://iili.io/abc.jpg", serverHost))
        assertTrue(ArtUrlPolicy.isAllowed("https://lh3.googleusercontent.com/abc.jpg", serverHost))
    }

    @Test
    fun `relative and garbage urls are never allowed`() {
        assertFalse(ArtUrlPolicy.isAllowed("/api/v1/art?id=abc", serverHost))
        assertFalse(ArtUrlPolicy.isAllowed("poster.jpg", serverHost))
        assertFalse(ArtUrlPolicy.isAllowed(null, serverHost))
        assertFalse(ArtUrlPolicy.isAllowed("", serverHost))
        assertFalse(ArtUrlPolicy.isAllowed("not a url at all", serverHost))
    }

    @Test
    fun `non-http schemes are never allowed`() {
        assertFalse(ArtUrlPolicy.isAllowed("javascript:alert(1)", serverHost))
        assertFalse(ArtUrlPolicy.isAllowed("ftp://image.tmdb.org/abc.jpg", serverHost))
        assertFalse(ArtUrlPolicy.isAllowed("file:///etc/passwd", serverHost))
    }

    @Test
    fun `an unknown host fails open only while the server host is still loading`() {
        assertTrue(ArtUrlPolicy.isAllowed("https://hindilinks4u.example/poster.jpg", null))
        assertFalse(ArtUrlPolicy.isAllowed("https://hindilinks4u.example/poster.jpg", serverHost))
    }

    @Test
    fun `hostOf reads the configured server host`() {
        assertEquals("raddstream.duckdns.org", ArtUrlPolicy.hostOf("https://raddstream.duckdns.org"))
        assertEquals("92.4.95.252", ArtUrlPolicy.hostOf("http://92.4.95.252:8080"))
        assertNull(ArtUrlPolicy.hostOf(null))
        assertNull(ArtUrlPolicy.hostOf(""))
    }
}
