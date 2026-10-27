package com.raddstream.app.network

import com.raddstream.app.brand.Brand
import com.raddstream.app.data.ServerSettingsRepository
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Result of querying the unkillable gateway (Blogger deadman switch).
 */
data class DiscoveryResult(
    val primary: String?,
    val backups: List<String>,
    val verifiedWorkingUrl: String?,
)

/**
 * Dynamic Server Discovery — Unkillable Deadman Switch Fallback.
 *
 * If the configured node (or IP 92.4.95.252) becomes unreachable or changes,
 * this client queries the stealth Blogger gateway (https://rehan-radd.blogspot.com/),
 * parses the anti-search stealth meta tags (`radd-primary` and `radd-backup-*`),
 * verifies candidates by probing latency, and updates ServerSettingsRepository automatically.
 */
@Singleton
class DynamicServerDiscovery @Inject constructor(
    private val settingsRepository: ServerSettingsRepository,
) {
    companion object {
        private val META_CONTENT_FIRST_REGEX = Regex(
            """<meta\s+content=['"]([^'"]+)['"]\s+name=['"]radd-(primary|backup-[^'"]+)['"]""",
            RegexOption.IGNORE_CASE
        )
        private val META_NAME_FIRST_REGEX = Regex(
            """<meta\s+name=['"]radd-(primary|backup-[^'"]+)['"]\s+content=['"]([^'"]+)['"]""",
            RegexOption.IGNORE_CASE
        )

        /**
         * Parses raw HTML into primary and backup node lists without network calls.
         */
        fun parseHtmlNodes(rawHtml: String): Pair<String?, List<String>> {
            var primary: String? = null
            val backups = mutableListOf<String>()

            META_CONTENT_FIRST_REGEX.findAll(rawHtml).forEach { match ->
                val url = match.groupValues[1].trim()
                val type = match.groupValues[2].lowercase()
                if (type == "primary") {
                    if (primary == null) primary = url
                } else {
                    backups.add(url)
                }
            }

            META_NAME_FIRST_REGEX.findAll(rawHtml).forEach { match ->
                val type = match.groupValues[1].lowercase()
                val url = match.groupValues[2].trim()
                if (type == "primary") {
                    if (primary == null) primary = url
                } else {
                    backups.add(url)
                }
            }

            return Pair(primary, backups.distinct())
        }
    }

    /**
     * Discovers all nodes published on the stealth gateway.
     */
    suspend fun fetchPublishedNodes(gatewayUrl: String = Brand.gatewayDiscoveryUrl): DiscoveryResult = withContext(Dispatchers.IO) {
        val targetUrl = gatewayUrl.trim().ifBlank { "https://rehan-radd.blogspot.com/" }
        val rawHtml = try {
            val conn = (URL(targetUrl).openConnection() as HttpURLConnection).apply {
                connectTimeout = 6000
                readTimeout = 6000
                instanceFollowRedirects = true
                setRequestProperty("User-Agent", Brand.userAgent)
            }
            conn.inputStream.use { stream ->
                BufferedReader(InputStreamReader(stream)).readText()
            }
        } catch (_: Exception) {
            return@withContext DiscoveryResult(null, emptyList(), null)
        }

        val (primary, backups) = parseHtmlNodes(rawHtml)
        val candidates = listOfNotNull(primary) + backups
        var working: String? = null
        for (candidate in candidates) {
            if (probeNodeHealth(candidate)) {
                working = candidate
                break
            }
        }

        DiscoveryResult(primary, backups, working)
    }

    /**
     * Probes candidate node health by verifying /api/v1/posts or /setup check.
     */
    fun probeNodeHealth(serverUrl: String, timeoutMs: Int = 3000): Boolean {
        return try {
            val cleanUrl = serverUrl.trim().trimEnd('/')
            val testEndpoint = URL("$cleanUrl/api/v1/posts?limit=1")
            val conn = (testEndpoint.openConnection() as HttpURLConnection).apply {
                connectTimeout = timeoutMs
                readTimeout = timeoutMs
                instanceFollowRedirects = true
                requestMethod = "GET"
                setRequestProperty("User-Agent", Brand.userAgent)
            }
            conn.responseCode in 200..399
        } catch (_: Exception) {
            false
        }
    }

    /**
     * Automatic failover: probes gateway and saves working node if found.
     */
    suspend fun discoverAndPersistWorkingServer(): String? = withContext(Dispatchers.IO) {
        val result = fetchPublishedNodes()
        result.verifiedWorkingUrl?.let { working ->
            settingsRepository.saveServerUrl(working)
            working
        }
    }
}
