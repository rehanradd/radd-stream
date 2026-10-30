package com.raddstream.app.ui.navigation

import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
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
import androidx.compose.ui.unit.dp
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.raddstream.app.brand.Brand
import com.raddstream.app.data.RemoteFeatures
import com.raddstream.app.ui.screens.BrowseScreen
import com.raddstream.app.ui.screens.DetailScreen
import com.raddstream.app.ui.screens.DownloadsScreen
import com.raddstream.app.ui.screens.EmbedWebViewScreen
import com.raddstream.app.ui.screens.HomeScreen
import com.raddstream.app.ui.screens.MyListScreen
import com.raddstream.app.ui.screens.PlayerScreen
import com.raddstream.app.ui.screens.RegionSelectionScreen
import com.raddstream.app.ui.screens.SearchScreen
import com.raddstream.app.ui.screens.SettingsScreen
import com.raddstream.app.ui.screens.SetupScreen
import com.raddstream.app.ui.screens.VipUpgradeScreen
import com.raddstream.app.ui.theme.AccentPrimary
import com.raddstream.app.ui.theme.BackgroundDark
import com.raddstream.app.ui.theme.OnSurfaceMuted
import com.raddstream.app.ui.theme.SurfaceDark
import com.raddstream.app.ui.theme.SurfaceVariantDark

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

    val bottomNavItems = buildList {
        add(BottomNavItem("Home", Screen.Home.route, Icons.Default.Home))
        if (features.search) add(BottomNavItem("Search", Screen.Search.route, Icons.Default.Search))
        add(BottomNavItem("My List", Screen.MyList.route, Icons.Default.Favorite))
        add(BottomNavItem("Settings", Screen.Settings.route, Icons.Default.Settings))
    }

    val showBottomBar = currentRoute in bottomNavItems.map { it.route }

    Scaffold(
        containerColor = BackgroundDark,
        bottomBar = {
            if (showBottomBar) {
                NavigationBar(
                    containerColor = SurfaceDark,
                ) {
                    bottomNavItems.forEach { item ->
                        val selected = currentRoute == item.route
                        NavigationBarItem(
                            icon = { Icon(item.icon, contentDescription = item.label) },
                            label = { Text(item.label) },
                            selected = selected,
                            colors = NavigationBarItemDefaults.colors(
                                selectedIconColor = AccentPrimary,
                                selectedTextColor = AccentPrimary,
                                unselectedIconColor = OnSurfaceMuted,
                                unselectedTextColor = OnSurfaceMuted,
                                indicatorColor = SurfaceVariantDark,
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
                        // Two entrances, one button. Opened from Settings the viewer already has a
                        // catalog behind this screen, so popping back to it keeps one Home entry;
                        // on a first install the region screen IS the whole stack, and there is
                        // nothing to pop, so Home is pushed and this screen leaves for good.
                        if (!navController.popBackStack(Screen.Home.route, inclusive = false)) {
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
                            navController.navigate(Screen.Player.createRoute(it, item.title))
                        }
                    },
                    onPlayLocal = { uri, title ->
                        navController.navigate(Screen.PlayerLocal.createRoute(uri, title))
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
                        navController.navigate(Screen.Player.createRoute(streamId, title))
                    },
                    onOpenProviderPage = { streamId, title ->
                        navController.navigate(Screen.Embed.createRoute(streamId, title))
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
