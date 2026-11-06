package com.raddstream.app.ui.navigation

import com.raddstream.app.brand.Brand

/**
 * The deep links this app opens and shares, in one place — so a URI built
 * for sharing, a URI the manifest accepts, and a URI the NavGraph matches
 * can never drift apart.
 *
 * The scheme is the brand's (`Brand.deepLinkScheme`, `radd` today); the
 * manifest accepts any path under it, and the NavGraph matches the same
 * patterns below. A stream link carries the server's OPAQUE HANDLE, never
 * an address — the same rule as [Screen.Player]: the handle resolves
 * against our own redirector at playback time.
 *
 * [parse] is the contract check: it answers what a URI means, so a test can
 * pin the shapes the NavGraph patterns implement. Nothing in the app calls
 * it today — incoming links arrive through the NavController — but the next
 * caller (an incoming-share handler, a notification tap) reads this file,
 * not three.
 */
sealed interface DeepLink {
    data class Detail(val postId: Int) : DeepLink
    data class Stream(val streamId: String, val title: String) : DeepLink
    data class Browse(val type: String?) : DeepLink
}

object DeepLinks {

    /** The link a share sends: the title's own page inside this app. */
    fun detailUri(postId: Int): String = Brand.deepLinkUri("detail/$postId")

    /** The link that opens the player for one stream handle. */
    fun streamUri(streamId: String, title: String): String =
        Brand.deepLinkUri("stream/${encodeRouteArg(streamId)}/${encodeRouteArg(title)}")

    fun browseUri(type: String?): String = Brand.deepLinkUri("browse/${type ?: "all"}")

    fun parse(uri: String): DeepLink? {
        val prefix = "${Brand.deepLinkScheme}://"
        if (!uri.startsWith(prefix)) return null
        val segments = uri.removePrefix(prefix).trimStart('/')
            .split("/").map { decodeRouteArg(it) }
        return when (segments.firstOrNull()) {
            "detail" -> segments.getOrNull(1)?.toIntOrNull()?.let { DeepLink.Detail(it) }
            "stream" -> if (segments.size >= 3) {
                DeepLink.Stream(segments[1], segments[2])
            } else {
                null
            }
            "browse" -> DeepLink.Browse(segments.getOrNull(1))
            else -> null
        }
    }
}
