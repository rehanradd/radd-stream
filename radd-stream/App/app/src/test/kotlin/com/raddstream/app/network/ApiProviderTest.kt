package com.raddstream.app.network

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
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
}
