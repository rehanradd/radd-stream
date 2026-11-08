package com.raddstream.app.share

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pure JVM coverage of the LAN share protocol — no Robolectric, no sockets. Every decision
 * the real server makes is decided here first, which is the entire reason the protocol was
 * split out of [LanShareServer].
 */
class LanShareProtocolTest {

    private val size = 5_000L

    private val catalog = mapOf(
        "tok1" to ShareEntry("video.mkv", size, "video/x-matroska", enabled = true),
        "off" to ShareEntry("hidden.mkv", size, "video/x-matroska", enabled = false),
        // Named like traversal bait on purpose: even when an entry matches the leaf name,
        // a hostile *path* must not be allowed to select it.
        "passwd" to ShareEntry("passwd.mkv", size, "video/x-matroska", enabled = true),
    )

    private fun get(path: String, range: String? = null, method: String = "GET"): ShareResponse =
        LanShareProtocol.respond(
            method = method,
            path = path,
            headers = if (range == null) emptyMap() else mapOf("Range" to range),
            catalog = catalog,
        )

    @Test
    fun `full file answers 200 with length type and accept-ranges`() {
        val r = get("/tok1")
        assertEquals(200, r.status)
        assertEquals(size.toString(), r.headers["Content-Length"])
        assertEquals("video/x-matroska", r.headers["Content-Type"])
        assertEquals("bytes", r.headers["Accept-Ranges"])
        assertEquals(0L, r.bodyStart)
        assertEquals(size, r.bodyLength)
    }

    @Test
    fun `explicit first 500 bytes answers 206 with exact span`() {
        val r = get("/tok1", range = "bytes=0-499")
        assertEquals(206, r.status)
        assertEquals("bytes 0-499/$size", r.headers["Content-Range"])
        assertEquals("500", r.headers["Content-Length"])
        assertEquals(0L, r.bodyStart)
        assertEquals(500L, r.bodyLength)
    }

    @Test
    fun `open ended range runs to the last byte`() {
        val r = get("/tok1", range = "bytes=1000-")
        assertEquals(206, r.status)
        assertEquals("bytes 1000-4999/$size", r.headers["Content-Range"])
        assertEquals("4000", r.headers["Content-Length"])
        assertEquals(1000L, r.bodyStart)
        assertEquals(4000L, r.bodyLength)
    }

    @Test
    fun `suffix range returns the final N bytes`() {
        val r = get("/tok1", range = "bytes=-500")
        assertEquals(206, r.status)
        assertEquals("bytes 4500-4999/$size", r.headers["Content-Range"])
        assertEquals("500", r.headers["Content-Length"])
        assertEquals(4500L, r.bodyStart)
    }

    @Test
    fun `range ending past the file is clamped not rejected`() {
        val r = get("/tok1", range = "bytes=4000-999999")
        assertEquals(206, r.status)
        assertEquals("bytes 4000-4999/$size", r.headers["Content-Range"])
        assertEquals("1000", r.headers["Content-Length"])
    }

    @Test
    fun `unsatisfiable range answers 400 with star content-range`() {
        val r = get("/tok1", range = "bytes=9000-12000")
        assertEquals(400, r.status)
        assertEquals("*/$size", r.headers["Content-Range"])
        assertEquals(0L, r.bodyLength)
    }

    @Test
    fun `malformed range answers 400`() {
        assertEquals(400, get("/tok1", range = "bytes=abc-").status)
        assertEquals(400, get("/tok1", range = "bytes=500-100").status)
        assertNull(LanShareProtocol.parseRange("items=0-1", size))
        assertNull(LanShareProtocol.parseRange("bytes=", size))
    }

    @Test
    fun `unknown token answers 404`() {
        val r = get("/nope")
        assertEquals(404, r.status)
        assertEquals(0L, r.bodyLength)
    }

    @Test
    fun `post is refused with allow header`() {
        val r = get("/tok1", method = "POST")
        assertEquals(405, r.status)
        assertEquals("GET, HEAD", r.headers["Allow"])
    }

    @Test
    fun `disabled share answers 403`() {
        val r = get("/off")
        assertEquals(403, r.status)
        assertEquals(0L, r.bodyLength)
    }

    @Test
    fun `head declares length but asks for no body`() {
        val r = get("/tok1", method = "HEAD")
        assertEquals(200, r.status)
        assertEquals(size.toString(), r.headers["Content-Length"])
        assertEquals(0L, r.bodyLength)
        val partial = get("/tok1", range = "bytes=0-99", method = "HEAD")
        assertEquals(206, partial.status)
        assertEquals(0L, partial.bodyLength)
    }

    @Test
    fun `traversal path cannot select any catalog file`() {
        // Same shape the task requires the server to survive: dot-dot segments reaching for
        // /etc/passwd. Token lookup misses (or, for the /passwd variants, the path is not a
        // single clean segment) and the request dies as a 404 before any file is opened.
        for (evil in listOf("/../../etc/passwd", "/..%2f..%2fetc/passwd", "/tok1/../../x")) {
            val r = get(evil)
            assertEquals("traversal must not serve: $evil", 404, r.status)
            assertEquals(0L, r.bodyLength)
            assertFalse(r.isOk)
        }
    }

    @Test
    fun `oversized header block is rejected`() {
        val huge = mapOf("X-Pad" to "A".repeat(LanShareProtocol.MAX_HEADER_BYTES + 100))
        val r = LanShareProtocol.respond("GET", "/tok1", huge, catalog)
        assertEquals(431, r.status)
        assertEquals(0L, r.bodyLength)
        val ok = LanShareProtocol.respond("GET", "/tok1", mapOf("Range" to "bytes=0-10"), catalog)
        assertTrue(LanShareProtocol.headerBlockBytes("GET", "/tok1", mapOf("Range" to "bytes=0-10"))
            <= LanShareProtocol.MAX_HEADER_BYTES)
        assertEquals(206, ok.status)
    }

    @Test
    fun `share url exposes only our address and token never an upstream source`() {
        val url = LanShareProtocol.shareUrl("192.168.1.42", 8990, "tok1")
        assertEquals("http://192.168.1.42:8990/tok1", url)
        assertFalse(url.contains("video.mkv"))
        // A host field that smuggles anything beyond a bare address (an upstream URL, say)
        // is rejected outright instead of producing a leaking link.
        runCatching { LanShareProtocol.shareUrl("cdn.example.com/base.mp4", 8990, "tok1") }
            .onFailure { assertTrue(it is IllegalArgumentException) }
        runCatching { LanShareProtocol.shareUrl("192.168.1.42", 8990, "a b") }
            .onFailure { assertTrue(it is IllegalArgumentException) }
    }

    // ── per-start session token (security fixes, 2026-11-08) ─────────────

    private val session = "0123456789abcdef0123456789abcdef"

    private fun getWithSession(path: String, proved: String? = session): ShareResponse =
        LanShareProtocol.respond(
            method = "GET",
            path = if (proved == null) path else "$path?token=$proved",
            headers = emptyMap(),
            catalog = catalog,
            sessionToken = session,
        )

    @Test
    fun `a request without the session token is refused`() {
        val r = getWithSession("/tok1", proved = null)
        assertEquals(403, r.status)
        assertEquals(0L, r.bodyLength)
    }

    @Test
    fun `a wrong session token is refused without saying which file exists`() {
        assertEquals(403, getWithSession("/tok1", proved = "deadbeef").status)
        // Unknown file + wrong session is still 403: the session check runs before
        // the file lookup, so a wrong session never learns whether a file exists.
        assertEquals(403, getWithSession("/nope", proved = "deadbeef").status)
        assertEquals(404, getWithSession("/nope").status)
    }

    @Test
    fun `the right session token serves the file`() {
        val r = getWithSession("/tok1")
        assertEquals(200, r.status)
        assertEquals(size, r.bodyLength)
    }

    @Test
    fun `minted session tokens are 128 bit hex and never repeat`() {
        val first = LanShareProtocol.generateSessionToken()
        val second = LanShareProtocol.generateSessionToken()
        assertEquals(2 * LanShareProtocol.SESSION_TOKEN_BYTES, first.length)
        assertTrue(first.all { it in '0'..'9' || it in 'a'..'f' })
        assertTrue(first != second)
    }

    @Test
    fun `share url carries the session token when one exists`() {
        val url = LanShareProtocol.shareUrl("192.168.1.42", 8990, "tok1", session)
        assertEquals("http://192.168.1.42:8990/tok1?token=$session", url)
        assertEquals(
            "http://192.168.1.42:8990/tok1",
            LanShareProtocol.shareUrl("192.168.1.42", 8990, "tok1"),
        )
    }
}
