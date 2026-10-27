package com.raddstream.app.ui.navigation

import java.net.URLDecoder
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

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

        fun createRoute(streamId: String, title: String): String {
            val encodedHandle = URLEncoder.encode(streamId, StandardCharsets.UTF_8.name())
            val encodedTitle = URLEncoder.encode(title, StandardCharsets.UTF_8.name())
            return "player/$encodedHandle/$encodedTitle"
        }

        fun decodeStreamId(encoded: String): String =
            try {
                URLDecoder.decode(encoded, StandardCharsets.UTF_8.name())
            } catch (_: Exception) {
                encoded
            }

        fun decodeTitle(encoded: String): String =
            try {
                URLDecoder.decode(encoded, StandardCharsets.UTF_8.name())
            } catch (_: Exception) {
                encoded
            }
    }

    /**
     * A finished public download addressed by its own local content/file URI. It is not a
     * stream handle and must not be routed through the redirector: the bytes are already here.
     */
    object PlayerLocal : Screen("player_local/{uri}/{title}") {
        const val ARG_URI = "uri"
        const val ARG_TITLE = "title"

        fun createRoute(uri: String, title: String): String {
            val encodedUri = URLEncoder.encode(uri, StandardCharsets.UTF_8.name())
            val encodedTitle = URLEncoder.encode(title, StandardCharsets.UTF_8.name())
            return "player_local/$encodedUri/$encodedTitle"
        }

        fun decode(encoded: String): String =
            try {
                URLDecoder.decode(encoded, StandardCharsets.UTF_8.name())
            } catch (_: Exception) {
                encoded
            }
    }
}
