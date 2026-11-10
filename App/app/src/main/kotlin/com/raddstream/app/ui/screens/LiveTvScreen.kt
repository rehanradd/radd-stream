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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.clearAndSetSemantics
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
            state.isLoading -> PosterGridSkeleton(
                modifier = Modifier.fillMaxSize().padding(contentPadding),
            )
            state.error != null -> ErrorState(
                message = state.error ?: "Could not load live channels.",
                onRetry = { viewModel.refresh() },
                modifier = Modifier.fillMaxSize().padding(contentPadding),
            )
            state.channels.isEmpty() -> EmptyState(
                title = "No live channels right now",
                message = "Live channels will appear here once the operator enables them.",
                modifier = Modifier.fillMaxSize().padding(contentPadding),
            )
            else -> Column(Modifier.fillMaxSize().padding(contentPadding)) {
                OutlinedTextField(
                    value = state.query,
                    onValueChange = viewModel::onQueryChanged,
                    // E-L2: the label is the field's accessible name — a placeholder
                    // alone does not label it.
                    label = { Text("Search channels") },
                    placeholder = { Text("Search channels") },
                    leadingIcon = {
                        Icon(
                            Icons.Default.Search,
                            contentDescription = null,
                        )
                    },
                    singleLine = true,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 4.dp),
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
                            selected = state.selectedCategory == null,
                            onClick = { viewModel.onCategorySelected(null) },
                            label = { Text("All") },
                        )
                    }
                    items(state.categories) { category ->
                        FilterChip(
                            selected = state.selectedCategory == category,
                            onClick = { viewModel.onCategorySelected(category) },
                            label = { Text(categoryLabel(category)) },
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

@Composable
private fun LiveTvChannelCard(
    channel: LiveTvChannel,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    // Robo run 2: every card announced its name three times (logo description,
    // name text, and the "LIVE" badge on every card) — the same words on all
    // ~18 channels. One sentence per card; the logo, badge and texts are paint.
    val a11y = "${channel.name}, live, ${categoryLabel(channel.category)} · ${channel.country}"
    Card(
        onClick = onClick,
        modifier = modifier.semantics { contentDescription = a11y },
    ) {
        Column {
            Box {
                CatalogImage(
                    url = channel.logoUrl,
                    contentDescription = null, // the card sentence says the name
                    fallbackLabel = channel.name,
                    // Phase 7 (M4): channel logos come from the operator-curated
                    // channel registry, not the catalog — their hosts are the
                    // registry's own, and the art policy does not vet them.
                    allowAnyHost = true,
                    modifier = Modifier
                        .fillMaxWidth()
                        .aspectRatio(16f / 9f),
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
                maxLines = 2,
                modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp).clearAndSetSemantics { },
            )
            Text(
                text = "${categoryLabel(channel.category)} · ${channel.country}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 10.dp).padding(bottom = 10.dp).clearAndSetSemantics { },
            )
        }
    }
}
