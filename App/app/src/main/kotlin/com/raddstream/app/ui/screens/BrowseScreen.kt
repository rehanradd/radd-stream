package com.raddstream.app.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.grid.rememberLazyGridState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.raddstream.app.ui.components.CatalogGridColumns
import com.raddstream.app.ui.components.EmptyState
import com.raddstream.app.ui.components.ErrorState
import com.raddstream.app.ui.components.InlineLoadFailure
import com.raddstream.app.ui.components.PosterCard
import com.raddstream.app.ui.components.PosterGridSkeleton
import com.raddstream.app.ui.components.rememberGridEndlessPaging
import com.raddstream.app.viewmodel.BrowseViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BrowseScreen(
    onBackClick: () -> Unit,
    onPostClick: (Int) -> Unit,
    viewModel: BrowseViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()
    val gridState = rememberLazyGridState()
    rememberGridEndlessPaging(gridState = gridState) { viewModel.loadMore() }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = { Text(state.title) },
                navigationIcon = {
                    IconButton(onClick = onBackClick) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        },
    ) { contentPadding ->
        when {
            state.loading && state.items.isEmpty() -> PosterGridSkeleton(
                modifier = Modifier.fillMaxSize().padding(contentPadding),
            )
            state.error != null && state.items.isEmpty() ->
                ErrorState(message = state.error ?: "Could not load.", onRetry = viewModel::load,
                    modifier = Modifier.padding(contentPadding))
            state.items.isEmpty() -> EmptyState(
                title = "Nothing here yet",
                message = "This category has no titles on the connected server.",
                modifier = Modifier.padding(contentPadding),
            )
            else -> LazyVerticalGrid(
                state = gridState,
                columns = CatalogGridColumns,
                modifier = Modifier.fillMaxSize().padding(contentPadding),
                contentPadding = PaddingValues(top = 8.dp, bottom = 32.dp, start = 16.dp, end = 16.dp),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                items(state.items, key = { it.id }) { post ->
                    PosterCard(post = post, onClick = { onPostClick(post.id) })
                }
                if (state.loadingMore) {
                    item {
                        Box(Modifier.fillMaxWidth().height(60.dp), contentAlignment = Alignment.Center) {
                            CircularProgressIndicator(Modifier.height(28.dp), strokeWidth = 2.dp)
                        }
                    }
                }
                // The grid is what the viewer can see; a page that failed to arrive is not.
                // Without this a dead next page just looks like a shorter category.
                state.error?.let { failure ->
                    item(contentType = "failure") {
                        InlineLoadFailure(message = failure, onRetry = viewModel::loadMore)
                    }
                }
            }
        }
    }
}
