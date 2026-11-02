package com.raddstream.app.network

import java.net.ConnectException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
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

    @Test
    fun `rejects a fragment`() {
        assertThrows(IllegalArgumentException::class.java) {
            normalizeServerUrl("https://api.example.test#section")
        }
    }

    // ── HTTPS primary, plain-HTTP fallback ─────────────────────────────────────
    //
    // The two brand addresses as the shipping brand file spells them. A test that typed
    // "https://primary.test" here would pass whatever the brand said, including a build that
    // still ships plain HTTP as its default, so the assertions below read the file the APK is
    // built from and then use those values.
    private val brandPrimary: String by lazy { brandValue("network.default_server_url") }
    private val brandFallback: String by lazy { brandValue("network.fallback_server_url") }

    @Test
    fun `the brand ships a TLS default and a plain-HTTP fallback of the same box`() {
        assertTrue(
            "network.default_server_url must be TLS, found '$brandPrimary'",
            brandPrimary.startsWith("https://"),
        )
        assertEquals("http://92.4.95.252", brandFallback)
        assertEquals(
            "the release cleartext switch must stay off now that the default is TLS",
            "false", brandValue("network.release_cleartext_for_default_host"),
        )
    }

    @Test
    fun `a fresh install lists TLS first and the plain address second`() {
        assertEquals(
            listOf(brandPrimary, brandFallback),
            serverCandidates(savedUrl = null, defaultUrl = brandPrimary, fallbackUrl = brandFallback),
        )
    }

    @Test
    fun `an install that saved the old plain address tries TLS before it`() {
        // The saved value is the PREVIOUS shipped default, not a choice to be on HTTP.
        val candidates = serverCandidates(
            savedUrl = "http://92.4.95.252",
            defaultUrl = brandPrimary,
            fallbackUrl = brandFallback,
        )
        assertEquals(listOf(brandPrimary, "http://92.4.95.252"), candidates)
    }

    @Test
    fun `a server the viewer chose for themselves never gains our fallback`() {
        assertEquals(
            listOf("https://their-catalog.example/"),
            serverCandidates(
                savedUrl = "https://their-catalog.example/",
                defaultUrl = brandPrimary,
                fallbackUrl = brandFallback,
            ),
        )
    }

    @Test
    fun `no fallback key means one candidate and the old behaviour`() {
        assertEquals(
            listOf(brandPrimary),
            serverCandidates(savedUrl = null, defaultUrl = brandPrimary, fallbackUrl = ""),
        )
    }

    @Test
    fun `the fallback is probed only after the primary fails, and never before`() {
        val asked = mutableListOf<String>()
        val probe = { url: String -> asked.add(url); false }
        assertThrows(ConnectException::class.java) {
            chooseSessionServer(null, brandPrimary, brandFallback, probe)
        }
        assertEquals(listOf(brandPrimary, brandFallback), asked)

        val afterPrimaryWorked = mutableListOf<String>()
        val working = chooseSessionServer(null, brandPrimary, brandFallback) { url ->
            afterPrimaryWorked.add(url); url == brandPrimary
        }
        assertEquals(brandPrimary, working)
        assertEquals(
            "a primary that answers must not cost the viewer a second probe",
            listOf(brandPrimary), afterPrimaryWorked,
        )
    }

    @Test
    fun `the fallback answers for the session when TLS does not`() {
        val chosen = chooseSessionServer(null, brandPrimary, brandFallback) { url ->
            url == brandFallback
        }
        assertEquals(brandFallback, chosen)
    }

    @Test
    fun `nothing answering says so in plain words and names no address`() {
        val failure = assertThrows(ConnectException::class.java) {
            chooseSessionServer(null, brandPrimary, brandFallback) { false }
        }
        val shown = friendlyNetworkError(failure, "Could not reach the catalog.", debugBuild = true)
        assertEquals(
            "The server didn't answer. It may be offline — try again in a moment. " +
                "(No configured server answered)",
            shown,
        )
        for (leak in listOf("92.4.95.252", "raddstream", "duckdns", "http")) {
            assertFalse("the sentence a viewer sees must not quote '$leak'", shown.contains(leak))
        }
    }

    @Test
    fun `nothing configured at all still routes to Setup rather than a transport error`() {
        assertThrows(IllegalStateException::class.java) {
            chooseSessionServer(savedUrl = null, defaultUrl = "", fallbackUrl = "") { true }
        }
    }

    private fun brandValue(key: String): String {
        val properties = java.util.Properties()
        java.io.FileInputStream(brandFile()).use { properties.load(it) }
        return (properties.getProperty(key) ?: "").trim()
    }

    /**
     * The brand file the APK is actually built from, found the way every other source-reading test
     * in this module finds it — walking up from the working directory rather than assuming it, so
     * the assertions still read the real file if Gradle ever changes where unit tests run.
     */
    private fun brandFile(): java.io.File {
        var dir: java.io.File? = java.io.File("").absoluteFile
        while (dir != null) {
            val candidate = java.io.File(dir, "brand.properties")
            if (candidate.isFile) return candidate
            dir = dir.parentFile
        }
        throw AssertionError("brand.properties not found above ${java.io.File("").absolutePath}")
    }
}
