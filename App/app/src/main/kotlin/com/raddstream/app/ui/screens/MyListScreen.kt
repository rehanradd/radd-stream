package com.raddstream.app.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.raddstream.app.network.models.Post
import com.raddstream.app.ui.components.CatalogGridColumns
import com.raddstream.app.ui.components.EmptyState
import com.raddstream.app.ui.components.PosterCard
import com.raddstream.app.ui.components.PosterGridSkeleton
import com.raddstream.app.ui.components.raddFilterChipColors
import com.raddstream.app.viewmodel.ListSort
import com.raddstream.app.viewmodel.MyListViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MyListScreen(
    onPostClick: (Post) -> Unit,
    viewModel: MyListViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }

    // One tap removes the row; the way back is the snackbar, not a dialog
    // the viewer had to answer first. Dismissing the snackbar without
    // tapping Undo lets the removal stand.
    LaunchedEffect(state.removedTitle) {
        val title = state.removedTitle ?: return@LaunchedEffect
        val result = snackbarHostState.showSnackbar(
            message = "Removed $title from My List",
            actionLabel = "Undo",
            duration = SnackbarDuration.Long,
        )
        if (result == SnackbarResult.ActionPerformed) {
            viewModel.undoRemoval()
        } else {
            viewModel.clearRemovedNotice()
        }
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = {
            TopAppBar(
                title = { Text("My List") },
            )
        },
    ) { contentPadding ->
        when {
            state.isLoading -> PosterGridSkeleton(modifier = Modifier.fillMaxSize().padding(contentPadding))
            state.favorites.isEmpty() && state.hiddenCount > 0 -> EmptyState(
                // Nothing here is "empty" — the rows exist and this build may not show them.
                // Saying "your list is empty" would be a second loss on top of the first one.
                title = "Nothing to show from your list",
                message = state.hiddenNotice
                    ?: "Tap the heart on any movie or series to save it here for quick access.",
                icon = {
                    Icon(
                        Icons.Default.FavoriteBorder,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.secondary,
                        modifier = Modifier.size(40.dp),
                    )
                },
                modifier = Modifier.padding(contentPadding),
            )
            state.favorites.isEmpty() -> Column(
                modifier = Modifier.fillMaxSize().padding(contentPadding),
            ) {
                EmptyState(
                    title = "Your list is empty",
                    message = "Tap the heart on any movie or series to save it here for quick access.",
                    icon = {
                        Icon(
                            Icons.Default.FavoriteBorder,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.secondary,
                            modifier = Modifier.size(40.dp),
                        )
                    },
                    modifier = Modifier.fillMaxWidth(),
                )
                if (state.popular.isNotEmpty()) {
                    PopularRow(popular = state.popular, onPostClick = onPostClick)
                }
            }
            else -> Column(Modifier.fillMaxSize().padding(contentPadding)) {
                state.hiddenNotice?.let { notice ->
                    Text(
                        text = notice,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp),
                    )
                }
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(min = 48.dp)
                        .padding(horizontal = 16.dp, vertical = 4.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    ListSort.entries.forEach { sort ->
                        FilterChip(
                            colors = raddFilterChipColors(),
                            selected = state.sort == sort,
                            onClick = { viewModel.setSort(sort) },
                            label = { Text(sort.label) },
                        )
                    }
                }
                LazyVerticalGrid(
                    columns = CatalogGridColumns,
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(top = 8.dp, bottom = 24.dp, start = 16.dp, end = 16.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                    verticalArrangement = Arrangement.spacedBy(14.dp),
                ) {
                    items(state.favorites, key = { it.id }) { post ->
                        PosterCard(
                            post = post,
                            onClick = { onPostClick(post) },
                            onRemove = { viewModel.remove(post.id) },
                        )
                    }
                }
            }
        }
    }
}

/**
 * Three titles for an empty list — the server's own trending order (most
 * prints and mirrors first), not this viewer's history. A tap opens the
 * title; saving it from there is what fills the list.
 */
@Composable
private fun PopularRow(popular: List<Post>, onPostClick: (Post) -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text(
            "Popular right now",
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onBackground,
        )
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            popular.take(3).forEach { post ->
                PosterCard(
                    post = post,
                    onClick = { onPostClick(post) },
                    modifier = Modifier.weight(1f),
                )
            }
        }
    }
}
