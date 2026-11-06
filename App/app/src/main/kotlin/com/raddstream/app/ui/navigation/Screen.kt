package com.raddstream.app.ui.navigation

import java.net.URLDecoder
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

/**
 * The one route-argument codec. A handle, a URI or a title is free TEXT that can contain `/`,
 * `?` and `%`, and a route segment splits on those characters — so every destination carrying
 * one encodes on the way in and decodes on the way out, identically. Three destinations needed
 * this and each had its own copy of the same four lines; one owner means a route can never be
 * built one way and parsed another. The decoder is `internal` (not private) so [DeepLinks]
 * parses with the same codec instead of a second copy.
 */
internal fun encodeRouteArg(raw: String): String =
    URLEncoder.encode(raw, StandardCharsets.UTF_8.name())

internal fun decodeRouteArg(encoded: String): String =
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
    object Search : Screen("search?query={query}") {
        const val ARG_QUERY = "query"

        /** The tab's plain address — the bottom bar and Home navigate here, with no query. */
        const val PLAIN_ROUTE = "search"

        /** A search opened with a query already filled in (an actor tap on a detail card). */
        fun createRoute(query: String? = null): String =
            if (query.isNullOrBlank()) PLAIN_ROUTE else "search?query=${encodeRouteArg(query)}"
    }
    object LiveTv : Screen("live_tv")
    object MyList : Screen("my_list")
    object Settings : Screen("settings")
    object Help : Screen("help")
    object WatchHistory : Screen("watch_history")
    object Downloads : Screen("downloads")
    object VipUpgrade : Screen("vip_upgrade")
    /** Session 123: the account screens — the dashboard, the standalone check-in, the coins, and the profile. */
    object Dashboard : Screen("dashboard")
    object CheckIn : Screen("check_in")
    object Coins : Screen("coins")
    object Profile : Screen("profile")
    object Browse : Screen("browse/{type}") {
        const val ARG_TYPE = "type"
        fun createRoute(type: String?): String = "browse/${type ?: "all"}"
    }
    object Detail : Screen("detail/{postId}?autoplay={autoplay}&workId={workId}") {
        const val ARG_POST_ID = "postId"
        const val ARG_AUTOPLAY = "autoplay"
        /**
         * Phase 7 (M1): the v2 work id, when the row came from a v2 list. A v2 row
         * has no v1 post id — its `id` is the negative work-id sentinel — so the
         * detail route carries the work id in its own argument and `postId`
         * stays 0. A v1 row passes no workId and the route behaves as before.
         */
        const val ARG_WORK_ID = "workId"
        fun createRoute(postId: Int, autoplay: Boolean = false): String =
            "detail/$postId?autoplay=$autoplay&workId=-1"
        fun createRouteForWork(workId: Long, autoplay: Boolean = false): String =
            "detail/0?autoplay=$autoplay&workId=$workId"
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

    /** The phone's own videos (Movies/ and Download/), listed from MediaStore. */
    object LocalFiles : Screen("local_files")

    /**
     * NAV-4/NAV-5: the catch-all for a deep link that parses to nothing — a
     * `radd://` URI with no known shape. A link that leads nowhere says so,
     * with a way home, instead of silently opening Home as if nothing happened.
     */
    object DeadLink : Screen("dead_link")
}
