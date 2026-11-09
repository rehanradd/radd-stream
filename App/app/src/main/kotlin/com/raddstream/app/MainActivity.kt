package com.raddstream.app

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.Image
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.Surface
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.raddstream.app.brand.Brand
import com.raddstream.app.data.RemoteFeatures
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.data.Telemetry
import com.raddstream.app.network.models.PanelDisclaimer
import com.raddstream.app.network.models.PanelTheme
import com.raddstream.app.repository.CatalogRepository
import com.raddstream.app.ui.navigation.LocalVideoOpen
import com.raddstream.app.ui.navigation.Screen
import com.raddstream.app.ui.navigation.RaddStreamNavGraph
import com.raddstream.app.ui.navigation.StartDestination
import com.raddstream.app.update.InAppUpdate
import com.raddstream.app.ui.navigation.resolveStartDestination
import com.raddstream.app.ui.screens.AnalyticsConsentDialog
import com.raddstream.app.ui.screens.DisclaimerDialog
import com.raddstream.app.ui.screens.MaintenanceScreen
import com.raddstream.app.ui.theme.RaddStreamTheme
import com.raddstream.app.ui.theme.parseAccentHex
import com.raddstream.app.ui.theme.resolveThemeDark
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

/**
 * Single-activity host.
 * Routes an install with no server to setup, one that has a server but has never been asked
 * what it watches to the region screen, and a returning viewer straight to the catalog.
 *
 * This activity also owns the app-wide theme, which is why the wallpaper-colour
 * preference is read *here*: it is the only place where the answer can reach
 * [RaddStreamTheme] before any screen paints.
 *
 * And it is the one door a video file handed over by another app comes through — cold start and
 * warm start alike. Which intent that counts as, and what the file gets called, is
 * [LocalVideoOpen]'s rule, not this activity's; what lives here is the reading of the Intent and
 * the holding of the request until there is a back stack to put it on.
 */
@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    @Inject
    lateinit var serverSettingsRepository: ServerSettingsRepository

    @Inject
    lateinit var catalogRepository: CatalogRepository

    /**
     * A file another app asked us to play, waiting for the graph that can route it. It is
     * composition state on the activity, not a local in [setContent], because the cold-start
     * intent lands before the nav graph exists: the server address is read asynchronously, so
     * the first frame this activity paints is often the spinner, and an open kept only in the
     * composition would be gone by the time there is a back stack to push onto.
     */
    private var pendingLocalOpen by mutableStateOf<LocalVideoOpen?>(null)

    /** Makes two opens of one file two requests; see [LocalVideoOpen.from]. */
    private var localOpenNonce = 0L

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        takeLocalVideoFrom(intent)
        enableEdgeToEdge()
        setContent {
            // The login streak (plan §5 step 19): one record per day this device opens the app.
            // A rotation recreates this activity and re-runs this effect, but recordLoginDay is
            // idempotent within a day, so the second run changes nothing — and a launch that
            // never reaches a screen still counts, because the streak is about opening the app.
            LaunchedEffect(Unit) {
                serverSettingsRepository.recordLoginDay()
            }
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

            // The operator's tab order, mirrored into DataStore by RemoteConfigWatcher.
            // Seeded with an empty list so a cold start shows the bar's own four; a
            // store that cannot answer takes no tab away from anybody.
            val tabsPreference: Flow<List<String>> = remember(serverSettingsRepository) {
                serverSettingsRepository.panelTabs.catch { emit(emptyList()) }
            }
            val operatorTabs by tabsPreference.collectAsState(initial = emptyList())

            // The operator's theme, mirrored into DataStore by RemoteConfigWatcher.
            // Seeded with the app's own defaults (dark, brand accent, hero on) so a
            // cold start paints the app it always painted; a store that cannot
            // answer takes no theme away from anybody.
            val themePreference: Flow<PanelTheme> = remember(serverSettingsRepository) {
                serverSettingsRepository.themeSettings.catch { emit(PanelTheme()) }
            }
            val operatorTheme by themePreference.collectAsState(initial = PanelTheme())

            // The viewer's own autoplay-previews switch (plan §5 step 10): it gates the
            // Home hero alongside the operator's theme flag — either one off stops the
            // carousel. Seeded on, matching the hero's own default.
            val autoplayPreviewsPreference: Flow<Boolean> = remember(serverSettingsRepository) {
                serverSettingsRepository.autoplayPreviews.catch { emit(true) }
            }
            val autoplayPreviews by autoplayPreviewsPreference.collectAsState(initial = true)

            // The operator's disclaimer, mirrored into DataStore by RemoteConfigWatcher,
            // and the version this install has already accepted. The stored value is
            // the panel value; `effective()` resolves the shipped default when the
            // panel has published nothing, so the text is never blank — a cold
            // start shows the default once, exactly as a first run should.
            // `disclaimerSeenVersion` starts null and is filled by the collect
            // below, the same known-flag pattern the analytics answer uses:
            // until the stored version lands, nothing is shown, so a viewer
            // who already accepted never sees the dialog flash for one frame.
            val disclaimerPreference: Flow<PanelDisclaimer> = remember(serverSettingsRepository) {
                serverSettingsRepository.disclaimer.catch { emit(PanelDisclaimer()) }
            }
            val disclaimer by disclaimerPreference.collectAsState(initial = PanelDisclaimer())
            val effectiveDisclaimer = disclaimer.effective()
            var disclaimerSeenVersion by remember { mutableStateOf<Int?>(null) }
            LaunchedEffect(Unit) {
                serverSettingsRepository.disclaimerSeenVersion.collect { disclaimerSeenVersion = it }
            }
            val activityScope = rememberCoroutineScope()

            // Tracking A asks once, the first time the app runs after this
            // build: share anonymous totals, or not. Null means never asked.
            // The answer is collected in a LaunchedEffect rather than a
            // collectAsState so the dialog cannot flash on launch for a
            // viewer who already answered: until the first emission lands,
            // `analyticsConsentKnown` is false and nothing shows.
            var analyticsConsent by remember { mutableStateOf<Boolean?>(null) }
            var analyticsConsentKnown by remember { mutableStateOf(false) }
            LaunchedEffect(Unit) {
                serverSettingsRepository.analyticsConsent.collect { answer ->
                    analyticsConsent = answer
                    analyticsConsentKnown = true
                }
            }

            RaddStreamTheme(
                darkTheme = resolveThemeDark(operatorTheme.mode, isSystemInDarkTheme()),
                dynamicColor = effectiveDynamicColor(dynamicColorRequested, operatorTheme.dynamicColor),
                accent = parseAccentHex(operatorTheme.accent),
            ) {
                var startDestination by remember { mutableStateOf<String?>(null) }
                LaunchedEffect(Unit) {
                    val savedUrl = try {
                        serverSettingsRepository.serverUrl.first()
                    } catch (_: Exception) {
                        null
                    }
                    val hasSavedServer = try {
                        serverSettingsRepository.hasSavedServerUrl.first()
                    } catch (_: Exception) {
                        false
                    }
                    // A fresh install never sees the Setup form when the shipped server
                    // answers: the default is probed twice (one retry) in the background,
                    // and saved only when it answers. A dead default — or an unbranded
                    // build with no default at all — still opens Setup, with the address
                    // held but never shown until the viewer asks for a different server.
                    val defaultReachable: Boolean? = if (savedUrl.isNullOrBlank() || hasSavedServer) {
                        null
                    } else {
                        trySilentDefaultConnect(catalogRepository, savedUrl)
                    }
                    val destination = resolveStartDestination(
                        savedUrl = savedUrl,
                        hasSavedServerUrl = hasSavedServer,
                        defaultServerReachable = defaultReachable,
                        // First install after the server is connected gets one chance to say what
                        // they watch; a store that cannot answer is treated as "already asked",
                        // because onboarding is a convenience and must never become the door.
                        regionUnanswered = regionChoiceUnanswered(serverSettingsRepository),
                    )
                    startDestination = when (destination) {
                        StartDestination.Setup -> Screen.Setup.route
                        StartDestination.Region -> Screen.Region.route
                        StartDestination.Home -> Screen.Home.route
                    }
                }

                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background,
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
                        // Session 120: the wait before the first route used to be
                        // a bare spinner on black, which on a slow first install
                        // reads as a dead app. Branded loading screen instead:
                        // the mark, the name, the spinner.
                        destination == null -> Column(
                            modifier = Modifier.fillMaxSize(),
                            verticalArrangement = Arrangement.Center,
                            horizontalAlignment = Alignment.CenterHorizontally,
                        ) {
                            Image(
                                painter = painterResource(R.drawable.ic_logo_mark),
                                contentDescription = null,
                                modifier = Modifier.size(96.dp),
                            )
                            Text(
                                text = Brand.name,
                                style = MaterialTheme.typography.headlineMedium,
                                color = MaterialTheme.colorScheme.onBackground,
                                modifier = Modifier.padding(top = 16.dp, bottom = 24.dp),
                            )
                            CircularProgressIndicator()
                            Text(
                                text = stringResource(R.string.app_loading),
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(top = 16.dp),
                            )
                        }
                        else -> RaddStreamNavGraph(
                            startDestination = destination,
                            features = operatorFeatures,
                            tabs = operatorTabs,
                            theme = operatorTheme,
                            autoplayPreviews = autoplayPreviews,
                            openRequest = pendingLocalOpen,
                            onOpenConsumed = { pendingLocalOpen = null },
                        )
                    }
                    // The disclaimer outranks every screen but the maintenance
                    // notice above: it is the one thing the viewer must read
                    // before watching, once per published version. It cannot
                    // be dismissed without tapping "I understand" — a
                    // disclaimer you can swipe away unread is not one. The
                    // one other way out is Decline, which says plainly why
                    // and closes the app: agreeing is the price of using it.
                    if (disclaimerSeenVersion != null && disclaimerSeenVersion != effectiveDisclaimer.version) {
                        DisclaimerDialog(
                            disclaimer = effectiveDisclaimer,
                            confirmLabel = "I understand",
                            onConfirm = {
                                activityScope.launch {
                                    serverSettingsRepository.acceptDisclaimer(effectiveDisclaimer.version)
                                }
                            },
                            onDismissRequest = {},
                            dismissLabel = "Decline",
                            onDecline = {
                                Toast.makeText(
                                    this@MainActivity,
                                    "You need to accept the disclaimer to use Radd Stream.",
                                    Toast.LENGTH_LONG,
                                ).show()
                                finish()
                            },
                        )
                    }
                    // Tracking A: the one question before anything is
                    // counted. Both buttons are answers — there is no way to
                    // dismiss it unanswered — and answering refreshes the
                    // telemetry snapshot at once, so a "yes" turns the
                    // headers on without a restart and a "no" leaves the app
                    // exactly as it was.
                    // Session 121 (P-21): the question used to appear over whatever
                    // the first paint was — on a first install, over the genre
                    // picker, before the viewer had seen anything of the app. It
                    // now waits until Home is the destination, so the first thing
                    // a viewer meets is the app, not a question; a first-run
                    // viewer answers it on the next launch instead. (The branded
                    // loading screen from Session 120 already covers the wait
                    // before any route exists.)
                    // Session 122: it also waits for the disclaimer to be
                    // settled — the two dialogs used to stack on a first
                    // install, the analytics question over the terms. The
                    // disclaimer is settled when the stored version equals
                    // the effective one; a null stored version (not yet
                    // read) is not settled.
                    if (analyticsConsentKnown && analyticsConsent == null && destination == Screen.Home.route &&
                        disclaimerSeenVersion == effectiveDisclaimer.version) {
                        AnalyticsConsentDialog(
                            onAccept = {
                                activityScope.launch {
                                    serverSettingsRepository.saveAnalyticsConsent(true)
                                    Telemetry.refresh(serverSettingsRepository)
                                }
                            },
                            onDecline = {
                                activityScope.launch {
                                    serverSettingsRepository.saveAnalyticsConsent(false)
                                    Telemetry.refresh(serverSettingsRepository)
                                }
                            },
                        )
                    }
                }
            }
        }
    }

    override fun onDestroy() {
        // The flexible-update listener lives in InAppUpdate; a leaked Play
        // listener survives the activity, so it is unregistered here.
        InAppUpdate.onDestroy()
        super.onDestroy()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        // The activity is declared `launchMode=singleTop`, so a second file opened from a file
        // manager while the app is alive arrives here instead of starting another activity — and
        // without this the second file a viewer opens would silently stay the first one on screen.
        setIntent(intent)
        takeLocalVideoFrom(intent)
    }

    /**
     * One Intent in, one route out. Nothing is decided here: [LocalVideoOpen] owns which intent
     * becomes a play request, which scheme may be played at all, and what the file is called, so
     * the manifest's advertised filter and this activity's behaviour are the same rule rather
     * than two that have to be kept in step by hand.
     */
    private fun takeLocalVideoFrom(source: Intent?) {
        val data = source?.data ?: return
        val open = LocalVideoOpen.from(
            scheme = data.scheme,
            address = data.toString(),
            mimeType = source.type ?: resolvedType(data),
            lastPathSegment = data.lastPathSegment,
            nonce = ++localOpenNonce,
        ) ?: return
        pendingLocalOpen = open
    }

    /**
     * The provider's own idea of what a `content://` row holds, for the sender that declared no
     * type. A provider this app may not read throws, and an unreadable file is a file we do not
     * play — it is not a reason for another app's Intent to crash this activity before it has
     * painted a frame.
     */
    private fun resolvedType(data: Uri): String? = try {
        contentResolver.getType(data)
    } catch (_: Exception) {
        null
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
 *
 * The panel's theme permission ANDs in as well: the operator can switch dynamic colour off for
 * every phone at once, and a viewer who turned it on still gets the brand scheme until the
 * operator allows it again.
 */
private fun effectiveDynamicColor(storedEnabled: Boolean, panelAllowed: Boolean): Boolean =
    storedEnabled && Brand.dynamicColorAllowed && panelAllowed

/**
 * Two bounded probes of the shipped server, for a fresh install only.
 *
 * `testAndSaveServer` saves the address when it answers, so a fresh install that
 * reaches Home through here has a saved server from then on — the probe runs
 * once per install, never on every cold start. A slow first network can lose
 * one probe, so a failure earns exactly one retry before the caller opens
 * Setup: a slow answer must not become a leaked address on a form. The 15s
 * bound is the whole point: a dead default must not hold the first frame
 * hostage; the OkHttp timeouts underneath are 10s connect / 15s read, so this
 * is the tighter ceiling. A timeout reads as "did not answer" and the caller
 * opens Setup.
 */
private const val SILENT_CONNECT_TIMEOUT_MS = 15_000L

private suspend fun trySilentDefaultConnect(
    catalogRepository: CatalogRepository,
    url: String,
): Boolean {
    repeat(2) {
        val answered = try {
            withTimeoutOrNull(SILENT_CONNECT_TIMEOUT_MS) {
                catalogRepository.testAndSaveServer(url)
            } != null
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            false
        }
        if (answered) return true
    }
    return false
}

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
