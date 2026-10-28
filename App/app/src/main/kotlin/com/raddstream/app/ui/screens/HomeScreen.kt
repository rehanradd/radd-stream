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
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
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
                // The banner rides the first rail that actually has rows, so it is real
                // catalog data (freshest additions) and not a hand-picked fake "featured" set.
                val heroItems = state.sections.firstOrNull { it.visible }?.items.orEmpty().take(HERO_LIMIT)
                if (heroItems.isNotEmpty()) {
                    HeroCarousel(posts = heroItems, onPostClick = onPostClick)
                    Spacer(Modifier.height(12.dp))
                } else if (state.sections.any { it.loading }) {
                    // Hold the hero's footprint while the first rail lands, so the page
                    // never flashes a bare background and then jumps when it fills in.
                    HeroSkeleton()
                    Spacer(Modifier.height(12.dp))
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
                JumpOffRow(onBrowseType = onBrowseType)
                Spacer(Modifier.height(8.dp))

                state.sections.filter { it.visible || it.loading || it.error != null }.forEach { section ->
                    HomeRailSection(
                        section = section,
                        onPostClick = onPostClick,
                        onSeeAll = { onBrowseType(section.type) },
                        onRetry = { viewModel.retrySection(section.key) },
                    )
                }
                Spacer(Modifier.height(24.dp))
            }
        }

        state.updateNotice?.let { update ->
            AppUpdateDialog(
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

@Composable
private fun AppUpdateDialog(onUpdateNow: () -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        icon = { RaddStreamMark(diameter = 40.dp) },
        title = {
            Text(
                text = Brand.copy("update_title", "A new build is available"),
                fontWeight = FontWeight.Bold,
            )
        },
        text = {
            Text(
                Brand.copy(
                    "update_message",
                    "${Brand.name} has published a newer APK. Download it to keep the catalog and player current.",
                    "name" to Brand.name,
                ),
            )
        },
        confirmButton = {
            Button(onClick = onUpdateNow) {
                Text(Brand.copy("update_now", "Update Now"), fontWeight = FontWeight.SemiBold)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Later") }
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
