package com.raddstream.app.network

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class ApiProviderTest {
    @Test
    fun `normalizes scheme and appends trailing slash`() {
        assertEquals(
            "https://api.example.test:8080/radd/",
            normalizeServerUrl(" HTTPS://api.example.test:8080/radd "),
        )
    }

    @Test
    fun `preserves a root server URL`() {
        assertEquals("http://192.168.1.5:8080/", normalizeServerUrl("http://192.168.1.5:8080"))
    }

    @Test
    fun `rejects unsupported schemes`() {
        assertThrows(IllegalArgumentException::class.java) {
            normalizeServerUrl("ftp://api.example.test")
        }
    }

    @Test
    fun `rejects a URL without a host`() {
        assertThrows(IllegalArgumentException::class.java) {
            normalizeServerUrl("https:///catalog")
        }
    }

    @Test
    fun `rejects embedded credentials and query strings`() {
        assertThrows(IllegalArgumentException::class.java) {
            normalizeServerUrl("https://user:pass@api.example.test")
        }
        assertThrows(IllegalArgumentException::class.java) {
            normalizeServerUrl("https://api.example.test?token=value")
        }
    }

    // ── certificate pinning ──────────────────────────────────────────────
    private val pins = listOf(
        "s/tdAOmUzd8syaTuqfgGvFcn6DzA5Cmb+Vby1ST+U3Y=",
        "sCkq5UWXjg+7mKu9lMhhYF5bGLsy7VI/UNW3tccdR7w=",
        "diGVwiVYbubAI3RW4hB9xU8e/CH2GnkuvVFZE8zmgzI=",
    )

    @Test
    fun `pins apply to the default host only`() {
        val pinner = certificatePinnerFor(
            "https://raddstream.duckdns.org", "raddstream.duckdns.org", pins,
        )
        assertEquals(3, pinner?.pins?.size)
        assertTrue(pinner?.pins?.all { it.pattern == "raddstream.duckdns.org" } == true)
    }

    @Test
    fun `pins do not apply to a user-chosen server`() {
        assertEquals(
            null,
            certificatePinnerFor(
                "https://my-own-catalog.example", "raddstream.duckdns.org", pins,
            ),
        )
    }

    @Test
    fun `no pins means no pinner`() {
        assertEquals(
            null,
            certificatePinnerFor(
                "https://raddstream.duckdns.org", "raddstream.duckdns.org", emptyList(),
            ),
        )
    }

    @Test
    fun `no default host means no pinner`() {
        assertEquals(
            null,
            certificatePinnerFor("https://raddstream.duckdns.org", null, pins),
        )
    }

    @Test
    fun `a malformed pin fails at build time`() {
        assertThrows(IllegalArgumentException::class.java) {
            certificatePinnerFor(
                "https://raddstream.duckdns.org", "raddstream.duckdns.org",
                listOf("not-a-pin"),
            )
        }
    }

    @Test
    fun `a vip pass appends to a redirector url and nothing without one`() {
        val url = streamRedirectUrl("http://92.4.95.252", "tok1")
        assertEquals(
            "http://92.4.95.252/api/v1/stream?id=tok1&vip=ABC123",
            withVipPass(url, "ABC123"),
        )
        assertEquals(url, withVipPass(url, null))
        assertEquals(url, withVipPass(url, "   "))
    }

    @Test
    fun `a vip pass starts the query on a url without one`() {
        assertEquals(
            "http://92.4.95.252/api/v1/download?vip=ABC123",
            withVipPass("http://92.4.95.252/api/v1/download", "ABC123"),
        )
    }
}
