package com.raddstream.relay

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The status -> verdict table, as a pure rule.
 *
 * The defect this guards: a 403 from a proxy used to classify as Reject ("merchant
 * secret rejected"), and Reject used to delete the queued payment. Under the
 * shipped default URL every real payment would have been posted once, refused by
 * the edge, and destroyed on the phone — with a log line naming the wrong cause.
 */
class RelayVerdictTest {

    private fun verdict(code: Int) = PostVerdict.of(code)

    @Test
    fun two_hundred_family_is_ok() {
        for (code in listOf(200, 201, 204, 299)) {
            assertEquals("HTTP $code must be Ok", PostVerdict.Ok, verdict(code))
        }
    }

    @Test
    fun conflict_409_is_ok_because_the_server_already_has_the_tid() {
        assertEquals(PostVerdict.Ok, verdict(409))
    }

    @Test
    fun unauthorized_401_is_reject_because_the_secret_was_checked() {
        assertTrue(verdict(401) is PostVerdict.Reject)
        assertTrue((verdict(401) as PostVerdict.Reject).reason.contains("401"))
    }

    @Test
    fun forbidden_403_is_retry_and_does_not_blame_the_secret() {
        val result = verdict(403)
        assertTrue("a proxy refusal is not a verdict on the credential", result is PostVerdict.Retry)
        val reason = (result as PostVerdict.Retry).reason
        assertTrue(reason.contains("403"))
        assertTrue("the reason must name the route", reason.contains("proxy"))
        assertTrue(
            "the reason must not assert a credential failure",
            !reason.contains("secret"),
        )
    }

    @Test
    fun missing_route_404_is_retry() {
        assertTrue(verdict(404) is PostVerdict.Retry)
    }

    @Test
    fun timeout_and_rate_limit_retry() {
        assertTrue(verdict(408) is PostVerdict.Retry)
        assertTrue(verdict(429) is PostVerdict.Retry)
    }

    @Test
    fun other_client_errors_are_rejects() {
        for (code in listOf(400, 422, 413)) {
            assertTrue("HTTP $code is a request fault", verdict(code) is PostVerdict.Reject)
        }
    }

    @Test
    fun server_errors_retry() {
        for (code in listOf(500, 502, 503)) {
            assertTrue("HTTP $code is the server's problem", verdict(code) is PostVerdict.Retry)
        }
    }

    @Test
    fun positive_control_an_unseen_status_is_never_a_reject() {
        // The table has no arm for these, so they fall through. The requirement is
        // directional: "unknown" must preserve the payment, never destroy it.
        for (code in listOf(0, 302, 600)) {
            assertTrue(
                "HTTP $code was never classified; it must not read as Reject",
                verdict(code) !is PostVerdict.Reject,
            )
        }
    }
}
