package com.raddstream.app.tooling

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Two facts about the HTTPS-primary / HTTP-fallback work that the compiler cannot see and a
 * behaviour test here cannot reach, so they are answered at the source and at the built config.
 *
 * 1. **A fallback must never become the saved server.** `chooseSessionServer` is a function from
 *    values to a value, and the file that calls it is not allowed to hold a writer. This is a scan
 *    because there is no fake repository in this module — no mocking library is installed — and a
 *    Robolectric test that ran the real DataStore would still need a socket to fail. What the scan
 *    can prove is the thing that actually matters: the code path has no way to persist.
 * 2. **The one cleartext exception in a release build is named, not global.** The policy is
 *    generated into `build/` from `/brand.properties` by `:app:generateBrandAssets`, so the
 *    generated file — the bytes that ship — is what gets read, not the brand key that supposedly
 *    produced it.
 *
 * Both carry positive controls, because a scan whose marker moved or whose regex matches nothing is
 * green by accident: the retired-persistence and the wrong-host cases are asserted to be caught.
 */
class SessionFallbackGuardTest {

    private val repoRoot: File by lazy {
        var dir: File? = File("").absoluteFile
        while (dir != null) {
            if (File(dir, "brand.properties").isFile) return@lazy dir
            dir = dir.parentFile
        }
        error("brand.properties not found above ${File("").absolutePath}")
    }

    private val provider = source("network", "ApiProvider.kt")
    private val discovery = source("network", "DynamicServerDiscovery.kt")

    /** 1: the session decision reads the store and never writes it. */
    @Test
    fun `the session fallback has no way to save itself as the user's server`() {
        for (writer in listOf("saveServerUrl", "dataStore.edit", "preferences[")) {
            assertFalse(
                "ApiProvider.kt must not write the saved server — a session fallback that " +
                    "persists would silently retire TLS on every future launch ($writer)",
                provider.contains(writer),
            )
        }
        // Positive control: the marker is real. The discovery path DOES persist a working node,
        // so if this file ever stopped containing it, the scan above would be proving nothing.
        assertTrue(
            "DynamicServerDiscovery.kt is expected to call saveServerUrl; if it no longer does, " +
                "the control above is vacuous",
            discovery.contains("saveServerUrl"),
        )
    }

    /** 2: the shipped release policy. */
    @Test
    fun `the release network policy names the fallback host and nothing wider`() {
        val policy = generatedPolicy()
        val domains = DOMAIN_REGEX.findAll(policy).map { it.groupValues[1].trim() }.toList()

        assertEquals(
            "loopback, plus exactly the brand's plain-HTTP fallback host",
            listOf("10.0.2.2", "127.0.0.1", "92.4.95.252", "localhost"),
            domains.sorted(),
        )
        assertFalse("a wildcard domain would be a global cleartext switch", domains.any { it.contains("*") })
        assertFalse(
            "the TLS default must not be added to the cleartext list while " +
                "network.release_cleartext_for_default_host is false",
            domains.any { it.contains("duckdns") || it.contains("raddstream") },
        )
        assertFalse(
            "a base-config exception permits cleartext everywhere, which is the thing this file " +
                "exists to refuse",
            Regex("base-config[^>]*cleartextTrafficPermitted\\s*=\\s*\"true\"").containsMatchIn(policy),
        )
        assertEquals(
            "every permitted host is named exactly, never as a parent domain",
            domains.size,
            Regex("includeSubdomains\\s*=\\s*\"false\"").findAll(policy).count(),
        )
    }

    /**
     * Positive control for the read above: a policy that DID open cleartext globally or add the
     * default host must be refused by the same checks, so the assertions are not passing because
     * the file is empty or the patterns are wrong.
     */
    @Test
    fun `the same checks refuse a policy that went global`() {
        val widened = """
            <network-security-config>
                <base-config cleartextTrafficPermitted="true" />
                <domain-config cleartextTrafficPermitted="true">
                    <domain includeSubdomains="true">*</domain>
                    <domain includeSubdomains="true">raddstream.duckdns.org</domain>
                </domain-config>
            </network-security-config>
        """.trimIndent()
        assertTrue(
            Regex("base-config[^>]*cleartextTrafficPermitted\\s*=\\s*\"true\"").containsMatchIn(widened),
        )
        val wildcarded = DOMAIN_REGEX.findAll(widened).map { it.groupValues[1].trim() }.toList()
        assertTrue(wildcarded.contains("*"))
        assertEquals(0, Regex("includeSubdomains\\s*=\\s*\"false\"").findAll(widened).count())
    }

    private fun generatedPolicy(): String {
        val file = File(repoRoot, "App/app/build/generated/res/brand/xml/network_security_config.xml")
        assertTrue(
            "${file.absolutePath} is missing — run :app:generateBrandAssets (any build does). " +
                "This test reads the config that actually ships, so it cannot fall back to the " +
                "brand key that produced it.",
            file.isFile,
        )
        return file.readText()
    }

    private fun source(vararg path: String): String {
        val relative = (listOf("App", "app", "src", "main", "kotlin", "com", "raddstream", "app") +
            path.toList()).joinToString("/")
        val file = File(repoRoot, relative)
        assertTrue("${file.path} is gone — this guard has been looking at nothing", file.isFile)
        return file.readText()
    }

    private companion object {
        val DOMAIN_REGEX = Regex("<domain[^>]*>([^<]*)</domain>")
    }
}
