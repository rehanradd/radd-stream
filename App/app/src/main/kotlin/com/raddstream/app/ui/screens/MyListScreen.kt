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
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.raddstream.app.ui.components.CatalogGridColumns
import com.raddstream.app.ui.components.EmptyState
import com.raddstream.app.ui.components.PosterCard
import com.raddstream.app.ui.components.PosterGridSkeleton
import com.raddstream.app.viewmodel.ListSort
import com.raddstream.app.viewmodel.MyListViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MyListScreen(
    onPostClick: (Int) -> Unit,
    viewModel: MyListViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
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
            state.favorites.isEmpty() -> EmptyState(
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
                modifier = Modifier.padding(contentPadding),
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
                            onClick = { onPostClick(post.id) },
                            onLongClick = { viewModel.requestRemoval(post.id) },
                        )
                    }
                }
            }
        }

        // A held tile is a wish, not a deletion: the row stays until this answer comes back.
        state.armedRemovalId?.let { armedId ->
            val armed = state.favorites.firstOrNull { it.id == armedId }
            AlertDialog(
                onDismissRequest = viewModel::cancelRemoval,
                title = { Text("Remove from My List?") },
                text = {
                    Text(
                        if (armed == null) {
                            "This title will be removed from this device and from your synced " +
                                "list. You can save it again any time."
                        } else {
                            "${armed.displayTitle} will be removed from this device and from " +
                                "your synced list. You can save it again any time."
                        },
                    )
                },
                confirmButton = {
                    TextButton(onClick = viewModel::confirmRemoval) { Text("Remove") }
                },
                dismissButton = {
                    TextButton(onClick = viewModel::cancelRemoval) { Text("Keep") }
                },
            )
        }
    }
}
