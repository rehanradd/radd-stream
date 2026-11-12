package com.raddstream.app.player

import java.net.URLEncoder
import java.nio.charset.StandardCharsets

/**
 * Session 76 (Build 4): the bought direct-download URL for one opaque stream
 * handle — what the coins "Direct Link" button opens for a viewer who spent
 * a download credit.
 *
 * The URL is the server's own download endpoint with the spent credit
 * attached: `<server>/api/v1/download?id=<handle>&credit=<token>`. The
 * server spends the credit on this one download and 302s straight to the
 * file — a credit is a direct file, not a web page, so the shortener never
 * runs on it whether or not any web marker is set. The token is the
 * credit's signed id, so the browser needs no account and the credit buys
 * no other movie.
 *
 * The free web-link form this file used to build (the shortener
 * interstitial) is GONE — removed 2026-11-12 with the download
 * dialog's "Need a free link instead?" row. Free downloads go through the
 * in-app download service only, never a browser.
 *
 * Mirrors [com.raddstream.app.network.downloadRedirectUrl]'s shape (trim
 * the base, drop one trailing slash, URL-encode the handle) so the two
 * URLs can never drift apart in encoding.
 */
fun creditDownloadUrl(serverBaseUrl: String, streamId: String, creditToken: String): String {
    val origin = serverBaseUrl.trim().run { if (endsWith("/")) dropLast(1) else this }
    val handle = URLEncoder.encode(streamId.trim(), StandardCharsets.UTF_8.name())
    val token = URLEncoder.encode(creditToken.trim(), StandardCharsets.UTF_8.name())
    return "$origin/api/v1/download?id=$handle&credit=$token"
}
