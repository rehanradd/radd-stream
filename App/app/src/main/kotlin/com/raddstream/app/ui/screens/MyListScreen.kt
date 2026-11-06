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
import androidx.compose.material.icons.filled.History
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import androidx.compose.ui.semantics.clearAndSetSemantics
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
    onOpenWatchHistory: () -> Unit = {},
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
                // CL-7, same as Settings: the title says "My List" and so does
                // its nav tab — the title is paint, not a second announcement.
                title = { Text("My List", modifier = Modifier.clearAndSetSemantics { }) },
                actions = {
                    // The history lives next to the list it belongs to: the same
                    // device, the same titles, one tap away in every list state.
                    IconButton(onClick = onOpenWatchHistory) {
                        Icon(Icons.Default.History, contentDescription = "Watch history")
                    }
                },
                },
>>>>>>> 40370e2 (Session 81 (D1.3): Watch History screen)
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
            state.favorites.isEmpty() -> MyListEmptyContent(
                popular = state.popular,
                onPostClick = onPostClick,
                modifier = Modifier.fillMaxSize().padding(contentPadding),
            )
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
                            // Robo run 2: the three sort chips are 32dp tall
                            // (FilterChip's visual height) — the touch-target
                            // floor is 48dp, so the chip itself carries it.
                            modifier = Modifier.heightIn(min = 48.dp),
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
 * Robo run 8: the My List empty state never showed its "Popular right now"
 * row — and Robo measured three 32dp clickables just above the nav bar.
 * Both are the same layout bug: [EmptyState] is a fillMaxSize Box, so inside
 * the Column it took the whole height and the [PopularRow] below it was laid
 * out with no height left — off-screen, its three poster cards collapsed to
 * a strip at the content's bottom edge, one per column. The message now takes
 * the remaining space (weight 1f) and the row takes its natural height, so
 * the suggestions are visible and every card is a full-height tile.
 * Internal so MyListEmptyContentTest can pin it without the Hilt ViewModel.
 */
@Composable
internal fun MyListEmptyContent(
    popular: List<Post>,
    onPostClick: (Post) -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier) {
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
            modifier = Modifier.weight(1f).fillMaxWidth(),
        )
        if (popular.isNotEmpty()) {
            PopularRow(popular = popular, onPostClick = onPostClick)
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
