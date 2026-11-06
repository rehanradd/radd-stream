package com.raddstream.app.ui.navigation

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.vectorResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.raddstream.app.R
import com.raddstream.app.brand.Brand
import com.raddstream.app.data.RemoteFeatures
import com.raddstream.app.network.models.PanelTheme
import com.raddstream.app.network.models.Post
import com.raddstream.app.player.PlayerSessionStore
import com.raddstream.app.ui.screens.BrowseScreen
import com.raddstream.app.ui.screens.CheckInScreen
import com.raddstream.app.ui.screens.CoinsScreen
import com.raddstream.app.ui.screens.DashboardScreen
import com.raddstream.app.ui.screens.DeadLinkScreen
import com.raddstream.app.ui.screens.DetailScreen
import com.raddstream.app.ui.screens.DownloadsScreen
import com.raddstream.app.ui.screens.EmbedWebViewScreen
import com.raddstream.app.ui.screens.HelpScreen
import com.raddstream.app.ui.screens.HomeScreen
import com.raddstream.app.ui.screens.LiveTvScreen
import com.raddstream.app.ui.screens.LocalFilesScreen
import com.raddstream.app.ui.screens.MyListScreen
import com.raddstream.app.ui.screens.PlayerScreen
import com.raddstream.app.ui.screens.ProfileScreen
import com.raddstream.app.ui.screens.RegionSelectionScreen
import com.raddstream.app.ui.screens.SearchScreen
import com.raddstream.app.ui.screens.SettingsScreen
import com.raddstream.app.ui.screens.SetupScreen
import com.raddstream.app.ui.screens.VipUpgradeScreen
import com.raddstream.app.ui.screens.WatchHistoryScreen

private data class BottomNavItem(
    val label: String,
    /** The destination's route, used to tell whether the tab is selected. */
    val route: String,
    val icon: ImageVector,
    /**
     * The address the tab navigates to. Usually the same as [route] — but a
     * destination with an optional argument (Search's `query`) must be
     * navigated to by its plain address, never by the template string:
     * navigating to "search?query={query}" would search for the literal
     * text "{query}".
     */
    val navigateRoute: String = route,
)

/** Test tag on a bottom-nav tab's indicator pill, so the a11y test can measure it directly. */
internal const val BottomNavIndicatorTag = "bottomNavIndicator"

/**
 * Robo run 5: the bottom-nav touch target still measured 32dp — the M3
 * NavigationBarItem's active-indicator pill, not the item itself. Run 4 set
 * the bar to exactly 80dp and pinned the item clickables at 80dp (and that
 * still holds), but Robo keeps measuring the 32dp pill inside the item, so
 * the bar no longer uses NavigationBarItem at all. This tab owns its own
 * clickable — the full 80dp bar height — and its own indicator pill, raised
 * to 48dp so no node in the bar is under the 48dp touch-target floor. The
 * bar is 80dp of content plus the system nav inset (run 6: forcing the bar
 * to exactly 80dp total crushed the tabs to 32dp on a 3-button-nav device,
 * because M3 applies the nav-bars inset inside the bar — see the
 * NavigationBar call below); never fillMaxHeight() on a tab — that expands
 * the bar to fill the screen (run 4). The label keeps M3's labelMedium so
 * the taller pill still fits the bar.
 * Internal so BottomNavTouchTargetTest can pin the pill height directly.
 */
@Composable
internal fun RowScope.BottomNavTab(
    label: String,
    icon: ImageVector,
    selected: Boolean,
    onClick: () -> Unit,
) {
    Box(
        modifier = Modifier
            .weight(1f)
            .height(80.dp)
            .clickable(onClick = onClick, role = Role.Tab)
            // The tab itself carries the spoken name (the SwitchRow pattern):
            // the painted icon and label are silent, so the name is heard
            // exactly once. No mergeDescendants — the pill stays its own
            // node so the test can measure it.
            .semantics { contentDescription = label; this.selected = selected },
        contentAlignment = Alignment.Center,
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            Box(
                modifier = Modifier
                    .size(width = 64.dp, height = 48.dp)
                    .background(
                        color = if (selected) {
                            MaterialTheme.colorScheme.surfaceContainerHighest
                        } else {
                            Color.Transparent
                        },
                        shape = RoundedCornerShape(24.dp),
                    )
                    .testTag(BottomNavIndicatorTag),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    icon,
                    contentDescription = null,
                    tint = if (selected) {
                        MaterialTheme.colorScheme.primary
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                    modifier = Modifier.size(24.dp),
                )
            }
            Text(
                label,
                style = MaterialTheme.typography.labelMedium,
                color = if (selected) {
                    MaterialTheme.colorScheme.primary
                } else {
                    MaterialTheme.colorScheme.onSurfaceVariant
                },
                modifier = Modifier.clearAndSetSemantics { },
            )
        }
    }
}

/**
 * The whole navigable app.
 *
 * [features] is the operator's board, read once by the activity and handed down: the switches
 * have to be obeyed by the tab bar and by the screens' own entry points together, or a hidden
 * tab beside a still-live "Open Downloads" card is a feature that is half removed. The routes
 * themselves stay registered even for a switched-off feature — a back stack that already holds
 * that screen must not name a destination the graph cannot resolve, and a kept file stays
 * playable no matter what the board says about making new ones.
 *
 * [openRequest] is a video file another app asked us to play, already judged by
 * [LocalVideoOpen]; [onOpenConsumed] reports that it has been put on the back stack. The graph
 * does not decide anything about the file — it routes what the activity handed over, on the same
 * `player_local` route a finished download uses.
 *
 * NAV-5: [deepLinkRequest] is a `radd://` link [DeepLinks.parse] read, routed the same way;
 * [unknownDeepLink] is one it could not read, routed to the dead-link destination instead of
 * silently opening Home.
 */

/**
 * Phase 7 (M1): open a row from any list. A v2 row has no v1 post id — its `id`
 * is the negative work-id sentinel — so it opens by work id; a v1 row opens by
 * post id, exactly as before. The sentinel itself must never be navigated to:
 * the detail screen reads it as "no post".
 */
private fun NavHostController.navigateToPost(post: Post, autoplay: Boolean = false) {
    val route = if (post.workId != null) {
        Screen.Detail.createRouteForWork(post.workId, autoplay)
    } else {
        Screen.Detail.createRoute(post.id, autoplay)
    }
    navigate(route)
}

@Composable
fun RaddStreamNavGraph(
    navController: NavHostController = rememberNavController(),
    startDestination: String,
    features: RemoteFeatures = RemoteFeatures(),
    /** The operator's tab order from the panel (`tabs` tuning key), as the activity last received it; empty means "never received", and the bar falls back to its own five. */
    tabs: List<String> = emptyList(),
    /** The operator's theme, for the hero knobs Home reads from it. */
    theme: PanelTheme = PanelTheme(),
    /** The viewer's own autoplay-previews switch (plan §5 step 10): either it or the operator's hero flag being off stops the carousel. */
    autoplayPreviews: Boolean = true,
    openRequest: LocalVideoOpen? = null,
    onOpenConsumed: () -> Unit = {},
    deepLinkRequest: DeepLink? = null,
    onDeepLinkConsumed: () -> Unit = {},
    unknownDeepLink: String? = null,
    onUnknownDeepLinkConsumed: () -> Unit = {},
) {
    val navBackStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = navBackStackEntry?.destination?.route

    // Exactly once per request: the nonce is what makes the same file tapped twice a second
    // request, and clearing it here is what stops a later recomposition from pushing a duplicate
    // copy of the player onto the stack. Single-top for the same reason — a viewer who opens the
    // file that is already playing should stay on it, not stack a second one behind the first.
    LaunchedEffect(openRequest) {
        val request = openRequest ?: return@LaunchedEffect
        navController.navigate(request.route) { launchSingleTop = true }
        onOpenConsumed()
    }

    // NAV-5: a parsed deep link routes exactly once, the same way. Stream links
    // also match the player route's own navDeepLink, so the NavController may
    // already be there — launchSingleTop makes the second navigate a no-op,
    // not a duplicate player. Detail and Browse have no navDeepLink pattern,
    // so this effect is their only way in.
    LaunchedEffect(deepLinkRequest) {
        val request = deepLinkRequest ?: return@LaunchedEffect
        when (request) {
            is DeepLink.Detail -> navController.navigate(Screen.Detail.createRoute(request.postId)) {
                launchSingleTop = true
            }
            is DeepLink.Stream -> navController.navigate(
                Screen.Player.createRoute(request.streamId, request.title),
            ) {
                launchSingleTop = true
            }
            is DeepLink.Browse -> navController.navigate(Screen.Browse.createRoute(request.type)) {
                launchSingleTop = true
            }
        }
        onDeepLinkConsumed()
    }

    // NAV-5: a link that parsed to nothing still goes somewhere — the dead-link
    // destination, which says so with a way home, instead of silently opening
    // Home as if nothing happened.
    LaunchedEffect(unknownDeepLink) {
        if (unknownDeepLink == null) return@LaunchedEffect
        navController.navigate(Screen.DeadLink.route) { launchSingleTop = true }
        onUnknownDeepLinkConsumed()
    }

    // The operator's tab order, resolved against what this build can show: Home is always
    // first, Search only when its feature flag is on, and an empty or all-unknown list falls
    // back to the five tabs this build has always shipped. The routes stay registered even
    // for a tab the operator hid — a back stack that already holds that screen must not name
    // a destination the graph cannot resolve.
    // The five tabs wear the brand's own icons (res/drawable/ic_tab_*.xml,
    // the stroke set from the brand pack — the `?attr/colorControlNormal`
    // tint the pack files carried was stripped on copy-in, because this app
    // has no such attr; the NavigationBarItem tint is the only tint). The
    // vectors are stroke-black; Icon's tint recolours them to the bar's
    // selected/unselected colours, exactly as the Material icons did.
    val bottomNavItems = PanelTabs.resolve(tabs, features.search).map { id ->
        when (id) {
            "live_tv" -> BottomNavItem("Live TV", Screen.LiveTv.route, ImageVector.vectorResource(R.drawable.ic_tab_live_tv))
            "search" -> BottomNavItem("Search", Screen.Search.route, ImageVector.vectorResource(R.drawable.ic_tab_search), navigateRoute = Screen.Search.PLAIN_ROUTE)
            "my_list" -> BottomNavItem("My List", Screen.MyList.route, ImageVector.vectorResource(R.drawable.ic_tab_my_list))
            "settings" -> BottomNavItem("Settings", Screen.Settings.route, ImageVector.vectorResource(R.drawable.ic_tab_settings))
            else -> BottomNavItem("Home", Screen.Home.route, ImageVector.vectorResource(R.drawable.ic_tab_home))
        }
    }

    val showBottomBar = currentRoute in bottomNavItems.map { it.route }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        bottomBar = {
            if (showBottomBar) {
                NavigationBar(
                    containerColor = MaterialTheme.colorScheme.surfaceContainer,
                    // Robo run 6: the bottom-nav touch target STILL measured
                    // 32dp — and the run-5 pill is 48dp, so the pill was never
                    // the measured node. The measured node is the tab itself,
                    // and the cause is the bar's own height: M3 1.3.0's
                    // NavigationBar lays its Row out at minHeight 80dp AND
                    // applies the system navigation-bars inset inside it
                    // (windowInsetsPadding). Forcing the bar to exactly 80dp
                    // (the run-4 fix) leaves the Row 80dp total, so a 48dp
                    // system nav bar (3-button navigation, the Robo device)
                    // eats 48dp of it and the tabs are measured with 32dp of
                    // height — exactly the 80 - 48 the console reports. The
                    // 80dp is the M3 CONTENT height, not the bar's total: the
                    // bar sizes to its content plus the inset, so no height
                    // is forced here and the tabs keep their full 80dp.
                    // Never fillMaxHeight() on a tab — that expands the bar
                    // to fill the screen (run 4).
                ) {
                    bottomNavItems.forEach { item ->
                        val selected = currentRoute == item.route
                        BottomNavTab(
                            label = item.label,
                            icon = item.icon,
                            selected = selected,
                            onClick = {
                                if (currentRoute != item.route) {
                                    navController.navigate(item.navigateRoute) {
                                        popUpTo(Screen.Home.route) {
                                            saveState = true
                                        }
                                        launchSingleTop = true
                                        restoreState = true
                                    }
                                }
                            },
                        )
                    }
                }
            }
        },
    ) { innerPadding ->
        NavHost(
            navController = navController,
            startDestination = startDestination,
            modifier = Modifier.padding(bottom = if (showBottomBar) innerPadding.calculateBottomPadding() else 0.dp),
        ) {
            composable(Screen.Setup.route) {
                SetupScreen(
                    onConnected = {
                        navController.navigate(Screen.Home.route) {
                            popUpTo(Screen.Setup.route) { inclusive = true }
                        }
                    },
                )
            }

            composable(Screen.Region.route) {
                RegionSelectionScreen(
                    onContinue = {
                        // Two entrances, one button. Opened from Settings the
                        // viewer came from a screen that is still behind this
                        // one, so popping just this screen returns them to it
                        // — popping back to Home destroyed the Settings entry
                        // and left the viewer with no way back to the row they
                        // just used (Session 114: the row "disappeared"
                        // because its screen did). On a first install the
                        // region screen IS the whole stack, so there is
                        // nothing to pop and Home is pushed instead, with
                        // this screen leaving for good.
                        if (!navController.popBackStack()) {
                            navController.navigate(Screen.Home.route) {
                                popUpTo(Screen.Region.route) { inclusive = true }
                            }
                        }
                    },
                )
            }

            composable(Screen.Home.route) {
                HomeScreen(
                    onSearchClick = { navController.navigate(Screen.Search.PLAIN_ROUTE) },
                    searchEnabled = features.search,
                    onPostClick = { post -> navController.navigateToPost(post) },
                    // Session 121 (P-26): the hero's Watch Now opens the title and
                    // starts it, instead of only opening the title.
                    onWatchNowClick = { post ->
                        navController.navigateToPost(post, autoplay = true)
                    },
                    onBrowseType = { type -> navController.navigate(Screen.Browse.createRoute(type)) },
                    onSetupServerClick = { navController.navigate(Screen.Setup.route) },
                    onOpenLocalFiles = { navController.navigate(Screen.LocalFiles.route) },
                    onOpenDownloads = { navController.navigate(Screen.Downloads.route) },
                    // Session 123: the Home check-in card opens the standalone
                    // check-in screen — the card claims, the screen shows the week.
                    onOpenCheckIn = { navController.navigate(Screen.CheckIn.route) },
                    // Session 123 (HO-7): a guest's sign-in door is Settings,
                    // where the account card lives.
                    onOpenSignIn = { navController.navigate(Screen.Settings.route) },
                    heroMax = theme.heroMax,
                    heroAutoplay = theme.heroAutoplay && autoplayPreviews,
                    heroIntervalMs = theme.heroIntervalS * 1_000L,
                )
            }

            composable(
                route = Screen.Browse.route,
                arguments = listOf(
                    navArgument(Screen.Browse.ARG_TYPE) {
                        type = NavType.StringType
                        defaultValue = "all"
                    },
                ),
                deepLinks = listOf(
                    androidx.navigation.navDeepLink { uriPattern = Brand.deepLinkUri("browse/{type}") },
                ),
            ) {
                BrowseScreen(
                    onBackClick = { navController.popBackStack() },
                    onPostClick = { post -> navController.navigateToPost(post) },
                )
            }

            composable(
                route = Screen.Search.route,
                arguments = listOf(
                    // An actor tap lands here with the name already filled
                    // in; the plain tab navigates with no argument, so the
                    // default keeps every existing search link working.
                    navArgument(Screen.Search.ARG_QUERY) {
                        type = NavType.StringType
                        defaultValue = ""
                    },
                ),
            ) { backStackEntry ->
                SearchScreen(
                    initialQuery = backStackEntry.arguments?.getString(Screen.Search.ARG_QUERY)?.takeIf { it.isNotBlank() },
                    onPostClick = { post -> navController.navigateToPost(post) },
                    onPlayDirectUrl = { url, title ->
                        // The address is staged, never routed: the player
                        // opens the opaque key and reads the address from
                        // the store (see PlayerSessionStore).
                        val key = PlayerSessionStore.Instance.stageDirectUrl(url)
                        navController.navigate(Screen.Player.createRoute(key, title)) {
                            // A double-tap on Play must not stack two identical
                            // players: one Back would then land on the same
                            // player again and look like Back doing nothing
                            // (Session 114).
                            launchSingleTop = true
                        }
                    },
                )
            }

            composable(Screen.MyList.route) {
                MyListScreen(
                    onPostClick = { post -> navController.navigateToPost(post) },
                    onOpenWatchHistory = { navController.navigate(Screen.WatchHistory.route) },
                )
            }

            composable(Screen.LiveTv.route) {
                LiveTvScreen(
                    onPlayChannel = { streamId, title ->
                        // The same player route a movie uses, addressed by
                        // the server's opaque stream handle — the player
                        // itself is untouched by Live TV.
                        navController.navigate(Screen.Player.createRoute(streamId, title))
                    },
                )
            }

            composable(Screen.Settings.route) {
                SettingsScreen(
                    features = features,
                    onOpenDownloads = { navController.navigate(Screen.Downloads.route) },
                    onOpenVipUpgrade = { navController.navigate(Screen.VipUpgrade.route) },
                    onOpenRegionChoice = { navController.navigate(Screen.Region.route) },
                    // Session 123: the account screens, from the Account card.
                    onOpenDashboard = { navController.navigate(Screen.Dashboard.route) },
                    onOpenProfile = { navController.navigate(Screen.Profile.route) },
                    onOpenCoins = { navController.navigate(Screen.Coins.route) },
                    onOpenHelp = { navController.navigate(Screen.Help.route) },
                    onOpenWatchHistory = { navController.navigate(Screen.WatchHistory.route) },
                )
            }

            composable(Screen.Help.route) {
                HelpScreen(onBackClick = { navController.popBackStack() })
            }

            composable(Screen.WatchHistory.route) {
                WatchHistoryScreen(
                    onBackClick = { navController.popBackStack() },
                    onPostClick = { postId -> navController.navigate(Screen.Detail.createRoute(postId)) },
                )
            }

            composable(Screen.VipUpgrade.route) {
                VipUpgradeScreen(
                    onBackClick = { navController.popBackStack() },
                    // Session 123: the wallet on the VIP screen opens the coins
                    // screen, where the balance and the history live.
                    onOpenCoins = { navController.navigate(Screen.Coins.route) },
                )
            }

            // Session 123: the account screens — the dashboard that answers
            // "where do I stand?", the standalone check-in, the coins, and the
            // profile. None of them is a tab; Settings, Home and VIP link here.
            composable(Screen.Dashboard.route) {
                DashboardScreen(
                    onBackClick = { navController.popBackStack() },
                    onOpenCheckIn = { navController.navigate(Screen.CheckIn.route) },
                    onOpenCoins = { navController.navigate(Screen.Coins.route) },
                    onOpenProfile = { navController.navigate(Screen.Profile.route) },
                    onOpenVipUpgrade = { navController.navigate(Screen.VipUpgrade.route) },
                )
            }

            composable(Screen.CheckIn.route) {
                CheckInScreen(onBackClick = { navController.popBackStack() })
            }

            composable(Screen.Coins.route) {
                CoinsScreen(onBackClick = { navController.popBackStack() })
            }

            composable(Screen.Profile.route) {
                ProfileScreen(
                    onBackClick = { navController.popBackStack() },
                    onOpenDashboard = { navController.navigate(Screen.Dashboard.route) },
                    onOpenCoins = { navController.navigate(Screen.Coins.route) },
                )
            }

            composable(Screen.Downloads.route) {
                DownloadsScreen(
                    onBackClick = { navController.popBackStack() },
                    onPlay = { item ->
                        item.streamHandle?.let {
                            navController.navigate(Screen.Player.createRoute(it, item.title)) {
                                launchSingleTop = true
                            }
                        }
                    },
                    onPlayLocal = { uri, title ->
                        navController.navigate(Screen.PlayerLocal.createRoute(uri, title)) {
                            launchSingleTop = true
                        }
                    },
                    onOpenLocalFiles = { navController.navigate(Screen.LocalFiles.route) },
                )
            }

            composable(Screen.LocalFiles.route) {
                LocalFilesScreen(
                    onBackClick = { navController.popBackStack() },
                    onPlayLocal = { uri, title ->
                        navController.navigate(Screen.PlayerLocal.createRoute(uri, title)) {
                            launchSingleTop = true
                        }
                    },
                )
            }

            composable(
                route = Screen.Detail.route,
                arguments = listOf(
                    navArgument(Screen.Detail.ARG_POST_ID) { type = NavType.IntType },
                    // Phase 7 (M1): the v2 work id — a default of -1 keeps every
                    // existing detail link (deep links included) working.
                    navArgument(Screen.Detail.ARG_WORK_ID) {
                        type = NavType.LongType
                        defaultValue = -1L
                    },
                    // Session 121 (P-26): the hero's Watch Now opens the title and starts
                    // it — an optional flag, so every existing detail link still works.
                    navArgument(Screen.Detail.ARG_AUTOPLAY) {
                        type = NavType.BoolType
                        defaultValue = false
                    },
                ),
                deepLinks = listOf(
                    androidx.navigation.navDeepLink { uriPattern = Brand.deepLinkUri("detail/{postId}") },
                ),
            ) { backStackEntry ->
                DetailScreen(
                    autoplay = backStackEntry.arguments?.getBoolean(Screen.Detail.ARG_AUTOPLAY) ?: false,
                    onBackClick = { navController.popBackStack() },
                    onPlayStream = { streamId, title ->
                        navController.navigate(Screen.Player.createRoute(streamId, title)) {
                            launchSingleTop = true
                        }
                    },
                    onOpenProviderPage = { streamId, title ->
                        navController.navigate(Screen.Embed.createRoute(streamId, title)) {
                            launchSingleTop = true
                        }
                    },
                    onOpenDownloads = { navController.navigate(Screen.Downloads.route) },
                    onOpenVipUpgrade = { navController.navigate(Screen.VipUpgrade.route) },
                    onActorClick = { actor ->
                        navController.navigate(Screen.Search.createRoute(actor))
                    },
                )
            }

            composable(
                route = Screen.Player.route,
                arguments = listOf(
                    navArgument(Screen.Player.ARG_STREAM_ID) { type = NavType.StringType },
                    navArgument(Screen.Player.ARG_TITLE) { type = NavType.StringType },
                ),
                deepLinks = listOf(
                    // radd://stream/<handle>/<title> — a shared link opens the
                    // player for one handle, with the same args the in-app
                    // route carries, so the decode below is identical.
                    androidx.navigation.navDeepLink { uriPattern = Brand.deepLinkUri("stream/{streamId}/{title}") },
                ),
            ) { backStackEntry ->
                val encodedHandle = backStackEntry.arguments?.getString(Screen.Player.ARG_STREAM_ID) ?: ""
                val encodedTitle = backStackEntry.arguments?.getString(Screen.Player.ARG_TITLE) ?: ""
                val streamId = Screen.Player.decodeStreamId(encodedHandle)
                val title = Screen.Player.decodeTitle(encodedTitle)

                PlayerScreen(
                    streamId = streamId,
                    title = title,
                    onBackClick = { navController.popBackStack() },
                    onPlayNextEpisode = { _, nextPostId, season, episode ->
                        if (nextPostId != null && nextPostId > 0) {
                            navController.navigate(Screen.Detail.createRoute(nextPostId)) {
                                launchSingleTop = true
                                popUpTo(Screen.Player.route) { inclusive = true }
                            }
                        }
                    },
                    // SC §3: an actor tapped on the pause strip searches them,
                    // the same route the detail screen's cast chips take.
                    onActorClick = { actor ->
                        navController.navigate(Screen.Search.createRoute(actor)) {
                            launchSingleTop = true
                        }
                    },
                    // NAV-4: the expired-link card's way home.
                    onHomeClick = {
                        navController.navigate(Screen.Home.route) {
                            launchSingleTop = true
                        }
                    },
                )
            }

            /**
             * The provider's own page, for a link the server says is a page and not a file. The
             * route carries the OPAQUE HANDLE only — see [Screen.Embed] for why an address never
             * belongs in a back stack, and `EmbedWebViewScreen` for what this screen does not do.
             */
            composable(
                route = Screen.Embed.route,
                arguments = listOf(
                    navArgument(Screen.Embed.ARG_STREAM_ID) { type = NavType.StringType },
                    navArgument(Screen.Embed.ARG_TITLE) { type = NavType.StringType },
                ),
            ) {
                EmbedWebViewScreen(onBack = { navController.popBackStack() })
            }

            composable(
                route = Screen.PlayerLocal.route,
                arguments = listOf(
                    navArgument(Screen.PlayerLocal.ARG_URI) { type = NavType.StringType },
                    navArgument(Screen.PlayerLocal.ARG_TITLE) { type = NavType.StringType },
                ),
            ) { backStackEntry ->
                val localUri = Screen.PlayerLocal.decode(
                    backStackEntry.arguments?.getString(Screen.PlayerLocal.ARG_URI).orEmpty(),
                )
                val title = Screen.PlayerLocal.decode(
                    backStackEntry.arguments?.getString(Screen.PlayerLocal.ARG_TITLE).orEmpty(),
                )
                PlayerScreen(
                    streamId = "",
                    title = title,
                    localUri = localUri,
                    onBackClick = { navController.popBackStack() },
                )
            }

            // NAV-5: the catch-all for a deep link that parsed to nothing.
            composable(route = Screen.DeadLink.route) {
                DeadLinkScreen(
                    onHomeClick = {
                        navController.navigate(Screen.Home.route) {
                            launchSingleTop = true
                        }
                    },
                )
            }
        }
    }
}
