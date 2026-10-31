package com.raddstream.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Surface
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import com.raddstream.app.brand.Brand
import com.raddstream.app.data.RemoteFeatures
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.ui.navigation.Screen
import com.raddstream.app.ui.navigation.RaddStreamNavGraph
import com.raddstream.app.ui.screens.MaintenanceScreen
import com.raddstream.app.ui.theme.RaddStreamTheme
import com.raddstream.app.ui.theme.BackgroundDark
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.first

/**
 * Single-activity host.
 * Routes an install with no server to setup, one that has a server but has never been asked
 * what it watches to the region screen, and a returning viewer straight to the catalog.
 *
 * This activity also owns the app-wide theme, which is why the wallpaper-colour
 * preference is read *here*: it is the only place where the answer can reach
 * [RaddStreamTheme] before any screen paints.
 */
@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    @Inject
    lateinit var serverSettingsRepository: ServerSettingsRepository

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            // Collected as composition state, not snapshotted once: flipping the Settings switch
            // must recompose the theme live, and a `first()` here would freeze whatever the store
            // said at cold start and make the toggle look broken until the process restarted.
            //
            // `collectAsState` rather than `collectAsStateWithLifecycle` because this project never
            // declares lifecycle-runtime-compose (only lifecycle-viewmodel-compose, whose POM lists
            // runtime-compose under <dependencyManagement>, which does not put it on the classpath).
            // Every screen here uses collectAsState; matching them beats relying on an artifact that
            // is not in the version catalog.
            //
            // The seed is Brand.schemeDynamicColorDefault, i.e. exactly what RaddStreamTheme would
            // have painted before this collection existed — a slow store changes nothing on frame 1.
            val brandSeed = Brand.schemeDynamicColorDefault
            val dynamicColorPreference: Flow<Boolean> = remember(serverSettingsRepository) {
                serverSettingsRepository.dynamicColorEnabled
                    // A DataStore read that throws (corrupt file, disk failure) must not kill the
                    // activity mid-setContent. Handled the same way as the try/catch around
                    // serverUrl.first() below: hold the brand default, let the app open.
                    // What is NOT protected: the exception is swallowed here, so a store that keeps
                    // failing means this toggle can never take effect for the life of the process,
                    // and nothing on screen will ever say so out loud.
                    .catch { emit(brandSeed) }
            }
            val dynamicColorRequested by dynamicColorPreference.collectAsState(initial = brandSeed)

            // The operator's maintenance switch, mirrored into DataStore by RemoteConfigWatcher.
            // Seeded `false` so a cold start paints the app it always painted; the flag can only
            // ever take the user out of the catalog, never hold them at a spinner while it loads.
            val maintenancePreference: Flow<Boolean> = remember(serverSettingsRepository) {
                serverSettingsRepository.maintenanceMode.catch { emit(false) }
            }
            val underMaintenance by maintenancePreference.collectAsState(initial = false)

            // The operator's feature board, as one snapshot for the same reason it is written as
            // one DataStore edit: a tab bar that hides Search while the Settings card still offers
            // Downloads has answered two different server replies. Seeded all-on, so a cold start
            // paints the app every deployment has always shipped, and a store that cannot answer
            // takes features away from nobody.
            val featuresPreference: Flow<RemoteFeatures> = remember(serverSettingsRepository) {
                serverSettingsRepository.remoteFeatures.catch { emit(RemoteFeatures()) }
            }
            val operatorFeatures by featuresPreference.collectAsState(initial = RemoteFeatures())

            RaddStreamTheme(dynamicColor = effectiveDynamicColor(dynamicColorRequested)) {
                var startDestination by remember { mutableStateOf<String?>(null) }
                LaunchedEffect(Unit) {
                    val savedUrl = try {
                        serverSettingsRepository.serverUrl.first()
                    } catch (_: Exception) {
                        null
                    }
                    startDestination = when {
                        savedUrl.isNullOrBlank() -> Screen.Setup.route
                        // First install after the server is connected gets one chance to say what
                        // they watch; a store that cannot answer is treated as "already asked",
                        // because onboarding is a convenience and must never become the door.
                        regionChoiceUnanswered(serverSettingsRepository) -> Screen.Region.route
                        else -> Screen.Home.route
                    }
                }

                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = BackgroundDark,
                ) {
                    var changingServer by remember { mutableStateOf(false) }
                    LaunchedEffect(underMaintenance) {
                        // Leave the escape behind as soon as the notice clears, so a server that
                        // goes back into maintenance cannot be outrun by a stale flag here.
                        if (!underMaintenance) changingServer = false
                    }
                    val destination = startDestination
                    when {
                        // The notice outranks routing — but it must not outrank the address field.
                        // The inventory (M-MON-06) asks for navigation blocked "except Settings",
                        // and this is the screen that changes which server the app talks to, so a
                        // wrongly flagged deployment stays survivable instead of becoming a brick.
                        underMaintenance && !changingServer -> MaintenanceScreen(
                            onChangeServer = {
                                startDestination = Screen.Setup.route
                                changingServer = true
                            },
                        )
                        destination == null -> Box(
                            modifier = Modifier.fillMaxSize(),
                            contentAlignment = Alignment.Center,
                        ) {
                            CircularProgressIndicator()
                        }
                        else -> RaddStreamNavGraph(
                            startDestination = destination,
                            features = operatorFeatures,
                        )
                    }
                }
            }
        }
    }
}

/**
 * The switch asks; [Brand.dynamicColorAllowed] decides.
 *
 * Effective colour = `storedEnabled && brandAllows`, and the AND is the whole point: with
 * `features.dynamic_color=false` in brand.properties the identity is pinned, so a viewer who
 * flips "Dynamic colour from wallpaper" gets nothing back. That is not a bug to fix here —
 * Theme.kt's policy block says the wallpaper must not get to repaint `primary`, and a user
 * preference that outranked the brand file would be the same violation from the other side.
 *
 * What this does NOT protect: [Brand.schemeDynamicColorDefault] stays the theme's own default, so
 * a re-skin shipping `features.dynamic_color=true` makes this same toggle live without any code
 * change. Android 12+ is still enforced inside RaddStreamTheme; pre-S devices get the brand scheme
 * no matter what both flags say.
 */
private fun effectiveDynamicColor(storedEnabled: Boolean): Boolean =
    storedEnabled && Brand.dynamicColorAllowed

/**
 * Whether this install has never been through the region screen.
 *
 * `userRegion` cannot answer that on its own: it normalizes an absent key to
 * [com.raddstream.app.data.UserRegion.DEFAULT], so "nobody chose" and "a viewer chose the default
 * card" are the same stored value. The separate recorded-flag is what distinguishes them, and it
 * is the only reason a first install opens once and never again.
 *
 * A store that throws reads as "already asked". Onboarding decides which print leads a list; it is
 * not required to reach the catalog, so a failing read must not become a wall.
 */
private suspend fun regionChoiceUnanswered(settings: ServerSettingsRepository): Boolean =
    try {
        !settings.regionChoiceRecorded.first()
    } catch (_: Exception) {
        false
    }
