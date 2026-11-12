package com.raddstream.app.ui.screens

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.text.format.Formatter
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import com.google.android.play.core.install.model.ActivityResult as PlayCoreActivityResult
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.EnterTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.slideInVertically
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import com.raddstream.app.brand.Brand
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.raddstream.app.network.models.FacetsResponse
import com.raddstream.app.network.models.PanelBroadcast
import com.raddstream.app.network.models.Post
import com.raddstream.app.ui.components.CatalogImage
import com.raddstream.app.ui.components.EmptyState
import com.raddstream.app.ui.components.ErrorState
import com.raddstream.app.ui.components.HeroCarousel
import com.raddstream.app.ui.components.HeroSkeleton
import com.raddstream.app.ui.components.InlineLoadFailure
import com.raddstream.app.ui.components.MediaRail
import com.raddstream.app.ui.components.PosterCard
import com.raddstream.app.ui.components.PosterRailSkeleton
import com.raddstream.app.ui.components.RaddDialogTitle
import com.raddstream.app.ui.components.SectionHeader
import com.raddstream.app.ui.components.SeeAllButton
import com.raddstream.app.ui.components.UserWords
import com.raddstream.app.ui.components.rememberReduceMotion
import com.raddstream.app.ui.theme.RaddMotion
import com.raddstream.app.ui.theme.RaddStreamMark
import com.raddstream.app.update.InAppUpdate
import com.raddstream.app.viewmodel.HomeSection
import com.raddstream.app.viewmodel.HomeViewModel
import com.raddstream.app.viewmodel.homeSyncLine
import com.raddstream.app.viewmodel.visibleHomeRows

private data class JumpOff(val label: String, val type: String?)

/** Slides in the hero banner. Six is enough to feel like a rail, few enough that the
 *  auto-advance cycle does not outlast attention. */
private const val HERO_LIMIT = 6

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(
    onSearchClick: () -> Unit,
    /** The search bar's submit: a query goes straight to Search with it applied. */
    onSearchQuery: (String) -> Unit = { onSearchClick() },
    /** False when the operator's `feature_flags.search` is off: the entry point disappears. */
    searchEnabled: Boolean = true,
    onPostClick: (Post) -> Unit = {},
    /** Session 121 (P-26): the hero's Watch Now — opens the title and starts it. */
    onWatchNowClick: (Post) -> Unit = onPostClick,
    onBrowseType: (String?) -> Unit = {},
    /**
     * A facet chip's jump-off: the genre, industry and/or language to land
     * on Search with already applied. Null means "no filter of that kind".
     */
    onFacetSelected: (genre: String?, industry: String?, language: String?) -> Unit = { _, _, _ -> },
    onSetupServerClick: () -> Unit = {},
    /** The phone's own videos (Movies/ and Download/), listed from MediaStore. */
    onOpenLocalFiles: () -> Unit = {},
    /** Kept-for-offline titles (Media Vault). */
    onOpenDownloads: () -> Unit = {},
    /** Session 123: the check-in card opens the standalone check-in screen. */
    onOpenCheckIn: () -> Unit = {},
    /** Session 123 (HO-7): a guest's way into an account — Settings, where sign-in lives. */
    onOpenSignIn: () -> Unit = {},
    /** The operator's hero knobs from the panel theme: 0 hides the hero slot. */
    heroMax: Int = HERO_LIMIT,
    heroAutoplay: Boolean = true,
    heroIntervalMs: Long = 5_000L,
    viewModel: HomeViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()
    val context = LocalContext.current
    val snackbarHostState = remember { SnackbarHostState() }

    // Phase 7 (D1): one tap removes a Continue Watching tile; the way back is
    // the snackbar, not a dialog the viewer had to answer first. Dismissing
    // the snackbar without tapping Undo lets the removal stand.
    LaunchedEffect(state.removedResumeTitle) {
        val title = state.removedResumeTitle ?: return@LaunchedEffect
        val result = snackbarHostState.showSnackbar(
            message = "Removed $title from Continue Watching",
            actionLabel = "Undo",
            duration = SnackbarDuration.Long,
        )
        if (result == SnackbarResult.ActionPerformed) {
            viewModel.undoRemoveFromContinueWatching()
        } else {
            viewModel.clearRemovedResumeNotice()
        }
    }

    // Play Core in-app updates: the launcher the update flow returns
    // through. `pendingFlexibleUpdateUrl` holds the URL of a flexible flow
    // already running — if Play reports it failed, the download page is the
    // way back, and the dialog was already dismissed when the flow started,
    // so the URL has to live here, not in state. A cancelled immediate flow
    // needs nothing: its dialog was never dismissed, so it is still there.
    var pendingFlexibleUpdateUrl by remember { mutableStateOf<String?>(null) }
    val updateLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.StartIntentSenderForResult(),
    ) { result ->
        val url = pendingFlexibleUpdateUrl
        pendingFlexibleUpdateUrl = null
        if (url != null && result.resultCode == PlayCoreActivityResult.RESULT_IN_APP_UPDATE_FAILED) {
            openDownload(context, url)
        }
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = {
            TopAppBar(
                title = { Text(Brand.copy("home_title", Brand.name), fontWeight = FontWeight.Bold) },
                actions = {
                    if (searchEnabled) {
                        IconButton(onClick = onSearchClick) {
                            Icon(Icons.Default.Search, contentDescription = "Search catalog")
                        }
                    }
                    IconButton(onClick = viewModel::refresh) {
                        Icon(Icons.Default.Refresh, contentDescription = "Refresh catalog")
                    }
                },
            )
        },
    ) { contentPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(contentPadding)
                .verticalScroll(rememberScrollState()),
        ) {
            if (state.isRefreshing) {
                LinearProgressIndicator(Modifier.fillMaxWidth())
            }

            // Search first: a plain movie-search bar (audit #17, reworked
            // 2026-11-12: the browser identity is dropped — this searches the
            // catalog only, it takes no address and opens no web page). The
            // viewer types here, and Enter opens Search with the query
            // applied. The top-bar icon stays as the empty-search door, and
            // the bar hides with the operator's search flag, exactly like
            // the icon does.
            if (searchEnabled) {
                var homeQuery by remember { mutableStateOf("") }
                SearchField(
                    query = homeQuery,
                    onQueryChanged = { homeQuery = it },
                    onSubmit = { onSearchQuery(homeQuery) },
                    modifier = Modifier.padding(horizontal = 16.dp),
                    label = "Search movies and shows",
                )
                Spacer(Modifier.height(12.dp))
            }

            // Gap A5: the sync/status line — how fresh the rows below are, or
            // that they are saved rows on an offline phone. Nothing until Home
            // has ever loaded, so a first launch never dates an empty page.
            homeSyncLine(state.lastHomeSyncMs, state.isOffline, System.currentTimeMillis())?.let { line ->
                Row(
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = line,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.weight(1f),
                    )
                    // P1-H6: the top-bar refresh icon had no visible meaning —
                    // a mystery circular arrow. The sync line now carries a
                    // plain "Refresh" button next to the freshness it refreshes.
                    TextButton(onClick = viewModel::refresh) { Text("Refresh") }
                }
                Spacer(Modifier.height(8.dp))
            }

            // The operator's channel to every phone: a broadcast shows above the
            // catalog, even when the catalog itself failed to load — that is
            // exactly when the operator has something to say.
            state.broadcasts.forEach { broadcast ->
                BroadcastBanner(
                    broadcast = broadcast,
                    onDismiss = { viewModel.dismissBroadcast(broadcast.id) },
                )
                Spacer(Modifier.height(8.dp))
            }

            // Fatal error only when *every* rail failed and none has data to show.
            val anyVisible = state.sections.any { it.visible }
            if (state.fatal != null && !anyVisible) {
                ErrorState(
                    message = state.fatal ?: "Server did not respond.",
                    onRetry = viewModel::refresh,
                    // The address is the one thing a person can fix themselves, and
                    // Settings is four taps away. Offer it where the failure is seen.
                    secondaryLabel = "Set up a server",
                    onSecondary = onSetupServerClick,
                )
            } else {
                // Continue Watching is first and pinned: it is the one rail
                // this device owns outright, and the research rule is that
                // Home opens on it — the hero carousel is discovery, not the
                // first thing. The hero still rides the first rail that has
                // rows, only now it rides behind the rail that remembers.
                val shownRows = visibleHomeRows(state.sections, state.continueWatching.isNotEmpty())
                val hasSaved = state.continueWatching.isNotEmpty() || anyVisible
                if (state.isOffline && hasSaved) {
                    OfflineBanner()
                    Spacer(Modifier.height(8.dp))
                }
                if (state.continueWatching.isNotEmpty()) {
                    Column {
                        SectionHeader(
                            title = "Continue watching",
                            modifier = Modifier.padding(horizontal = 16.dp),
                        )
                        // Keyed on the scope, not the work: two rows of the same series are two
                        // different episodes, and a duplicate key would crash the rail.
                        MediaRail(
                            items = state.continueWatching,
                            key = { "${it.post.id}|${it.season}|${it.episode}" },
                        ) { tile ->
                            PosterCard(
                                post = tile.post,
                                onClick = { onPostClick(tile.post) },
                                progressFraction = tile.progressFraction,
                                progressLabel = tile.resumeLabel,
                                // Phase 7 (D1): the × removes this scope from
                                // Continue Watching — server row first, then
                                // the local rows, with Undo on the snackbar.
                                onRemove = { viewModel.removeFromContinueWatching(tile) },
                            )
                        }
                        Spacer(Modifier.height(8.dp))
                    }
                }
                // The banner rides the first rail that actually has rows, so it is real
                // catalog data (freshest additions) and not a hand-picked fake "featured" set.
                // heroMax 0 hides the slot entirely — no carousel, no skeleton — because
                // the operator asked for no hero, not for a hero that never loads.
                // HO-1: the hero IS that rail's presentation, so its posters are
                // de-duplicated out of the rail below — the same six titles must
                // not appear twice on one screen.
                val heroSection = if (heroMax > 0) state.sections.firstOrNull { it.visible } else null
                val heroItems = heroSection?.items.orEmpty().take(heroMax)
                if (heroMax > 0) {
                    if (heroItems.isNotEmpty()) {
                        HeroCarousel(
                            posts = heroItems,
                            onPostClick = onPostClick,
                            onWatchNow = { post -> onWatchNowClick(post) },
                            isFavorite = { post ->
                                post.id in state.favoriteIds ||
                                    (post.workRef != null && post.workRef in state.favoriteWorkRefs)
                            },
                            onToggleFavorite = { post -> viewModel.toggleFavorite(post) },
                            autoplay = heroAutoplay,
                            intervalMs = heroIntervalMs,
                        )
                        Spacer(Modifier.height(12.dp))
                    } else if (state.sections.any { it.loading }) {
                        // Hold the hero's footprint while the first rail lands, so the page
                        // never flashes a bare background and then jumps when it fills in.
                        HeroSkeleton()
                        Spacer(Modifier.height(12.dp))
                    }
                }
                // Gap A6: the first-run card now rides BELOW the hero — a
                // new viewer meets a movie first, and the picks are still
                // the first thing that asks anything of them.
                if (state.showPickThree) {
                    PickThreeCard(
                        candidates = state.pickThreeCandidates,
                        isFavorite = { post ->
                            post.id in state.favoriteIds ||
                                (post.workRef != null && post.workRef in state.favoriteWorkRefs)
                        },
                        onToggleFavorite = { post -> viewModel.toggleFavorite(post) },
                        onPostClick = onPostClick,
                        onDismiss = viewModel::dismissPickThree,
                    )
                    Spacer(Modifier.height(8.dp))
                }

                // P0-3 / P1-H1: the coins economy no longer owns the top of
                // Home. The wallet lives on the CheckIn / VIP screens; Home
                // keeps at most this one-line nudge, below the hero.
                if (state.streakLadder.isNotEmpty()) {
                    CheckInNudge(
                        streakCount = state.streakCount,
                        serverStreak = state.serverStreak,
                        streakLadder = state.streakLadder,
                        coinBalance = state.coinBalance,
                        signedIn = state.signedIn,
                        claimedToday = state.claimedToday,
                        isClaiming = state.isClaiming,
                        claimMessage = state.claimMessage,
                        onClaim = viewModel::claimDailyLogin,
                        onOpenCheckIn = onOpenCheckIn,
                        onOpenSignIn = onOpenSignIn,
                    )
                    Spacer(Modifier.height(12.dp))
                }

                // Your library, below the hero where it can still be seen:
                // the phone's own videos, and downloads.
                if (searchEnabled) {
                    LibraryStrip(
                        onOpenLocalFiles = onOpenLocalFiles,
                        onOpenDownloads = onOpenDownloads,
                    )
                    Spacer(Modifier.height(8.dp))
                }

                // The free trial note, as one dismissible line below the
                // hero instead of a card above it. A dismissed note never
                // returns.
                state.trialDaysRemaining?.let { days ->
                    TrialNoteLine(
                        daysRemaining = days,
                        onDismiss = viewModel::dismissTrialNote,
                    )
                    Spacer(Modifier.height(8.dp))
                }

                // P1-H3: one "Browse" row, not two near-identical chip rows.
                BrowseSection(
                    facets = state.facets,
                    onBrowseType = onBrowseType,
                    onFacetSelected = onFacetSelected,
                )
                Spacer(Modifier.height(8.dp))

                // At most 10 rows total, CW included: a panel that publishes 12
                // sections does not get 12 rails on a phone, and the first rails win.
                // Audit #18: the same title never appears twice on Home. The seen
                // set is seeded with Continue Watching and the hero, so a rail
                // never repeats a tile or a hero poster; HO-1 (hero out of its
                // own rail) is now a special case of the same rule, by work
                // identity — not by row id, because one film filed twice has
                // two row ids.
                var seenWorks = state.continueWatching
                    .map { UserWords.workKey(it.post.workRef, it.post.displayTitle, it.post.year) }
                    .toSet() + heroItems.map { UserWords.workKey(it.workRef, it.displayTitle, it.year) }
                val renderedRows = shownRows.filter { it.visible || it.loading || it.error != null }
                    .map { section ->
                        val (kept, next) = UserWords.dedupeAcrossRails(
                            section.items,
                            seenWorks,
                        ) { post -> UserWords.workKey(post.workRef, post.displayTitle, post.year) }
                        seenWorks = next
                        section.copy(items = kept)
                    }
                renderedRows.forEachIndexed { index, section ->
                    HomeRailSection(
                        section = section,
                        index = index,
                        onPostClick = onPostClick,
                        onSeeAll = { onBrowseType(section.type) },
                        // A sorted rail has no Browse equivalent (Browse takes a
                        // type but no sort), so "See all" would silently re-sort
                        // it to freshest-first. Offer it only where the order
                        // survives the jump.
                        showSeeAll = section.browseEquivalent,
                        onRetry = { viewModel.retrySection(section.key) },
                    )
                }
                // A successful empty load is a blank page today: no rails, no
                // error, nothing to tap. Say so, and point at the one fix the
                // viewer can do — the server address in Settings.
                if (renderedRows.isEmpty() && state.continueWatching.isEmpty() &&
                    state.sections.none { it.loading } && state.fatal == null
                ) {
                    EmptyState(
                        title = "Nothing here yet",
                        message = "This catalog has no titles to show. Check your server in Settings.",
                        action = {
                            OutlinedButton(onClick = onSetupServerClick) {
                                Text("Set up a server")
                            }
                        },
                    )
                }
                Spacer(Modifier.height(24.dp))
            }
        }

        state.updateNotice?.let { update ->
            // A required update the viewer walked away from mid-flow
            // restarts itself instead of asking for another tap.
            LaunchedEffect(update.url, update.required) {
                if (update.required) {
                    InAppUpdate.resumeImmediateUpdateIfNeeded(context, updateLauncher) { }
                }
            }
            AppUpdateDialog(
                required = update.required,
                sizeBytes = update.sizeBytes,
                // Play Core first, download page when Play has nothing:
                // a sideloaded build always takes the download page, and
                // that is the live path until there is a Play listing. The
                // dialog dismisses only once the viewer is on their way —
                // a flexible flow dismisses when Play takes over (the
                // download runs in the background), a download dismisses
                // when the page opens, and an immediate flow never
                // dismisses: if the viewer cancels it, the dialog must
                // still be there, because a required update has no "Later".
                onUpdateNow = {
                    InAppUpdate.startUpdate(
                        context = context,
                        launcher = updateLauncher,
                        required = update.required,
                        downloadUrl = update.url,
                        onPlayFlowStarted = {
                            if (!update.required) {
                                pendingFlexibleUpdateUrl = update.url
                                viewModel.dismissUpdate()
                            }
                        },
                        onDownloadOpened = { viewModel.dismissUpdate() },
                    )
                },
                onDismiss = viewModel::dismissUpdate,
            )
        }
    }
}

/**
 * The operator's published APK is opened by the system browser/download manager via
 * ACTION_VIEW. Installing stays the platform's job — this app never asks for
 * REQUEST_INSTALL_PACKAGES and never starts an install itself.
 */
private fun openDownload(context: Context, url: String): Boolean = try {
    context.startActivity(
        Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
    )
    true
} catch (_: ActivityNotFoundException) {
    Toast.makeText(context, "No browser is available to open this download.", Toast.LENGTH_LONG).show()
    false
}

/**
 * One announcement from the admin panel. The severity picks the container: the
 * operator's urgent note reads urgent on the phone too, and an info note stays
 * quiet. A broadcast is plain text from the panel — never a link, never a button —
 * so there is nothing to tap except the dismiss.
 */
/**
 * The offline strip. It only renders when something saved is on screen —
 * an offline phone with nothing saved gets the error state, not a banner
 * over a blank page. The copy says what is true: the rails below are the
 * network's and may have failed, while Continue Watching is this device's
 * own saved titles and still plays.
 */
@Composable
private fun OfflineBanner() {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp),
        shape = RoundedCornerShape(12.dp),
        color = MaterialTheme.colorScheme.surfaceVariant,
    ) {
        Text(
            text = "You are offline — only titles saved on this device are available.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
        )
    }
}

/**
 * Gap A6 — the first-run "Pick 3 you like" card. Three real titles from the
 * first rail that has them; the heart saves each one to My List, the poster
 * opens the title, and "Not now" retires the card. Nothing here promises
 * personalisation — the picks ARE the start of My List, and the card says
 * exactly that.
 */
@Composable
private fun PickThreeCard(
    candidates: List<Post>,
    isFavorite: (Post) -> Boolean,
    onToggleFavorite: (Post) -> Unit,
    onPostClick: (Post) -> Unit,
    onDismiss: () -> Unit,
) {
    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
        shape = RoundedCornerShape(16.dp),
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
    ) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(
                text = "Pick 3 you like",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = "Tap the heart on three titles to start your My List.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            candidates.forEach { post ->
                val title = post.cleanTitle?.takeIf { it.isNotBlank() } ?: post.title
                val saved = isFavorite(post)
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                    modifier = Modifier.fillMaxWidth()
                        .clickable(onClick = { onPostClick(post) }, onClickLabel = "Open $title"),
                ) {
                    CatalogImage(
                        url = post.posterUrl,
                        contentDescription = null,
                        modifier = Modifier.size(width = 48.dp, height = 72.dp)
                            .clip(RoundedCornerShape(8.dp)),
                        fallbackLabel = title,
                    )
                    Column(Modifier.weight(1f)) {
                        Text(
                            text = title,
                            style = MaterialTheme.typography.bodyMedium,
                            fontWeight = FontWeight.SemiBold,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                        val subtitle = listOfNotNull(
                            post.year?.takeIf { it > 0 }?.toString(),
                            post.typeLabel,
                        ).joinToString(" · ")
                        if (subtitle.isNotBlank()) {
                            Text(
                                text = subtitle,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                    }
                    IconButton(onClick = { onToggleFavorite(post) }) {
                        Icon(
                            imageVector = if (saved) Icons.Default.Favorite else Icons.Default.FavoriteBorder,
                            contentDescription = if (saved) {
                                "Remove $title from My List"
                            } else {
                                "Save $title to My List"
                            },
                            tint = if (saved) {
                                MaterialTheme.colorScheme.secondary
                            } else {
                                MaterialTheme.colorScheme.onSurfaceVariant
                            },
                        )
                    }
                }
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                TextButton(onClick = onDismiss) { Text("Not now") }
            }
        }
    }
}

/**
 * UI-fix P0-3: the trial note as one dismissible line, not a card. The free
 * trial is granted silently; without this line the viewer loses VIP features
 * after 3 days with no prior explanation. A dismissed note never returns.
 */
@Composable
private fun TrialNoteLine(daysRemaining: Int, onDismiss: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = if (daysRemaining == 1) {
                "Free VIP: 1 day left — after that, free playback stays at 720p."
            } else {
                "Free VIP: $daysRemaining days left — after that, free playback stays at 720p."
            },
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.weight(1f),
        )
        IconButton(onClick = onDismiss) {
            Icon(
                Icons.Default.Close,
                contentDescription = "Dismiss trial note",
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun BroadcastBanner(broadcast: PanelBroadcast, onDismiss: () -> Unit) {
    val scheme = MaterialTheme.colorScheme
    val (container, onContainer) = when (broadcast.severity.lowercase()) {
        "urgent", "critical" -> scheme.errorContainer to scheme.onErrorContainer
        "warning" -> scheme.tertiaryContainer to scheme.onTertiaryContainer
        else -> scheme.primaryContainer to scheme.onPrimaryContainer
    }
    Card(
        colors = CardDefaults.cardColors(containerColor = container),
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(start = 16.dp, top = 12.dp, bottom = 12.dp, end = 4.dp),
            verticalAlignment = Alignment.Top,
        ) {
            Column(Modifier.weight(1f)) {
                Text(
                    broadcast.title,
                    style = MaterialTheme.typography.titleSmall,
                    color = onContainer,
                )
                if (broadcast.body.isNotBlank()) {
                    Spacer(Modifier.height(2.dp))
                    Text(
                        broadcast.body,
                        style = MaterialTheme.typography.bodySmall,
                        color = onContainer,
                    )
                }
            }
            IconButton(onClick = onDismiss) {
                Icon(
                    Icons.Default.Close,
                    contentDescription = "Dismiss announcement",
                    tint = onContainer,
                )
            }
        }
    }
}

@Composable
/**
 * The update dialog. A required update — this build is below the operator's
 * minimum — offers no "Later" and cannot be dismissed: the viewer cannot
 * keep using a build the operator has withdrawn.
 */
private fun AppUpdateDialog(
    required: Boolean,
    onUpdateNow: () -> Unit,
    onDismiss: () -> Unit,
    sizeBytes: Long = 0,
) {
    AlertDialog(
        onDismissRequest = if (required) ({}) else onDismiss,
        icon = { RaddStreamMark(diameter = 40.dp) },
        title = {
            // D-2: one dialog title style everywhere — display family,
            // semibold, 20sp.
            RaddDialogTitle(
                text = Brand.copy(
                    if (required) "update_required_title" else "update_title",
                    if (required) "Update required" else "A new build is available",
                ),
            )
        },
        text = {
            Column {
                Text(
                    Brand.copy(
                        if (required) "update_required_message" else "update_message",
                        if (required) {
                            "${Brand.name} needs an update to keep working. Download the new version to continue."
                        } else {
                            "${Brand.name} has published a newer version. Download it to keep everything current."
                        },
                        "name" to Brand.name,
                    ),
                )
                // A viewer on mobile data wants to know what the tap costs
                // before tapping it. No size published, no line — an absent
                // number is not a zero-byte download.
                if (sizeBytes > 0) {
                    Text(
                        text = "Download size: ${Formatter.formatShortFileSize(LocalContext.current, sizeBytes)}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(top = 8.dp),
                    )
                }
            }
        },
        confirmButton = {
            Button(onClick = onUpdateNow) {
                Text(Brand.copy("update_now", "Update Now"), fontWeight = FontWeight.SemiBold)
            }
        },
        dismissButton = if (required) {
            null
        } else {
            {
                TextButton(onClick = onDismiss) { Text("Later") }
            }
        },
        containerColor = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(28.dp),
    )
}

/**
 * The check-in card's day line, as a pure function so the wording is pinned
 * by a test (HO-6): the day number is the server's claimed count, never the
 * device's open count; until the server answers, no day number is printed
 * at all; a guest reads the honest local wording.
 */
internal fun checkInDayLine(
    signedIn: Boolean,
    serverStreak: Int?,
    streakCount: Int,
    targetDays: Int,
): String = when {
    signedIn && serverStreak != null ->
        "Day $serverStreak of $targetDays — claim today's coins to keep the streak going."
    signedIn ->
        "Claim today's coins to keep your streak going."
    else ->
        "You've opened the app $streakCount days in a row."
}

/**
 * The claim button's label (HO-8): today's pay from the server's ladder at
 * the next claimable day. No ladder value, no amount promised — the button
 * falls back to the plain wording instead of inventing a number.
 */
internal fun claimButtonLabel(
    serverStreak: Int?,
    streakLadder: Map<Int, Int>,
    isClaiming: Boolean,
): String {
    if (isClaiming) return "Claiming…"
    val todayDay = (serverStreak ?: 0) + 1
    val todayCoins = streakLadder[todayDay] ?: return "Claim today's coins"
    return "Claim $todayCoins coins for Day $todayDay"
}

/**
 * UI-fix P1-H1: the daily check-in as one line, not a wallet card. Home
 * keeps at most this nudge; the wallet, the streak ladder and the claim
 * shop live on the CheckIn screen, which the row opens. The wording rules
 * still hold (HO-6/HO-8, pinned by HomeCheckInTextTest): the day number is
 * the server's claimed count, never the device's open count, and the claim
 * button states the amount today pays from the server's ladder.
 */
@Composable
private fun CheckInNudge(
    streakCount: Int,
    serverStreak: Int?,
    streakLadder: Map<Int, Int>,
    coinBalance: Int,
    signedIn: Boolean,
    claimedToday: Boolean,
    isClaiming: Boolean,
    claimMessage: String?,
    onClaim: () -> Unit,
    onOpenCheckIn: () -> Unit = {},
    onOpenSignIn: () -> Unit = {},
) {
    val targetDays = streakLadder.keys.maxOrNull() ?: 7
    Surface(
        onClick = onOpenCheckIn,
        shape = RoundedCornerShape(16.dp),
        color = MaterialTheme.colorScheme.surfaceVariant,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Icon(Icons.Default.DateRange, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(
                    text = "Daily check-in",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    text = when {
                        !signedIn -> "Sign in to claim your coins."
                        claimedToday -> claimMessage ?: "Claimed for today."
                        signedIn && serverStreak != null ->
                            "Day $serverStreak of $targetDays · $coinBalance coins in your wallet."
                        else -> checkInDayLine(signedIn, serverStreak, streakCount, targetDays)
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            when {
                !signedIn -> {
                    Button(onClick = onOpenSignIn) { Text("Sign in") }
                }
                claimedToday -> {
                    Text(
                        text = "Claimed",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.primary,
                    )
                }
                else -> {
                    Button(onClick = onClaim, enabled = !isClaiming) {
                        Text(claimButtonLabel(serverStreak, streakLadder, isClaiming))
                    }
                }
            }
        }
    }
}

/**
 * Your library: the phone's own videos, and kept downloads. Two doors, both
 * inside the app — no pasted-link door, no web browsing.
 */
@Composable
internal fun LibraryStrip(
    onOpenLocalFiles: () -> Unit,
    onOpenDownloads: () -> Unit,
) {
    Column(Modifier.padding(top = 4.dp)) {
        // Audit #15: every section heading carries the 16 dp phone margin —
        // this one used to start at x=0 with its "Y" cut off.
        SectionHeader(title = "Your library", modifier = Modifier.padding(horizontal = 16.dp))
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            LibraryTile(
                label = "On this phone",
                icon = Icons.Default.Folder,
                onClick = onOpenLocalFiles,
                modifier = Modifier.weight(1f),
            )
            LibraryTile(
                label = "Downloads",
                icon = Icons.Default.Download,
                onClick = onOpenDownloads,
                modifier = Modifier.weight(1f),
            )
        }
    }
}

@Composable
private fun LibraryTile(
    label: String,
    icon: ImageVector,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        onClick = onClick,
        shape = RoundedCornerShape(16.dp),
        color = MaterialTheme.colorScheme.surfaceVariant,
        contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = modifier,
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 12.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Icon(icon, contentDescription = null)
            Text(
                text = label,
                style = MaterialTheme.typography.labelMedium,
                textAlign = TextAlign.Center,
            )
        }
    }
}

/**
 * UI-fix P1-H3/H4/H5: one "Browse" row, not two near-identical chip rows
 * ("Browse by genre" over "Browse by type"). Type chips first, then the
 * catalog's own facet chips — genres, industries, and languages (the server
 * already serves `language=`; the chips waited for a Search language filter
 * to land on, and it has now). "Seasons" is a catalog ingest state, not
 * something a viewer browses for — it reads "Complete series" here and in
 * Search. Internal so HomeSectionMarginsTest can pin the 16dp margin.
 */
@Composable
internal fun BrowseSection(
    facets: FacetsResponse?,
    onBrowseType: (String?) -> Unit,
    onFacetSelected: (genre: String?, industry: String?, language: String?) -> Unit,
) {
    val chips = remember(facets) {
        val genreChips = facets?.genres.orEmpty()
            .filter { it.count > 0 }
            .map { FacetChip(label = "${it.label} · ${it.count}", genre = it.key, industry = null, language = null) }
        val industryChips = facets?.industries.orEmpty()
            .filter { it.count > 0 }
            .map { FacetChip(label = "${it.label} · ${it.count}", genre = null, industry = it.key, language = null) }
        val languageChips = facets?.languages.orEmpty()
            .filter { it.count > 0 }
            .map { FacetChip(label = "${it.label} · ${it.count}", genre = null, industry = null, language = it.key) }
        genreChips + industryChips + languageChips
    }
    Column(Modifier.padding(top = 4.dp)) {
        // Audit #15: every section heading carries the 16 dp phone margin.
        SectionHeader(title = "Browse", modifier = Modifier.padding(horizontal = 16.dp))
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState())
                .horizontalScrollPadding(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            browseTypeTiles.forEach { tile ->
                Surface(
                    onClick = { onBrowseType(tile.type) },
                    shape = RoundedCornerShape(20.dp),
                    color = MaterialTheme.colorScheme.surfaceVariant,
                    contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
                ) {
                    Text(
                        text = tile.label,
                        style = MaterialTheme.typography.labelLarge,
                        // E-T4: 14dp of vertical padding takes the tile to >= 48dp.
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp),
                    )
                }
            }
        }
        if (chips.isNotEmpty()) {
            Spacer(Modifier.height(8.dp))
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState())
                    .horizontalScrollPadding(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                chips.forEach { chip ->
                    Surface(
                        onClick = { onFacetSelected(chip.genre, chip.industry, chip.language) },
                        shape = RoundedCornerShape(20.dp),
                        color = MaterialTheme.colorScheme.surfaceVariant,
                        contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
                    ) {
                        Text(
                            text = chip.label,
                            style = MaterialTheme.typography.labelLarge,
                            modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp),
                        )
                    }
                }
            }
        }
    }
}

private data class FacetChip(val label: String, val genre: String?, val industry: String?, val language: String?)

/** The browse type jump-offs. "Complete series" is the viewer's word for `complete_season`. */
private val browseTypeTiles = listOf(
    JumpOff("All", null),
    JumpOff("Movies", "movie"),
    JumpOff("Series", "series"),
    JumpOff("Anime", "anime"),
    JumpOff("Complete series", "complete_season"),
)

private fun Modifier.horizontalScrollPadding(): Modifier = this.padding(horizontal = 16.dp)

@Composable
private fun HomeRailSection(
    section: HomeSection,
    index: Int = 0,
    onPostClick: (Post) -> Unit,
    onSeeAll: () -> Unit,
    showSeeAll: Boolean = true,
    onRetry: () -> Unit,
) {
    // UI-fix P1-X1: rails arrive staggered (index * 60 ms, fade + a short
    // rise — the Region screen's index * 90 pattern, extended to rails).
    // Reduced-motion users get a plain fade, never the rise.
    val reduceMotion = rememberReduceMotion()
    AnimatedVisibility(
        visible = true,
        enter = fadeIn(
            animationSpec = tween(
                durationMillis = RaddMotion.DurationDefault,
                delayMillis = index * 60,
            ),
        ) + if (reduceMotion) {
            EnterTransition.None
        } else {
            slideInVertically(
                initialOffsetY = { it / 4 },
                animationSpec = tween(
                    durationMillis = RaddMotion.DurationDefault,
                    delayMillis = index * 60,
                    easing = RaddMotion.EmphasizedDecelerate,
                ),
            )
        },
    ) {
    when {
        section.error != null && section.items.isEmpty() -> {
            Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp)) {
                SectionHeader(title = section.title)
                Text(
                    text = section.error ?: "This row could not load.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(8.dp))
                OutlinedButton(onClick = onRetry) { Text("Retry") }
            }
        }
        section.loading && section.items.isEmpty() -> {
            Column {
                SectionHeader(title = section.title, modifier = Modifier.padding(horizontal = 16.dp))
                PosterRailSkeleton()
            }
        }
        section.items.isNotEmpty() -> {
            Column {
                SectionHeader(
                    title = section.title,
                    modifier = Modifier.padding(horizontal = 16.dp),
                    // Robo run 6: every rail's "See all" announced identically.
                    // The button speaks its section, so Movies and Series are
                    // distinct; the painted text stays the short "See all".
                    // A sorted rail has no Browse equivalent (Browse takes a
                    // type but no sort), so it gets no "See all" at all.
                    action = if (showSeeAll) {
                        { SeeAllButton(onClick = onSeeAll, contentDescription = "See all ${section.title}") }
                    } else {
                        null
                    },
                )
                MediaRail(items = section.items, key = { it.id }) { post ->
                    PosterCard(post = post, onClick = { onPostClick(post) })
                }
                // The rows here are real and from this page; the refresh that failed is a
                // separate fact and has to be said, or the screen claims a freshness it
                // does not have.
                section.refreshFailure?.let { reason ->
                    InlineLoadFailure(message = reason, onRetry = onRetry)
                }
                Spacer(Modifier.height(8.dp))
            }
        }
    }
    }
}
