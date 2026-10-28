package com.raddstream.app.ui.navigation

import java.net.URLDecoder
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

/**
 * The one route-argument codec. A handle, a URI or a title is free TEXT that can contain `/`,
 * `?` and `%`, and a route segment splits on those characters — so every destination carrying
 * one encodes on the way in and decodes on the way out, identically. Three destinations needed
 * this and each had its own copy of the same four lines; one owner means a route can never be
 * built one way and parsed another.
 */
private fun encodeRouteArg(raw: String): String =
    URLEncoder.encode(raw, StandardCharsets.UTF_8.name())

private fun decodeRouteArg(encoded: String): String =
    try {
        URLDecoder.decode(encoded, StandardCharsets.UTF_8.name())
    } catch (_: Exception) {
        // A malformed escape is not a reason to lose the whole argument: show what the caller
        // actually typed rather than a percent-sign soup.
        encoded
    }

/** All navigation destinations as a sealed class. */
sealed class Screen(val route: String) {
    object Setup : Screen("setup")
    object Region : Screen("region")
    object Home : Screen("home")
    object Search : Screen("search")
    object MyList : Screen("my_list")
    object Settings : Screen("settings")
    object Downloads : Screen("downloads")
    object VipUpgrade : Screen("vip_upgrade")
    object Browse : Screen("browse/{type}") {
        const val ARG_TYPE = "type"
        fun createRoute(type: String?): String = "browse/${type ?: "all"}"
    }
    object Detail : Screen("detail/{postId}") {
        const val ARG_POST_ID = "postId"
        fun createRoute(postId: Int): String = "detail/$postId"
    }
    /**
     * The player is addressed by the server's OPAQUE STREAM HANDLE, never by a URL: a route
     * argument lands in the back stack, in saved state and in a deep link, so an address in
     * here is an address that leaves the app. The handle resolves against our own
     * `/api/v1/stream?id=…` redirector at playback time.
     */
    object Player : Screen("player/{streamId}/{title}") {
        const val ARG_STREAM_ID = "streamId"
        const val ARG_TITLE = "title"

        fun createRoute(streamId: String, title: String): String =
            "player/${encodeRouteArg(streamId)}/${encodeRouteArg(title)}"

        fun decodeStreamId(encoded: String): String = decodeRouteArg(encoded)

        fun decodeTitle(encoded: String): String = decodeRouteArg(encoded)
    }

    /**
     * The provider's own page, for a link the server says is a page and not a file
     * (`ProviderPageLinks`). Addressed by the opaque handle for exactly the reason [Player] is:
     * the screen loads OUR redirector for that handle and lets the server's 302 decide where it
     * lands, so no upstream address is ever composed here, saved in a back stack, or painted on
     * the screen. What opens is the hoster's player — visibly, with its own controls and its own
     * conditions — because this app has no other way to present that page, and takes no
     * shortcut around it.
     */
    object Embed : Screen("embed/{streamId}/{title}") {
        const val ARG_STREAM_ID = "streamId"
        const val ARG_TITLE = "title"

        fun createRoute(streamId: String, title: String): String =
            "embed/${encodeRouteArg(streamId)}/${encodeRouteArg(title)}"

        fun decodeStreamId(encoded: String): String = decodeRouteArg(encoded)

        fun decodeTitle(encoded: String): String = decodeRouteArg(encoded)
    }

    /**
     * A finished public download addressed by its own local content/file URI. It is not a
     * stream handle and must not be routed through the redirector: the bytes are already here.
     */
    object PlayerLocal : Screen("player_local/{uri}/{title}") {
        const val ARG_URI = "uri"
        const val ARG_TITLE = "title"

        fun createRoute(uri: String, title: String): String =
            "player_local/${encodeRouteArg(uri)}/${encodeRouteArg(title)}"

        fun decode(encoded: String): String = decodeRouteArg(encoded)
    }
}
