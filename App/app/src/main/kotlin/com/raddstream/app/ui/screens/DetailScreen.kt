package com.raddstream.app.ui.screens

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.OpenInNew
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
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
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import coil.compose.AsyncImage
import com.raddstream.app.network.models.PostDetail
import com.raddstream.app.network.models.ReleaseDetail
import com.raddstream.app.network.models.SourceDetail
import com.raddstream.app.ui.theme.AccentGold
import com.raddstream.app.ui.theme.AccentPrimary
import com.raddstream.app.ui.theme.AccentSecondary
import com.raddstream.app.ui.theme.BackgroundDark
import com.raddstream.app.ui.theme.OnBackground
import com.raddstream.app.ui.theme.OnSurface
import com.raddstream.app.ui.theme.OnSurfaceMuted
import com.raddstream.app.ui.theme.SurfaceDark
import com.raddstream.app.ui.theme.SurfaceVariantDark
import com.raddstream.app.viewmodel.DetailNavigationEvent
import com.raddstream.app.viewmodel.DetailViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DetailScreen(
    onBackClick: () -> Unit,
    onPlayStream: (streamUrl: String, title: String) -> Unit,
    viewModel: DetailViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }
    val context = LocalContext.current

    LaunchedEffect(viewModel.navEvents) {
        viewModel.navEvents.collect { event ->
            when (event) {
                is DetailNavigationEvent.PlayStream -> {
                    onPlayStream(event.streamUrl, event.title)
                }
                is DetailNavigationEvent.OpenExternal -> {
                    openInExternalPlayer(context, event.streamUrl)
                }
            }
        }
    }

    LaunchedEffect(state.actionMessage) {
        state.actionMessage?.let { msg ->
            snackbarHostState.showSnackbar(msg)
            viewModel.clearActionMessage()
        }
    }

    Scaffold(
        containerColor = BackgroundDark,
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        state.post?.cleanTitle ?: state.post?.title ?: "Details",
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onBackClick) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                },
                actions = {
                    IconButton(onClick = viewModel::toggleFavorite) {
                        Icon(
                            imageVector = if (state.isFavorite) Icons.Default.Favorite else Icons.Default.FavoriteBorder,
                            contentDescription = if (state.isFavorite) "Remove from My List" else "Add to My List",
                            tint = if (state.isFavorite) AccentSecondary else OnSurface,
                        )
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Color.Transparent,
                    titleContentColor = OnBackground,
                ),
            )
        },
    ) { paddingValues ->
        when {
            state.isLoading -> {
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(paddingValues),
                    contentAlignment = Alignment.Center,
                ) {
                    CircularProgressIndicator(color = AccentPrimary)
                }
            }
            state.error != null && state.post == null -> {
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(paddingValues),
                    contentAlignment = Alignment.Center,
                ) {
                    Column(
                        horizontalAlignment = Alignment.CenterHorizontally,
                        modifier = Modifier.padding(24.dp),
                    ) {
                        Text(
                            text = state.error ?: "Unable to load title.",
                            color = OnSurfaceMuted,
                            textAlign = TextAlign.Center,
                            style = MaterialTheme.typography.bodyMedium,
                        )
                        Spacer(Modifier.height(16.dp))
                        OutlinedButton(onClick = viewModel::loadDetail) {
                            Icon(Icons.Default.Refresh, contentDescription = null)
                            Spacer(Modifier.width(8.dp))
                            Text("Retry")
                        }
                    }
                }
            }
            state.post != null -> {
                val post = state.post!!
                PostDetailContent(
                    post = post,
                    resolvingSourceId = state.resolvingSourceId,
                    onPlaySource = { source, external -> viewModel.playSource(source, external) },
                    contentPadding = paddingValues,
                )
            }
        }
    }
}

@Composable
private fun PostDetailContent(
    post: PostDetail,
    resolvingSourceId: Int?,
    onPlaySource: (SourceDetail, Boolean) -> Unit,
    contentPadding: PaddingValues,
) {
    // If series, handle season filtering
    val isSeries = post.contentType?.contains("series", ignoreCase = true) == true ||
            post.contentType?.contains("season", ignoreCase = true) == true ||
            post.releases.any { it.seasonNumber != null }

    val seasons = remember(post.releases) {
        post.releases.mapNotNull { it.seasonNumber }.distinct().sorted()
    }
    var selectedSeason by remember(seasons) {
        mutableStateOf(seasons.firstOrNull())
    }

    val displayedReleases = remember(post.releases, selectedSeason, isSeries) {
        if (isSeries && selectedSeason != null) {
            post.releases.filter { it.seasonNumber == selectedSeason }
        } else {
            post.releases
        }
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(
            top = contentPadding.calculateTopPadding(),
            bottom = 32.dp,
            start = 16.dp,
            end = 16.dp,
        ),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        // ── Poster & Header Info ──────────────────────────────────────
        item {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                // Poster
                Box(
                    modifier = Modifier
                        .width(120.dp)
                        .aspectRatio(0.68f)
                        .clip(RoundedCornerShape(12.dp))
                        .background(SurfaceVariantDark),
                    contentAlignment = Alignment.Center,
                ) {
                    if (!post.posterUrl.isNullOrBlank()) {
                        AsyncImage(
                            model = post.posterUrl,
                            contentDescription = "${post.title} poster",
                            modifier = Modifier.fillMaxSize(),
                            contentScale = ContentScale.Crop,
                        )
                    } else {
                        Text("No Poster", color = OnSurfaceMuted, style = MaterialTheme.typography.labelSmall)
                    }
                }

                // Metadata Column
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text(
                        text = post.cleanTitle?.takeIf(String::isNotBlank) ?: post.title,
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold,
                        color = OnBackground,
                        maxLines = 3,
                        overflow = TextOverflow.Ellipsis,
                    )

                    val metaList = listOfNotNull(
                        post.year?.takeIf(String::isNotBlank),
                        post.contentType?.replaceFirstChar { it.uppercase() }?.takeIf(String::isNotBlank),
                        post.language?.takeIf(String::isNotBlank),
                    )
                    if (metaList.isNotEmpty()) {
                        Text(
                            text = metaList.joinToString(" • "),
                            style = MaterialTheme.typography.bodySmall,
                            color = OnSurfaceMuted,
                        )
                    }

                    post.imdbRating?.takeIf(String::isNotBlank)?.let { rating ->
                        Surface(
                            color = SurfaceDark,
                            shape = RoundedCornerShape(6.dp),
                        ) {
                            Text(
                                text = "★ $rating IMDb",
                                color = AccentGold,
                                style = MaterialTheme.typography.labelMedium,
                                fontWeight = FontWeight.Bold,
                                modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                            )
                        }
                    }

                    post.sourceSite?.takeIf(String::isNotBlank)?.let { site ->
                        Text(
                            text = "Catalog: $site",
                            style = MaterialTheme.typography.labelSmall,
                            color = OnSurfaceMuted,
                        )
                    }
                }
            }
        }

        // ── Synopsis / Description ────────────────────────────────────
        if (!post.synopsis.isNullOrBlank()) {
            item {
                Text(
                    text = post.synopsis,
                    style = MaterialTheme.typography.bodyMedium,
                    color = OnSurface,
                )
            }
        }

        // ── Season selector for Series ────────────────────────────────
        if (isSeries && seasons.size > 1) {
            item {
                Text(
                    text = "Seasons",
                    style = MaterialTheme.typography.titleMedium,
                    color = OnBackground,
                    fontWeight = FontWeight.SemiBold,
                )
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    seasons.forEach { seasonNum ->
                        FilterChip(
                            selected = selectedSeason == seasonNum,
                            onClick = { selectedSeason = seasonNum },
                            label = { Text("Season $seasonNum") },
                        )
                    }
                }
            }
        }

        // ── Available Streams & Releases Header ───────────────────────
        item {
            Text(
                text = "Available Releases & Sources",
                style = MaterialTheme.typography.titleMedium,
                color = OnBackground,
                fontWeight = FontWeight.SemiBold,
            )
        }

        if (displayedReleases.isEmpty()) {
            item {
                Text(
                    text = "No direct stream releases parsed for this title.",
                    style = MaterialTheme.typography.bodySmall,
                    color = OnSurfaceMuted,
                )
            }
        } else {
            items(displayedReleases, key = { it.id }) { release ->
                ReleaseCard(
                    release = release,
                    resolvingSourceId = resolvingSourceId,
                    onPlaySource = onPlaySource,
                )
            }
        }
    }
}

@Composable
private fun ReleaseCard(
    release: ReleaseDetail,
    resolvingSourceId: Int?,
    onPlaySource: (SourceDetail, Boolean) -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceDark),
    ) {
        Column(
            modifier = Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            // Quality & specs row
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                val qualityTag = listOfNotNull(
                    release.resolution?.takeIf(String::isNotBlank),
                    release.quality?.takeIf(String::isNotBlank),
                ).joinToString(" ").ifBlank { "Direct Stream" }

                Text(
                    text = qualityTag,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    color = AccentPrimary,
                )

                val extraInfo = listOfNotNull(
                    release.size?.takeIf(String::isNotBlank),
                    release.codec?.takeIf(String::isNotBlank),
                ).joinToString(" • ")

                if (extraInfo.isNotBlank()) {
                    Text(
                        text = extraInfo,
                        style = MaterialTheme.typography.labelSmall,
                        color = OnSurfaceMuted,
                    )
                }
            }

            if (release.episodeNumber != null) {
                Text(
                    text = "Episode ${release.episodeNumber}: ${release.episodeTitle ?: ""}".trimEnd(':', ' '),
                    style = MaterialTheme.typography.bodySmall,
                    color = OnSurface,
                )
            }

            // Sources list
            if (release.sources.isNotEmpty()) {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    release.sources.forEach { source ->
                        SourceRow(
                            source = source,
                            isResolving = resolvingSourceId == source.id,
                            onPlay = { external -> onPlaySource(source, external) },
                        )
                    }
                }
            } else {
                Text(
                    text = "No direct download mirrors currently attached.",
                    style = MaterialTheme.typography.labelSmall,
                    color = OnSurfaceMuted,
                )
            }
        }
    }
}

@Composable
private fun SourceRow(
    source: SourceDetail,
    isResolving: Boolean,
    onPlay: (isExternal: Boolean) -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = SurfaceVariantDark,
        shape = RoundedCornerShape(8.dp),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 10.dp, vertical = 6.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = source.sourceName?.takeIf(String::isNotBlank) ?: (source.service ?: "Stream Source"),
                    style = MaterialTheme.typography.labelLarge,
                    color = OnSurface,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                val statusText = if (source.status == "active") "⚡ Fast Direct" else "Available"
                Text(
                    text = statusText,
                    style = MaterialTheme.typography.labelSmall,
                    color = OnSurfaceMuted,
                )
            }

            if (isResolving) {
                CircularProgressIndicator(
                    modifier = Modifier.size(24.dp),
                    strokeWidth = 2.dp,
                    color = AccentPrimary,
                )
            } else {
                Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    // Play in built-in player
                    IconButton(
                        onClick = { onPlay(false) },
                        modifier = Modifier.size(36.dp),
                    ) {
                        Icon(
                            Icons.Default.PlayArrow,
                            contentDescription = "Play in app",
                            tint = AccentPrimary,
                        )
                    }

                    // Open in external player (VLC / MX Player)
                    IconButton(
                        onClick = { onPlay(true) },
                        modifier = Modifier.size(36.dp),
                    ) {
                        Icon(
                            Icons.Default.OpenInNew,
                            contentDescription = "Open in external player",
                            tint = OnSurfaceMuted,
                        )
                    }
                }
            }
        }
    }
}

private fun openInExternalPlayer(context: Context, url: String) {
    try {
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(Uri.parse(url), "video/*")
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(Intent.createChooser(intent, "Play stream with..."))
    } catch (_: Exception) {
        try {
            val webIntent = Intent(Intent.ACTION_VIEW, Uri.parse(url)).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(webIntent)
        } catch (_: Exception) {
            Toast.makeText(context, "No video player or browser installed", Toast.LENGTH_SHORT).show()
        }
    }
}
