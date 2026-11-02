package com.raddstream.app.network

import com.google.gson.Gson
import com.raddstream.app.brand.Brand
import com.raddstream.app.data.ServerSettingsRepository
import java.net.ConnectException
import java.net.URI
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.util.Locale
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.withContext
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
    private val discovery: DynamicServerDiscovery,
) {
    @Volatile
    private var cachedBaseUrl: String? = null

    @Volatile
    private var cachedApi: RaddStreamApi? = null

    /**
     * The address THIS PROCESS is using, and the saved value the choice was made from.
     *
     * Session-only by design: a fallback to the plain-HTTP address is a decision about the network
     * right now, not a preference. It is never written to Settings, so the next launch tries the
     * brand's TLS address first again.
     *
     * Keying it to the saved value is what keeps that cache honest. Before this existed every call
     * re-read Settings, so a viewer who changed server mid-session was on the new one immediately;
     * a plain process-wide cache would have frozen them onto the old address until restart. The
     * fallback still survives the session because nothing changes the saved value while it is in
     * force — the failover path has no writer, which is the second half of the same rule.
     */
    @Volatile
    private var sessionDecision: SessionDecision? = null

    private data class SessionDecision(val savedUrl: String?, val serverUrl: String)

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

    suspend fun current(): RaddStreamApi = forServer(resolveSessionServerUrl())

    /**
     * The normalized origin of the server this session is actually talking to — the primary
     * address when it answers, the brand's fallback when it does not. Two jobs: build our own
     * redirector address with [streamRedirectUrl], and be the reference origin every hand-off
     * is checked against with [isSameOriginAsServer].
     */
    suspend fun currentBaseUrl(): String = normalizeServerUrl(resolveSessionServerUrl())

    /**
     * The one address this session uses, chosen once and then held for as long as the saved value
     * stays where it was.
     *
     * Primary first, fallback second — see [serverCandidates] for who counts as primary and
     * [pickWorkingServer] for what "works" means. If nothing answers, the failure is a
     * [ConnectException] with no address in it, because [friendlyNetworkError] shows a debug
     * build's raw text to the person holding the phone.
     *
     * [probe] exists so a test can decide reachability instead of asking a socket; production
     * never passes it. This function reads the saved server and returns a choice — it does not
     * write anything, which is what keeps a fallback to the plain-HTTP address from becoming the
     * address the install remembers.
     */
    internal suspend fun resolveSessionServerUrl(
        probe: (String) -> Boolean = ::probeDefault,
    ): String {
        val savedUrl = settingsRepository.serverUrl.first()
        sessionDecision?.let { decision ->
            if (decision.savedUrl == savedUrl) return decision.serverUrl
        }
        val chosen = withContext(Dispatchers.IO) {
            chooseSessionServer(savedUrl, Brand.defaultServerUrl, Brand.fallbackServerUrl, probe)
        }
        sessionDecision = SessionDecision(savedUrl, chosen)
        return chosen
    }

    private fun probeDefault(serverUrl: String): Boolean = discovery.probeNodeHealth(serverUrl)
}

/**
 * The address this session uses: the first candidate that [probe] says is working.
 *
 * It takes the saved address as a value and returns a value, and it holds no reference to anything
 * that can write — which is the whole reason a fallback to the plain-HTTP box cannot become the
 * address the install remembers. [ApiProvider] caches what this returns for the process and
 * nothing else.
 *
 * Two failures are deliberately distinct. Nothing configured at all is the Setup routing case, so
 * it throws [IllegalStateException] with the app's existing sentence and the person lands on the
 * connect screen. Nothing *answering* is a transport failure, so it throws [ConnectException] —
 * which [friendlyNetworkError] already renders as "The server didn't answer. It may be offline —
 * try again in a moment." The message names no address, no host and no status code, because a
 * debug build appends this raw text to the plain sentence.
 */
internal fun chooseSessionServer(
    savedUrl: String?,
    defaultUrl: String,
    fallbackUrl: String,
    probe: (String) -> Boolean,
): String {
    val candidates = serverCandidates(savedUrl, defaultUrl, fallbackUrl)
    if (candidates.isEmpty()) throw IllegalStateException("Connect to a catalog server first.")
    return pickWorkingServer(candidates, probe)
        ?: throw ConnectException(NO_WORKING_SERVER_MESSAGE)
}

private const val NO_WORKING_SERVER_MESSAGE = "No configured server answered"

/**
 * The addresses this session may use, in the order it should try them.
 *
 * Primary is whatever the person chose in Setup/Settings; with nothing chosen it is the brand's
 * default. Two rules then apply, and both exist so a TLS-first install is what a real install gets:
 *
 *  - **An install that predates the TLS default.** A saved address equal to the brand's *fallback*
 *    (the plain-HTTP box) is not a preference for HTTP — it is the old shipped default that
 *    outlived itself. The brand's TLS address goes first and the saved HTTP one drops to second.
 *  - **A saved address belonging to somebody else.** A viewer who pointed this app at a catalog of
 *    their own is not this deployment's customer for failover purposes: appending our fallback host
 *    would start sending *their* catalog's traffic to *our* server. The fallback is offered only
 *    when the primary is one of our own two addresses.
 *
 * Blank inputs drop out, and a candidate already in the list is never added twice, so a build that
 * ships no fallback yields exactly one candidate and behaves as it did before this existed.
 */
internal fun serverCandidates(
    savedUrl: String?,
    defaultUrl: String,
    fallbackUrl: String,
): List<String> {
    val fallback = fallbackUrl.trim()
    val primary = (savedUrl?.takeIf { it.isNotBlank() } ?: defaultUrl).trim()
    if (primary.isEmpty()) return emptyList()

    val primaryOrigin = originOf(primary)
    val defaultOrigin = originOf(defaultUrl)
    val fallbackOrigin = originOf(fallback)

    val ordered: List<String> = when {
        primaryOrigin.isNotEmpty() && primaryOrigin == fallbackOrigin &&
            defaultOrigin.isNotEmpty() && defaultOrigin != primaryOrigin ->
            listOf(defaultUrl.trim(), primary)
        fallback.isNotEmpty() && fallbackOrigin.isNotEmpty() && primaryOrigin == defaultOrigin ->
            listOf(primary, fallback)
        else -> listOf(primary)
    }
    return ordered.filter { it.isNotEmpty() }.distinctBy { originOf(it).ifEmpty { it } }
}

/**
 * The first candidate a probe says is working, or null when none is. Probes are cheap and
 * sequential on purpose: trying both when the first answers would double the latency of every
 * cold start and pick the slower address.
 */
internal fun pickWorkingServer(
    candidates: List<String>,
    probe: (String) -> Boolean,
): String? = candidates.firstOrNull { probe(it) }

/**
 * `scheme://host:port` with the scheme and host lowercased and a default port made explicit, so
 * two spellings of one server compare equal. An address that will not parse returns "" and is then
 * never treated as a match for anything — a malformed saved value stays exactly where it is.
 */
private fun originOf(url: String): String {
    val value = url.trim()
    if (value.isEmpty()) return ""
    val uri = try {
        URI(value)
    } catch (_: Exception) {
        return ""
    }
    val scheme = uri.scheme?.lowercase(Locale.ROOT) ?: return ""
    val host = uri.host?.lowercase(Locale.ROOT)?.takeIf { it.isNotEmpty() } ?: return ""
    val port = if (uri.port >= 0) uri.port else defaultPort(scheme)
    return "$scheme://$host:$port"
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
