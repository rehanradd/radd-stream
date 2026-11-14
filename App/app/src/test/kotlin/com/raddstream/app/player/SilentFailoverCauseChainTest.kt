package com.raddstream.app.player

import android.net.Uri
import androidx.media3.common.PlaybackException
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.HttpDataSource
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * The cause-chain half of the rate-limit detector ([isRateLimitedError]):
 * Media3 1.3.1 carries the HTTP status on the exception itself, so the
 * chain — not the message — is what recognises a 429 when the message
 * says nothing about it.
 *
 * This class is Robolectric, not plain JVM, on purpose. Media3 1.3.1's
 * [HttpDataSource.InvalidResponseCodeException] constructors all take a
 * @NonNull [DataSpec], and [DataSpec] takes a @NonNull [Uri] — so the
 * exception cannot be built without a real Uri, and `Uri.parse` needs the
 * framework. Two plain-JVM attempts proved it in CI: `DataSpec(null)`
 * failed (run 43555494034, `Null cannot be a value of a non-null type
 * android.net.Uri`), and passing a null DataSpec failed the same way
 * (run 43557197413, `Null cannot be a value of a non-null type
 * androidx.media3.datasource.DataSpec`). The message half of the detector
 * stays in the plain-JVM [SilentFailoverTest]; only the chain half lives
 * here.
 */
@RunWith(RobolectricTestRunner::class)
class SilentFailoverCauseChainTest {

    private fun causeChainError(status: Int): PlaybackException {
        val cause = HttpDataSource.InvalidResponseCodeException(
            status, null, null, emptyMap(),
            DataSpec(Uri.parse("https://127.0.0.1:8080/api/v1/stream?id=h-$status")),
            ByteArray(0),
        )
        return PlaybackException(
            "source error", cause,
            PlaybackException.ERROR_CODE_IO_BAD_HTTP_STATUS,
        )
    }

    @Test
    fun `isRateLimitedError recognizes a 429 through the cause chain`() {
        assertTrue(isRateLimitedError(causeChainError(429)))
    }

    @Test
    fun `isRateLimitedError rejects a 404 through the cause chain`() {
        // The chain branch must be status-based, not "any
        // InvalidResponseCodeException": a 404 hops, it never pauses.
        assertFalse(isRateLimitedError(causeChainError(404)))
    }
}
