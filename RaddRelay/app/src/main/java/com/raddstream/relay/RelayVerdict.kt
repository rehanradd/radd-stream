package com.raddstream.relay

/**
 * What one POST attempt proved, and what the queue does next.
 *
 * This is a pure function on the HTTP status on purpose: the defect it exists to
 * prevent was a *classification* error, not a transport error. A 403 from nginx
 * was read as "merchant secret rejected" and the payment was deleted on the
 * strength of it — but a proxy refusing a route says nothing about the
 * credential, and the route the app ships against is loopback-only by design.
 *
 * Rules:
 *  - 2xx and 409 are done (409 = the server already holds this TID; replay-safe).
 *  - 401 is the one status that genuinely means "credential rejected" — the
 *    server verifies X-Merchant-Secret before it reads a byte of the body.
 *  - 403 is a *proxy* refusing the route; the credential was never checked, so
 *    it is a retry with a reason that names the route, not the secret.
 *  - 404 is the route not deployed yet; retry.
 *  - 408/429/5xx and anything this table has never seen are retries: an unseen
 *    status is not evidence that the request was wrong.
 *  - Other 4xx are the request being wrong (malformed payload, bad TID shape);
 *    retrying cannot fix them from the phone.
 */
sealed class PostVerdict {

    object Ok : PostVerdict()

    data class Retry(val reason: String) : PostVerdict()

    data class Reject(val reason: String) : PostVerdict()

    companion object {
        fun of(code: Int): PostVerdict = when (code) {
            in 200..299 -> Ok
            409 -> Ok
            401 -> Reject("HTTP 401 — the server rejected the merchant secret")
            403 -> Retry(
                "HTTP 403 — a proxy refused the route; the credential was never checked",
            )
            404 -> Retry("HTTP 404 — webhook route not deployed yet")
            408, 429 -> Retry("HTTP $code")
            in 400..499 -> Reject("HTTP $code")
            else -> Retry("HTTP $code — unexpected status")
        }
    }
}
