package com.raddstream.app.brand

import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.File
import java.io.FileInputStream
import java.util.Base64
import java.util.Properties

/**
 * TlsPinsTest — guards the HTTPS default and its certificate pins, read
 * straight from /brand.properties the way BrandDriftTest does: plain JUnit4
 * on the JVM, no Robolectric, no Android runtime, no generated classes.
 *
 * It fails when:
 *  1. the shipped default server stops being the HTTPS catalog (a plain-
 *     HTTP default would send sync keys, VIP passes and stream tokens in
 *     cleartext);
 *  2. the pin list loses a pin, gains a non-pin, or stops decoding to a
 *     32-byte SHA-256 digest — a pin that is not a digest pins nothing;
 *  3. the release cleartext switch is turned on for the default host, which
 *     would let a release build talk plain HTTP to the catalog again.
 */
class TlsPinsTest {

    private val repoRoot: File by lazy {
        var dir: File? = File("").absoluteFile
        while (dir != null) {
            if (File(dir, "brand.properties").isFile) return@lazy dir
            dir = dir.parentFile
        }
        error("brand.properties not found above ${File("").absolutePath}")
    }

    private val brandProps: Properties by lazy {
        Properties().apply { FileInputStream(File(repoRoot, "brand.properties")).use { load(it) } }
    }

    private fun brandValue(key: String): String = (brandProps.getProperty(key) ?: "").trim()

    @Test
    fun `the shipped default server is the HTTPS catalog`() {
        assertEquals(
            "https://raddstream.duckdns.org",
            brandValue("network.default_server_url"),
        )
    }

    @Test
    fun `the pin list is three SHA-256 digests for the chain`() {
        val pins = brandValue("network.tls_pins").split(',')
            .map { it.trim() }
            .filter { it.isNotEmpty() }
        assertEquals(
            "pin the chain (intermediate + two roots), never the leaf — " +
                "the leaf rotates every ~90 days",
            3, pins.size,
        )
        pins.forEach { pin ->
            val decoded = Base64.getDecoder().decode(pin)
            assertEquals(
                "a pin that is not a 32-byte SHA-256 digest pins nothing: $pin",
                32, decoded.size,
            )
        }
        assertEquals(
            "the leaf pin must never be shipped — it expires with the certificate",
            0, pins.count { it == "EcVs8e1e4kKs4UyLKPW/18vyfcNDhaxp25RHB74Hbgk=" },
        )
    }

    @Test
    fun `release cleartext stays off for the default host`() {
        assertEquals(
            "false",
            brandValue("network.release_cleartext_for_default_host").lowercase(),
        )
    }
}
