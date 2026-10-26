package com.raddstream.app.network

import com.raddstream.app.BuildConfig
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException

/**
 * One place that turns a transport failure into a sentence a viewer can act on.
 *
 * Every screen used to print `error.message` straight from the exception, which put
 * "CLEARTEXT communication to 92.4.95.252 not permitted by network security policy"
 * and "Unable to resolve host …" in front of a person who cannot do anything with
 * them. A Retrofit `HttpException` message is the same problem: it is our wire
 * protocol's text, not the user's.
 *
 * What the viewer needs is which of the three real situations this is — the address
 * is wrong, the server is not answering, or this build is not allowed to reach it —
 * and each one names where to go. Raw text is kept for debug builds only, appended
 * after the plain sentence, because a developer genuinely does need it.
 */
fun friendlyNetworkError(
    error: Throwable?,
    fallback: String,
    debugBuild: Boolean = BuildConfig.DEBUG,
): String {
    val raw = error?.message.orEmpty()
    val plain = when {
        // The platform's own refusal, word for word from NetworkPolicyManager.
        raw.contains("CLEARTEXT communication") ->
            "This connection is not allowed over an unsecured address. " +
                "Use a server address that starts with https, or keep the app on its current server."
        error is UnknownHostException || raw.contains("Unable to resolve host") ->
            "We couldn't find that server. Check its address in Settings."
        error is ConnectException || raw.contains("Failed to connect") ->
            "The server didn't answer. It may be offline — try again in a moment."
        error is SocketTimeoutException || raw.contains("timeout", ignoreCase = true) ->
            "The server took too long to answer. Try again."
        httpStatus(raw) == 429 ->
            "That was a lot of requests at once. Give it a minute."
        httpStatus(raw) == 404 ->
            "The server doesn't have this page of the catalog."
        (httpStatus(raw) ?: 0) >= 500 ->
            "The catalog server is having trouble right now."
        else -> fallback
    }
    return if (debugBuild && raw.isNotBlank() && plain != fallback) "$plain ($raw)" else plain
}

/** The status code inside a Retrofit `HttpException` message, or null if there isn't one. */
internal fun httpStatus(raw: String): Int? =
    Regex("HTTP (\\d{3})").find(raw)?.groupValues?.get(1)?.toIntOrNull()
