package com.raddstream.app.network

import com.google.gson.Gson
import com.raddstream.app.data.ServerSettingsRepository
import java.net.URI
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.util.Locale
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.first
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory

/**
 * Builds (and caches) the Retrofit client for the server the user picked.
 *
 * WHAT IS DELIBERATELY NOT INSTALLED: no `HttpLoggingInterceptor`. Even with provenance gone
 * from every response, a media URL is a bearer token for a live stream and the redirect chain
 * leaves it in OkHttp's BODY-level logs, and therefore into bug reports and `adb bugreport`
 * (App/AGENTS.md §3). If a future build adds a logger, it must be a redacting one, not the
 * stock interceptor.
 *
 * There is also no `If-None-Match` / ETag handling: the v1 server sends no ETag, and the v2
 * contract's ETag/304 support is not served yet — see `models/EndpointGaps.kt`.
 */
@Singleton
class ApiProvider @Inject constructor(
    private val settingsRepository: ServerSettingsRepository,
) {
    @Volatile
    private var cachedBaseUrl: String? = null

    @Volatile
    private var cachedApi: RaddStreamApi? = null

    fun forServer(serverUrl: String): RaddStreamApi {
        val baseUrl = normalizeServerUrl(serverUrl)
        cachedApi?.let { api ->
            if (cachedBaseUrl == baseUrl) return api
        }

        synchronized(this) {
            cachedApi?.let { api ->
                if (cachedBaseUrl == baseUrl) return api
            }

            val client = OkHttpClient.Builder()
                .connectTimeout(10, TimeUnit.SECONDS)
                .readTimeout(15, TimeUnit.SECONDS)
                .build()
            // MUST be buildRaddGson(), not GsonBuilder().create(): the v1 wire sends
            // `is_temporary` as 1/0 on /api/v1/posts/{id} and as true/false on
            // /api/v1/stream, and keeps INTEGER-affinity columns as TEXT when the scraped
            // value did not look numeric. The stock config throws on both. See RaddGson.kt.
            val gson: Gson = buildRaddGson()
            val api = Retrofit.Builder()
                .baseUrl(baseUrl)
                .client(client)
                .addConverterFactory(GsonConverterFactory.create(gson))
                .build()
                .create(RaddStreamApi::class.java)

            cachedBaseUrl = baseUrl
            cachedApi = api
            return api
        }
    }

    suspend fun current(): RaddStreamApi {
        val savedUrl = settingsRepository.serverUrl.first()
            ?: throw IllegalStateException("Connect to a catalog server first.")
        return forServer(savedUrl)
    }

    /**
     * The normalized origin of the server the user connected to. Two jobs: build our own
     * redirector address with [streamRedirectUrl], and be the reference origin every hand-off
     * is checked against with [isSameOriginAsServer].
     */
    suspend fun currentBaseUrl(): String {
        val savedUrl = settingsRepository.serverUrl.first()
            ?: throw IllegalStateException("Connect to a catalog server first.")
        return normalizeServerUrl(savedUrl)
    }
}

/**
 * Our own redirector address for an opaque stream handle: `<server>/api/v1/stream?id=<handle>`.
 * This is the ONLY playable address this app ever builds, hands to an external player, or writes
 * into a download task. The server answers it with a 302, so no upstream host ever appears here.
 */
fun streamRedirectUrl(baseUrl: String, streamId: String): String {
    val origin = baseUrl.trim().run { if (endsWith("/")) dropLast(1) else this }
    val handle = URLEncoder.encode(streamId.trim(), StandardCharsets.UTF_8.name())
    return "$origin/api/v1/stream?id=$handle"
}

/**
 * True only when [playUrl] is an absolute http(s) address on the SAME host+port as [baseUrl] —
 * the origin the user configured. Every hand-off in the app (external player, download, share)
 * checks this first, so an address belonging to anyone else is refused even if one somehow
 * reached a model.
 */
fun isSameOriginAsServer(playUrl: String?, baseUrl: String): Boolean {
    val target = playUrl?.trim()?.takeIf { it.isNotEmpty() } ?: return false
    val base = baseUrl.trim().takeIf { it.isNotEmpty() } ?: return false
    val targetUri = try { URI(target) } catch (_: Exception) { return false }
    val baseUri = try { URI(base) } catch (_: Exception) { return false }
    val scheme = targetUri.scheme?.lowercase(Locale.ROOT) ?: return false
    if (scheme != "http" && scheme != "https") return false
    val host = targetUri.host?.lowercase(Locale.ROOT) ?: return false
    val baseHost = baseUri.host?.lowercase(Locale.ROOT) ?: return false
    if (host != baseHost) return false
    val basePort = if (baseUri.port >= 0) baseUri.port else defaultPort(baseUri.scheme)
    val targetPort = if (targetUri.port >= 0) targetUri.port else defaultPort(targetUri.scheme)
    return basePort == targetPort
}

private fun defaultPort(scheme: String?): Int = when (scheme?.lowercase(Locale.ROOT)) {
    "https" -> 443
    "http" -> 80
    else -> -1
}

/**
 * Validate and normalize a user-entered server origin before passing it to Retrofit.
 * Credentials, query strings, and fragments are rejected rather than persisted.
 */
fun normalizeServerUrl(input: String): String {
    val value = input.trim()
    require(value.isNotEmpty()) { "Enter a server URL." }

    val uri = try {
        URI(value)
    } catch (_: Exception) {
        throw IllegalArgumentException("Enter a valid server URL.")
    }

    val scheme = uri.scheme?.lowercase(Locale.ROOT)
    require(scheme == "http" || scheme == "https") {
        "The server URL must start with http:// or https://."
    }
    require(!uri.host.isNullOrBlank()) { "The server URL must include a hostname." }
    require(uri.rawUserInfo == null && uri.rawQuery == null && uri.rawFragment == null) {
        "Do not include credentials, a query, or a fragment in the server URL."
    }

    val normalizedScheme = value.replaceFirst(
        Regex("^[A-Za-z][A-Za-z0-9+.-]*://"),
        "$scheme://",
    )
    return if (normalizedScheme.endsWith('/')) normalizedScheme else "$normalizedScheme/"
}
