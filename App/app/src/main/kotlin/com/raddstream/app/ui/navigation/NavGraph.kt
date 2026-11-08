package com.raddstream.app.ui.navigation

import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.vectorResource
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
import com.raddstream.app.player.PlayerSessionStore
import com.raddstream.app.ui.screens.BrowseScreen
import com.raddstream.app.ui.screens.DetailScreen
import com.raddstream.app.ui.screens.DownloadsScreen
import com.raddstream.app.ui.screens.EmbedWebViewScreen
import com.raddstream.app.ui.screens.HomeScreen
import com.raddstream.app.ui.screens.LocalFilesScreen
import com.raddstream.app.ui.screens.MyListScreen
import com.raddstream.app.ui.screens.PlayerScreen
import com.raddstream.app.ui.screens.RegionSelectionScreen
import com.raddstream.app.ui.screens.SearchScreen
import com.raddstream.app.ui.screens.SettingsScreen
import com.raddstream.app.ui.screens.SetupScreen
import com.raddstream.app.ui.screens.VipUpgradeScreen

private data class BottomNavItem(
    val label: String,
    val route: String,
    val icon: ImageVector,
)

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
 */
@Composable
fun RaddStreamNavGraph(
    navController: NavHostController = rememberNavController(),
    startDestination: String,
    features: RemoteFeatures = RemoteFeatures(),
    /** The operator's tab order from the panel (`tabs` tuning key), as the activity last received it; empty means "never received", and the bar falls back to its own four. */
    tabs: List<String> = emptyList(),
    /** The operator's theme, for the hero knobs Home reads from it. */
    theme: PanelTheme = PanelTheme(),
    /** The viewer's own autoplay-previews switch (plan §5 step 10): either it or the operator's hero flag being off stops the carousel. */
    autoplayPreviews: Boolean = true,
    openRequest: LocalVideoOpen? = null,
    onOpenConsumed: () -> Unit = {},
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

    // The operator's tab order, resolved against what this build can show: Home is always
    // first, Search only when its feature flag is on, and an empty or all-unknown list falls
    // back to the four tabs this build has always shipped. The routes stay registered even
    // for a tab the operator hid — a back stack that already holds that screen must not name
    // a destination the graph cannot resolve.
    // The four tabs wear the brand's own icons (res/drawable/ic_tab_*.xml,
    // the stroke set from the brand pack — the `?attr/colorControlNormal`
    // tint the pack files carried was stripped on copy-in, because this app
    // has no such attr; the NavigationBarItem tint is the only tint). The
    // vectors are stroke-black; Icon's tint recolours them to the bar's
    // selected/unselected colours, exactly as the Material icons did.
    val bottomNavItems = PanelTabs.resolve(tabs, features.search).map { id ->
        when (id) {
            "search" -> BottomNavItem("Search", Screen.Search.route, ImageVector.vectorResource(R.drawable.ic_tab_search))
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
                ) {
                    bottomNavItems.forEach { item ->
                        val selected = currentRoute == item.route
                        NavigationBarItem(
                            icon = { Icon(item.icon, contentDescription = item.label) },
                            label = { Text(item.label) },
                            selected = selected,
                            colors = NavigationBarItemDefaults.colors(
                                selectedIconColor = MaterialTheme.colorScheme.primary,
                                selectedTextColor = MaterialTheme.colorScheme.primary,
                                unselectedIconColor = MaterialTheme.colorScheme.onSurfaceVariant,
                                unselectedTextColor = MaterialTheme.colorScheme.onSurfaceVariant,
                                indicatorColor = MaterialTheme.colorScheme.surfaceContainerHighest,
                            ),
                            onClick = {
                                if (currentRoute != item.route) {
                                    navController.navigate(item.route) {
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
                    onSearchClick = { navController.navigate(Screen.Search.route) },
                    searchEnabled = features.search,
                    onPostClick = { postId -> navController.navigate(Screen.Detail.createRoute(postId)) },
                    onBrowseType = { type -> navController.navigate(Screen.Browse.createRoute(type)) },
                    onSetupServerClick = { navController.navigate(Screen.Setup.route) },
                    onOpenLocalFiles = { navController.navigate(Screen.LocalFiles.route) },
                    onOpenDownloads = { navController.navigate(Screen.Downloads.route) },
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
                    onPostClick = { postId -> navController.navigate(Screen.Detail.createRoute(postId)) },
                )
            }

            composable(Screen.Search.route) {
                SearchScreen(
                    onBackClick = { navController.popBackStack() },
                    onPostClick = { postId -> navController.navigate(Screen.Detail.createRoute(postId)) },
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
                    onPostClick = { postId -> navController.navigate(Screen.Detail.createRoute(postId)) },
                )
            }

            composable(Screen.Settings.route) {
                SettingsScreen(
                    features = features,
                    onOpenDownloads = { navController.navigate(Screen.Downloads.route) },
                    onOpenVipUpgrade = { navController.navigate(Screen.VipUpgrade.route) },
                    onOpenRegionChoice = { navController.navigate(Screen.Region.route) },
                )
            }

            composable(Screen.VipUpgrade.route) {
                VipUpgradeScreen(onBackClick = { navController.popBackStack() })
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
                ),
                deepLinks = listOf(
                    androidx.navigation.navDeepLink { uriPattern = Brand.deepLinkUri("detail/{postId}") },
                ),
            ) {
                DetailScreen(
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
        }
    }
}
