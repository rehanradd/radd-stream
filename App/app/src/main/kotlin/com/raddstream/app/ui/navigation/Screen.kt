package com.raddstream.app.ui.navigation

import java.net.URLDecoder
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

/** All navigation destinations as a sealed class. */
sealed class Screen(val route: String) {
    object Setup : Screen("setup")
    object Home : Screen("home")
    object Search : Screen("search")
    object MyList : Screen("my_list")
    object Settings : Screen("settings")
    object Detail : Screen("detail/{postId}") {
        const val ARG_POST_ID = "postId"
        fun createRoute(postId: Int): String = "detail/$postId"
    }
    object Player : Screen("player/{url}/{title}") {
        const val ARG_URL = "url"
        const val ARG_TITLE = "title"

        fun createRoute(streamUrl: String, title: String): String {
            val encodedUrl = URLEncoder.encode(streamUrl, StandardCharsets.UTF_8.name())
            val encodedTitle = URLEncoder.encode(title, StandardCharsets.UTF_8.name())
            return "player/$encodedUrl/$encodedTitle"
        }

        fun decodeUrl(encoded: String): String =
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
}
