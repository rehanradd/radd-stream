package com.raddstream.app.player

import androidx.media3.common.C
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.HttpDataSource
import androidx.media3.exoplayer.upstream.DefaultLoadErrorHandlingPolicy
import androidx.media3.exoplayer.upstream.LoadErrorHandlingPolicy
import java.io.IOException

/**
 * HTTP statuses our own redirector answers with a final word — a handle
 * that has no playable source (404/410), a rung the quality gate refused
 * (402), or a press the server's per-minute bucket refused (429). None of
 * these heals by asking again at once: the 402 is the failover machine's
 * step-down, the 404/410 is its hop to another handle, and the 429 is a
 * "wait", not a "retry now". Media3's default policy retries the media
 * item — which IS the redirector URL — on all of them, so one dead handle
 * presses the redirector ~1/sec until the bucket 429s the whole session
 * (Sauce Labs S5, 2026-11-13: 239x404 + 136x429 in the window).
 */
internal val TERMINAL_REDIRECTOR_HTTP_STATUSES: Set<Int> = setOf(402, 403, 404, 410, 429)

/**
 * The retry delay for a load error whose HTTP status is known, or null
 * when this policy has nothing to say and Media3's default decides.
 * Pure, so the terminal-status table is pinnable without a player:
 * a terminal status never retries ([C.TIME_UNSET]), anything else
 * defers to the default.
 */
internal fun redirectorRetryDelayMs(responseCode: Int?): Long? =
    if (responseCode != null && responseCode in TERMINAL_REDIRECTOR_HTTP_STATUSES) C.TIME_UNSET else null

/**
 * Media3's load-error policy for the player, wrapping the default: a
 * terminal answer from our own redirector is never retried by the
 * loader — the failover machine owns the next move — and every other
 * error keeps the default's backoff. The status is read off the
 * exception the same two ways the failover machine reads a gate refusal
 * (see [isGateRefusalError]): the [HttpDataSource.InvalidResponseCodeException]
 * itself, or its message, "Response code: 404".
 */
// NOTE: the class carries @UnstableApi directly, not @OptIn — in Media3
// 1.3.1 UnstableApi is not a @RequiresOptIn marker, so @OptIn is ignored
// (kotlinc warning) and lint still flags implementing the unstable
// LoadErrorHandlingPolicy supertype. Marking the class propagates the
// instability to its users instead of hiding it.
@UnstableApi
class RedirectorLoadErrorPolicy : LoadErrorHandlingPolicy {

    private val fallback = DefaultLoadErrorHandlingPolicy()

    override fun getRetryDelayMsFor(loadErrorInfo: LoadErrorHandlingPolicy.LoadErrorInfo): Long {
        val terminal = redirectorRetryDelayMs(invalidResponseCode(loadErrorInfo.exception))
        if (terminal != null) return terminal
        return fallback.getRetryDelayMsFor(loadErrorInfo)
    }

    override fun getFallbackSelectionFor(
        fallbackOptions: LoadErrorHandlingPolicy.FallbackOptions,
        loadErrorInfo: LoadErrorHandlingPolicy.LoadErrorInfo,
    ): LoadErrorHandlingPolicy.FallbackSelection? {
        // A terminal answer is a final word, not a cue to try another
        // location/track of the same redirector URL — the failover machine
        // owns the next move. Everything else keeps the default's fallback.
        if (redirectorRetryDelayMs(invalidResponseCode(loadErrorInfo.exception)) != null) return null
        return fallback.getFallbackSelectionFor(fallbackOptions, loadErrorInfo)
    }

    override fun getMinimumLoadableRetryCount(dataType: Int): Int =
        fallback.getMinimumLoadableRetryCount(dataType)

    private fun invalidResponseCode(exception: IOException?): Int? {
        var cause: Throwable? = exception
        while (cause != null) {
            if (cause is HttpDataSource.InvalidResponseCodeException) return cause.responseCode
            cause = cause.cause
        }
        return null
    }
}
