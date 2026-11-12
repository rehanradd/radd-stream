package com.raddstream.app.network

import com.google.gson.Gson
import com.raddstream.app.brand.Brand
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.data.Telemetry
import java.net.URI
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.util.Locale
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.first
import okhttp3.CertificatePinner
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

            val defaultHost = runCatching { URI(Brand.defaultServerUrl).host }.getOrNull()
            val clientBuilder = OkHttpClient.Builder()
                .connectTimeout(10, TimeUnit.SECONDS)
                .readTimeout(15, TimeUnit.SECONDS)
                // Every request carries the app's own User-Agent, including its
                // version name: the config fetch is how the server learns
                // which build is asking, and the discovery probes already
                // send this same string. No header, no version on the wire.
                //
                // Tracking A adds the install headers on top, and only once
                // the viewer said yes to anonymous totals: `X-Install-Id` (a
                // random id minted on accept, never derived from the phone),
                // `X-App-Version`, `X-Device-Class` (low/mid/high from RAM),
                // `X-Region` (the viewer's region card), the two language
                // choices, and `Accept-Language` (the server reads only its
                // region subtag). A viewer who declined or was never asked
                // sends exactly what this client sent before — the User-Agent
                // alone — and the server falls back to the credential digest,
                // as it always did.
                .addInterceptor { chain ->
                    val builder = chain.request().newBuilder()
                        .header("User-Agent", Brand.userAgent)
                    if (Telemetry.consentAccepted) {
                        Telemetry.installId?.let { builder.header("X-Install-Id", it) }
                        builder.header("X-App-Version", Telemetry.appVersion)
                        builder.header("X-Device-Class", Telemetry.deviceClass)
                        Telemetry.region?.let { builder.header("X-Region", it) }
                        Telemetry.audioLanguage?.takeIf { it.isNotBlank() }
                            ?.let { builder.header("X-Audio-Lang", it) }
                        Telemetry.subtitleLanguage?.takeIf { it.isNotBlank() }
                            ?.let { builder.header("X-Subtitle-Lang", it) }
                        builder.header("Accept-Language", Telemetry.acceptLanguage)
                    }
                    chain.proceed(builder.build())
                }
            // Certificate pinning, default host only: `certificatePinnerFor`
            // returns null for any other server (or no pins), so a user-chosen
            // catalog is never pinned and the platform trust store decides.
            certificatePinnerFor(baseUrl, defaultHost, Brand.tlsPins)?.let {
                clientBuilder.certificatePinner(it)
            }
            val client = clientBuilder.build()
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
 * The VIP pass as a request header (Session 126): `X-Radd-Vip-Pass: <pass>`.
 * The same verification as `?vip=` on the server side (`redact.VIP_PASS_HEADER`),
 * but the pass never enters a URL — so it never lands in WebView history, a
 * back-stack argument, or a bug report. Only the Embed WebView uses this form:
 * it loads our own redirector directly, so the header rides the one request
 * that needs it. The player and the download engine keep [withVipPass], because
 * they follow the 302 outside this process and a header cannot ride along.
 */
const val VIP_PASS_HEADER: String = "X-Radd-Vip-Pass"

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
 * Our own download address for an opaque stream handle: `<server>/api/v1/download?id=<handle>`.
 * The in-app device-download path fetches through this, never through the
 * play redirector and never through a browser: the server answers it with
 * a 302 to the file, exactly like `/api/v1/stream`, and the download
 * client follows it with Range resume. (The HLS keep engine still fetches
 * its playlist through the play redirector — a segmented keep, not a file
 * download.)
 */
fun downloadRedirectUrl(baseUrl: String, streamId: String): String {
    val origin = baseUrl.trim().run { if (endsWith("/")) dropLast(1) else this }
    val handle = URLEncoder.encode(streamId.trim(), StandardCharsets.UTF_8.name())
    return "$origin/api/v1/download?id=$handle"
}

/**
 * Appends a signed VIP pass to one of our own redirector/download URLs
 * (Session 123): `…?vip=<pass>`. A null or blank pass leaves the URL
 * untouched, so guests and free accounts send exactly what they sent
 * before. The pass — not the sync key — is what travels here, because the
 * player and the download engine follow the 302 outside this process and a
 * header cannot ride along, while a pass carries no user id and cannot be
 * pointed at a person. Callers fetch it once per URL build from
 * `SyncAccountRepository.currentVipPass()`; the value is cached there, so
 * this never costs a network call at play time.
 */
fun withVipPass(url: String, pass: String?): String {
    if (pass.isNullOrBlank()) return url
    val encoded = URLEncoder.encode(pass.trim(), StandardCharsets.UTF_8.name())
    return url + if ("?" in url) "&vip=$encoded" else "?vip=$encoded"
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

/**
 * The certificate pinner for one server, or null when pinning does not apply.
 *
 * Pins are enforced ONLY for the shipped default host: a user-chosen server is
 * never pinned, and an empty pin list means the platform trust store decides,
 * exactly as before. `defaultHost` is the host of `Brand.defaultServerUrl` —
 * never a literal in this file, so a re-skin moves the pins with the brand.
 * A pin that fails to parse throws here, at client build time: a bad pin must
 * fail loudly, not silently pin nothing.
 */
fun certificatePinnerFor(baseUrl: String, defaultHost: String?, pins: List<String>): CertificatePinner? {
    if (pins.isEmpty()) return null
    val host = runCatching { URI(normalizeServerUrl(baseUrl)).host }.getOrNull() ?: return null
    if (defaultHost.isNullOrBlank() || !host.equals(defaultHost, ignoreCase = true)) return null
    return CertificatePinner.Builder().apply {
        pins.forEach { add(defaultHost, "sha256/$it") }
    }.build()
}
