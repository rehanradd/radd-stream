package com.raddstream.app.viewmodel

import java.io.IOException
import java.net.SocketTimeoutException
import kotlinx.coroutines.CancellationException
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response

/**
 * Session 156 (2026-11-13): the detail retry policy. The Sauce Labs S3
 * re-test showed a first tap dying with no request on the wire and the
 * "Failed to load details" screen — the error that caused it must retry
 * like any other first-call failure, never fail the tap outright.
 */
class DetailRetryPolicyTest {

    private fun http(code: Int): HttpException =
        HttpException(Response.error<Any>(code, "x".toResponseBody("text/plain".toMediaType())))

    @Test
    fun `provider not ready retries`() {
        assertTrue(
            isTransientDetailError(
                IllegalStateException("Connect to a catalog server first."),
            ),
        )
    }

    @Test
    fun `transport failures retry`() {
        assertTrue(isTransientDetailError(IOException("Connection reset")))
        assertTrue(isTransientDetailError(SocketTimeoutException("timeout")))
    }

    @Test
    fun `retryable HTTP statuses retry`() {
        assertTrue(isTransientDetailError(http(429)))
        assertTrue(isTransientDetailError(http(500)))
        assertTrue(isTransientDetailError(http(503)))
    }

    @Test
    fun `deterministic HTTP statuses fail fast`() {
        assertFalse(isTransientDetailError(http(400)))
        assertFalse(isTransientDetailError(http(401)))
        assertFalse(isTransientDetailError(http(403)))
        assertFalse(isTransientDetailError(http(404)))
    }

    @Test
    fun `anything else fails fast`() {
        assertFalse(isTransientDetailError(RuntimeException("boom")))
        assertFalse(isTransientDetailError(IllegalArgumentException("bad address")))
    }

    @Test
    fun `cancellation is never transient`() {
        // CancellationException extends IllegalStateException, so the
        // provider-not-ready branch above must not swallow it: a cancelled
        // load aborts at once instead of retrying.
        assertFalse(isTransientDetailError(CancellationException("cancelled")))
        assertFalse(
            isTransientDetailError(
                java.util.concurrent.CancellationException("cancelled"),
            ),
        )
    }

    @Test
    fun `retry budget is four attempts`() {
        // S3: three attempts over ~2.1 s closed before the connection
        // recovered. The fourth costs one more 1.5 s backoff, only when
        // all three before it failed.
        assertEquals(4, DETAIL_LOAD_MAX_ATTEMPTS)
    }
}
