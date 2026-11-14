package com.raddstream.app.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.raddstream.app.network.models.LiveTvChannel
import com.raddstream.app.ui.components.CatalogGridColumns
import com.raddstream.app.ui.components.CatalogImage
import com.raddstream.app.ui.components.EmptyState
import com.raddstream.app.ui.components.ErrorState
import com.raddstream.app.ui.components.PosterGridSkeleton
import com.raddstream.app.ui.components.raddFilterChipColors
import com.raddstream.app.ui.layout.CardGeometry
import com.raddstream.app.viewmodel.LiveTvViewModel

/**
 * The Live TV tab: a category-first channel grid, in the same shape as the
 * catalog grids (category chips on top, a logo grid below, search inside the
 * tab). There is no EPG time-grid in v1 — no EPG data source is wired for
 * these channels, and a grid of invented times would be a lie — and no
 * favourites yet, because favourites are a posts system, not a channels one.
 *
 * A tap plays the channel through the EXISTING player, addressed by the
 * server's opaque `stream_id` handle — the same route a movie uses. No raw
 * URL and no host name is ever shown, stored or routed here. A channel the
 * server reports dead answers the player's own unavailable state; nothing
 * on this screen ever fakes a play.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LiveTvScreen(
    onPlayChannel: (streamId: String, title: String) -> Unit,
    viewModel: LiveTvViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                // CL-7, same as Settings: the title says "Live TV" and so does
                // its nav tab — the title is paint, not a second announcement.
                title = { Text("Live TV", modifier = Modifier.clearAndSetSemantics { }) },
            )
        },
    ) { contentPadding ->
        when {
            state.isLoading && state.channels.isEmpty() -> PosterGridSkeleton(
                modifier = Modifier.fillMaxSize().padding(contentPadding),
            )
            // Audit #13: a down server with a saved list still shows the
            // list (with a notice, below) — the error owns the screen only
            // when there is nothing at all to show.
            state.error != null && state.channels.isEmpty() -> ErrorState(
                title = "Live TV isn't available",
                message = state.error ?: "Could not load live channels.",
                onRetry = { viewModel.refresh() },
                modifier = Modifier.fillMaxSize().padding(contentPadding),
            )
            state.channels.isEmpty() -> EmptyState(
                title = "No live channels right now",
                message = "Live channels will appear here when they are available.",
                modifier = Modifier.fillMaxSize().padding(contentPadding),
            )
            else -> Column(Modifier.fillMaxSize().padding(contentPadding)) {
                // Audit #13/#14: the cached list says so, in plain words,
                // with one tap to retry — never a raw code, never a dead tab.
                if (state.error != null) {
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Text(
                            text = if (state.showingCached) {
                                "Showing the last channel list — it may be out of date. ${state.error}"
                            } else {
                                state.error ?: "Could not load live channels."
                            },
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.weight(1f),
                        )
                        TextButton(onClick = { viewModel.refresh() }) { Text("Retry") }
                    }
                }
                OutlinedTextField(
                    value = state.query,
                    onValueChange = viewModel::onQueryChanged,
                    // Audit #33: a label AND a placeholder with the same text
                    // leaves the hint floating above the typed text. The
                    // placeholder alone vanishes on the first character; the
                    // accessible name rides on semantics instead.
                    placeholder = { Text("Search channels") },
                    leadingIcon = {
                        Icon(
                            Icons.Default.Search,
                            contentDescription = null,
                        )
                    },
                    trailingIcon = {
                        if (state.query.isNotEmpty()) {
                            IconButton(onClick = { viewModel.onQueryChanged("") }) {
                                Icon(
                                    Icons.Default.Close,
                                    contentDescription = "Clear search",
                                )
                            }
                        }
                    },
                    singleLine = true,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 4.dp)
                        .semantics { contentDescription = "Search channels" },
                )
                LazyRow(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 4.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    contentPadding = PaddingValues(end = 16.dp),
                ) {
                    item {
                        FilterChip(
                            colors = raddFilterChipColors(),
                            selected = state.selectedCategory == null,
                            onClick = { viewModel.onCategorySelected(null) },
                            label = { Text("All") },
                            // Audit #54: a FilterChip is 32 dp tall — the touch-target floor is 48 dp, so the chip itself carries it.
                            modifier = Modifier.heightIn(min = 48.dp),
                        )
                    }
                    items(state.categories) { category ->
                        FilterChip(
                            colors = raddFilterChipColors(),
                            selected = state.selectedCategory == category,
                            onClick = { viewModel.onCategorySelected(category) },
                            label = { Text(categoryLabel(category)) },
                            // Audit #54: a FilterChip is 32 dp tall — the touch-target floor is 48 dp, so the chip itself carries it.
                            modifier = Modifier.heightIn(min = 48.dp),
                        )
                    }
                }
                if (state.visibleChannels.isEmpty()) {
                    EmptyState(
                        title = "No channels match",
                        message = if (state.query.isNotBlank()) {
                            "Nothing named \"${state.query}\" is on live TV right now."
                        } else {
                            "Nothing in this category is on live TV right now."
                        },
                        modifier = Modifier.fillMaxWidth(),
                    )
                } else {
                    LazyVerticalGrid(
                        columns = CatalogGridColumns,
                        modifier = Modifier.fillMaxSize(),
                        contentPadding = PaddingValues(top = 8.dp, bottom = 24.dp, start = 16.dp, end = 16.dp),
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                        verticalArrangement = Arrangement.spacedBy(14.dp),
                    ) {
                        items(state.visibleChannels, key = { it.id }) { channel ->
                            LiveTvChannelCard(
                                channel = channel,
                                onClick = { onPlayChannel(channel.streamId, channel.name) },
                            )
                        }
                    }
                }
            }
        }
    }
}

/** The server's category id ("news") as a chip label ("News"). */
private fun categoryLabel(category: String): String =
    category.replaceFirstChar { it.uppercase() }

/**
 * The server's country code as a readable name. The registry writes ISO
 * codes ("PK", "IN") and "INTL" for the international set — two-letter
 * codes on a card are alphabet soup, and a viewer should not need a
 * geography lesson to know which country's channel this is. Unknown codes
 * pass through untouched, never guessed at.
 */
internal fun countryLabel(code: String?): String? {
    if (code.isNullOrBlank()) return null
    return when (code.trim().uppercase()) {
        "PK" -> "Pakistan"
        "IN" -> "India"
        "INTL" -> "International"
        "US" -> "USA"
        "GB", "UK" -> "UK"
        "AE" -> "UAE"
        "SA" -> "Saudi Arabia"
        "BD" -> "Bangladesh"
        "LK" -> "Sri Lanka"
        "NP" -> "Nepal"
        "AF" -> "Afghanistan"
        "TR" -> "Turkey"
        "IR" -> "Iran"
        "EG" -> "Egypt"
        else -> code.trim()
    }
}

@Composable
private fun LiveTvChannelCard(
    channel: LiveTvChannel,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    // Robo run 2: every card announced its name three times (logo description,
    // name text, and the "LIVE" badge on every card) — the same words on all
    // ~18 channels. One sentence per card; the logo, badge and texts are paint.
    val a11y = listOfNotNull(
        "${channel.name}, live",
        categoryLabel(channel.category),
        countryLabel(channel.country),
    ).joinToString(" · ")
    Card(
        onClick = onClick,
        modifier = modifier.semantics { contentDescription = a11y },
    ) {
        Column {
            Box(
                // F11 (Batch B): logos are letterboxed, not cropped. The old
                // 16:9 Crop box cut square logos down to a strip and stretched
                // wide ones, so no two cards' logos were the same size. Fit
                // shows every logo whole on one neutral plate.
                modifier = Modifier
                    .fillMaxWidth()
                    .aspectRatio(CardGeometry.WIDE_ART_ASPECT)
                    .background(MaterialTheme.colorScheme.surfaceVariant),
                contentAlignment = Alignment.Center,
            ) {
                CatalogImage(
                    url = channel.logoUrl,
                    contentDescription = null, // the card sentence says the name
                    fallbackLabel = channel.name,
                    // Phase 7 (M4): channel logos come from the operator-curated
                    // channel registry, not the catalog — their hosts are the
                    // registry's own, and the art policy does not vet them.
                    allowAnyHost = true,
                    contentScale = ContentScale.Fit,
                    modifier = Modifier
                        .fillMaxWidth()
                        .aspectRatio(CardGeometry.WIDE_ART_ASPECT)
                        .padding(8.dp),
                )
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(4.dp),
                    modifier = Modifier
                        .align(Alignment.TopStart)
                        .padding(6.dp)
                        .background(
                            MaterialTheme.colorScheme.surface.copy(alpha = 0.85f),
                            RoundedCornerShape(4.dp),
                        )
                        .padding(horizontal = 6.dp, vertical = 2.dp)
                        .clearAndSetSemantics { },
                ) {
                    Box(
                        modifier = Modifier
                            .size(8.dp)
                            .background(
                                MaterialTheme.colorScheme.error,
                                CircleShape,
                            ),
                    )
                    Text(
                        text = "LIVE",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                }
            }
            Text(
                text = channel.name,
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.onSurface,
                // F11 (Batch B): one line, not two — a wrapping name was half
                // the uneven card heights, and a channel name that needs two
                // lines in a 120dp column is a truncated name anyway.
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp).clearAndSetSemantics { },
            )
            Text(
                text = listOfNotNull(
                    categoryLabel(channel.category),
                    countryLabel(channel.country),
                ).joinToString(" · "),
                // P2-6: no trailing separator when the country is blank.
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.padding(horizontal = 10.dp).padding(bottom = 10.dp).clearAndSetSemantics { },
            )
        }
    }
}
