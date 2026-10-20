package com.raddstream.app.network

import com.google.gson.Gson
import com.google.gson.GsonBuilder
import com.raddstream.app.data.ServerSettingsRepository
import java.net.URI
import java.util.Locale
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.first
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory

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
            val gson: Gson = GsonBuilder().create()
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
