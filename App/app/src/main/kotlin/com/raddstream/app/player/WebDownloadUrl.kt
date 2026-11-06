package com.raddstream.app.player

import java.net.URLEncoder
import java.nio.charset.StandardCharsets

/**
 * Session 73 (Phase 5): the external-browser download URL for one opaque stream
 * handle — what the [Get Free Web Link] button opens for a free viewer.
 *
 * The URL is the server's own download endpoint with the web marker:
 * `<server>/api/v1/download?id=<handle>&via=web`. The server answers with a
 * 302 to ShrinkMe when the operator has enabled it, or straight to the file —
 * either way the browser, not the app, follows it, which is the whole point:
 * shorteners need interactive timers and browser clicks that break native
 * background downloads, so the app never shortens anything itself.
 *
 * Why not the branded `/download/?id=` page: nginx serves that location with
 * `Content-Disposition: attachment`, so a browser downloads the page's HTML
 * instead of rendering it — the page can only land with the gate's nginx
 * change. The direct link needs no live change and the user ends up in the
 * same place (the ShrinkMe interstitial, or the file).
 *
 * Mirrors [com.raddstream.app.network.streamRedirectUrl]'s shape (trim the
 * base, drop one trailing slash, URL-encode the handle) so the two URLs can
 * never drift apart in encoding.
 */
fun webDownloadUrl(serverBaseUrl: String, streamId: String): String {
    val origin = serverBaseUrl.trim().run { if (endsWith("/")) dropLast(1) else this }
    val handle = URLEncoder.encode(streamId.trim(), StandardCharsets.UTF_8.name())
    return "$origin/api/v1/download?id=$handle&via=web"
}
