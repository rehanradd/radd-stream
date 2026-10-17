package com.raddstream.app.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.raddstream.app.ui.components.PosterCard
import com.raddstream.app.ui.theme.AccentPrimary
import com.raddstream.app.ui.theme.AccentSecondary
import com.raddstream.app.ui.theme.BackgroundDark
import com.raddstream.app.ui.theme.OnBackground
import com.raddstream.app.ui.theme.OnSurfaceMuted
import com.raddstream.app.viewmodel.MyListViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MyListScreen(
    onPostClick: (Int) -> Unit,
    viewModel: MyListViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()

    Scaffold(
        containerColor = BackgroundDark,
        topBar = {
            TopAppBar(
                title = { Text("My List", color = OnBackground) },
            )
        },
    ) { contentPadding ->
        when {
            state.isLoading -> {
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(contentPadding),
                    contentAlignment = Alignment.Center,
                ) {
                    CircularProgressIndicator(color = AccentPrimary)
                }
            }
            state.favorites.isEmpty() -> {
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(contentPadding)
                        .padding(32.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Icon(
                            imageVector = Icons.Default.FavoriteBorder,
                            contentDescription = null,
                            tint = AccentSecondary.copy(alpha = 0.6f),
                            modifier = Modifier.padding(bottom = 12.dp),
                        )
                        Text(
                            text = "Your list is empty",
                            style = MaterialTheme.typography.titleMedium,
                            color = OnBackground,
                        )
                        Spacer(Modifier.height(6.dp))
                        Text(
                            text = "Tap the heart icon on any movie or series to save it here for quick access.",
                            style = MaterialTheme.typography.bodyMedium,
                            color = OnSurfaceMuted,
                            textAlign = TextAlign.Center,
                        )
                    }
                }
            }
            else -> {
                LazyVerticalGrid(
                    columns = GridCells.Fixed(2),
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(contentPadding)
                        .padding(horizontal = 16.dp),
                    contentPadding = PaddingValues(top = 8.dp, bottom = 24.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                    verticalArrangement = Arrangement.spacedBy(14.dp),
                ) {
                    items(state.favorites, key = { it.id }) { post ->
                        PosterCard(
                            post = post,
                            onClick = { onPostClick(post.id) },
                        )
                    }
                }
            }
        }
    }
}
