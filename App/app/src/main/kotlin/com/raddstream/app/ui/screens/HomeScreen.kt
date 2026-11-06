package com.raddstream.app.ui.screens

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
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
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import com.raddstream.app.brand.Brand
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.raddstream.app.network.models.PanelBroadcast
import com.raddstream.app.ui.components.EmptyState
import com.raddstream.app.ui.components.ErrorState
import com.raddstream.app.ui.components.HeroCarousel
import com.raddstream.app.ui.components.HeroSkeleton
import com.raddstream.app.ui.components.InlineLoadFailure
import com.raddstream.app.ui.components.MediaRail
import com.raddstream.app.ui.components.PosterCard
import com.raddstream.app.ui.components.SectionHeader
import com.raddstream.app.ui.components.SeeAllButton
import com.raddstream.app.ui.components.SkeletonBox
import com.raddstream.app.ui.theme.RaddStreamMark
import com.raddstream.app.viewmodel.HomeSection
import com.raddstream.app.viewmodel.HomeViewModel
import com.raddstream.app.viewmodel.visibleHomeRows

private data class JumpOff(val label: String, val type: String?)

/** Slides in the hero banner. Six is enough to feel like a rail, few enough that the
 *  auto-advance cycle does not outlast attention. */
private const val HERO_LIMIT = 6

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(
    onSearchClick: () -> Unit,
    /** False when the operator's `feature_flags.search` is off: the entry point disappears. */
    searchEnabled: Boolean = true,
    onPostClick: (Int) -> Unit = {},
    onBrowseType: (String?) -> Unit = {},
    onSetupServerClick: () -> Unit = {},
    /** The operator's hero knobs from the panel theme: 0 hides the hero slot. */
    heroMax: Int = HERO_LIMIT,
    heroAutoplay: Boolean = true,
    heroIntervalMs: Long = 5_000L,
    viewModel: HomeViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()
    val context = LocalContext.current

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
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
                                onClick = { onPostClick(tile.post.id) },
                                progressFraction = tile.progressFraction,
                                progressLabel = tile.resumeLabel,
                            )
                        }
                        Spacer(Modifier.height(8.dp))
                    }
                }
                // The banner rides the first rail that actually has rows, so it is real
                // catalog data (freshest additions) and not a hand-picked fake "featured" set.
                // heroMax 0 hides the slot entirely — no carousel, no skeleton — because
                // the operator asked for no hero, not for a hero that never loads.
                if (heroMax > 0) {
                    val heroItems = state.sections.firstOrNull { it.visible }?.items.orEmpty().take(heroMax)
                    if (heroItems.isNotEmpty()) {
                        HeroCarousel(
                            posts = heroItems,
                            onPostClick = onPostClick,
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
                JumpOffRow(onBrowseType = onBrowseType)
                Spacer(Modifier.height(8.dp))

                // At most 10 rows total, CW included: a panel that publishes 12
                // sections does not get 12 rails on a phone, and the first rails win.
                val renderedRows = shownRows.filter { it.visible || it.loading || it.error != null }
                renderedRows.forEach { section ->
                    HomeRailSection(
                        section = section,
                        onPostClick = onPostClick,
                        onSeeAll = { onBrowseType(section.type) },
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
            AppUpdateDialog(
                required = update.required,
                // Only close the dialog once the download actually opened, so a phone
                // with no browser keeps the one-tap path instead of losing it silently.
                onUpdateNow = { if (openDownload(context, update.url)) viewModel.dismissUpdate() },
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
) {
    AlertDialog(
        onDismissRequest = if (required) ({}) else onDismiss,
        icon = { RaddStreamMark(diameter = 40.dp) },
        title = {
            Text(
                text = Brand.copy(
                    if (required) "update_required_title" else "update_title",
                    if (required) "Update required" else "A new build is available",
                ),
                fontWeight = FontWeight.Bold,
            )
        },
        text = {
            Text(
                Brand.copy(
                    if (required) "update_required_message" else "update_message",
                    if (required) {
                        "${Brand.name} needs an update to keep working. Download the new build to continue."
                    } else {
                        "${Brand.name} has published a newer APK. Download it to keep the catalog and player current."
                    },
                    "name" to Brand.name,
                ),
            )
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

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun JumpOffRow(onBrowseType: (String?) -> Unit) {
    val tiles = listOf(
        JumpOff("All", null),
        JumpOff("Movies", "movie"),
        JumpOff("Series", "series"),
        JumpOff("Anime", "anime"),
        JumpOff("Seasons", "complete_season"),
    )
    Column(Modifier.padding(top = 4.dp)) {
        SectionHeader(title = "Browse")
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .horizontalScrollPadding(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            tiles.forEach { tile ->
                Surface(
                    onClick = { onBrowseType(tile.type) },
                    shape = RoundedCornerShape(20.dp),
                    color = MaterialTheme.colorScheme.surfaceVariant,
                    contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
                ) {
                    Text(
                        text = tile.label,
                        style = MaterialTheme.typography.labelLarge,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
                    )
                }
            }
        }
    }
}

private fun Modifier.horizontalScrollPadding(): Modifier = this.padding(horizontal = 16.dp)

@Composable
private fun HomeRailSection(
    section: HomeSection,
    onPostClick: (Int) -> Unit,
    onSeeAll: () -> Unit,
    onRetry: () -> Unit,
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
                Row(
                    modifier = Modifier.padding(horizontal = 16.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    repeat(4) { SkeletonBox(Modifier.height(190.dp).width(132.dp)) }
                }
            }
        }
        section.items.isNotEmpty() -> {
            Column {
                SectionHeader(
                    title = section.title,
                    modifier = Modifier.padding(horizontal = 16.dp),
                    action = { SeeAllButton(onClick = onSeeAll) },
                )
                MediaRail(items = section.items, key = { it.id }) { post ->
                    PosterCard(post = post, onClick = { onPostClick(post.id) })
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
