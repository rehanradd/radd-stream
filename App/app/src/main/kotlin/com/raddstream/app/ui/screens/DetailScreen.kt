package com.raddstream.app.ui.screens

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.horizontalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.OpenInNew
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.hilt.navigation.compose.hiltViewModel
import kotlinx.coroutines.launch
import com.raddstream.app.brand.Brand
import com.raddstream.app.network.models.PostDetail
import com.raddstream.app.ui.components.AudioBadge
import com.raddstream.app.ui.components.CapabilityChip
import com.raddstream.app.ui.components.CamBadge
import com.raddstream.app.ui.components.CatalogImage
import com.raddstream.app.ui.components.ErrorState
import com.raddstream.app.ui.components.HdrBadge
import com.raddstream.app.ui.components.ImageFallbackCard
import com.raddstream.app.ui.components.InlineLoadFailure
import com.raddstream.app.ui.components.LoadingState
import com.raddstream.app.ui.components.Pill
import com.raddstream.app.ui.components.PrintQualityBadge
import com.raddstream.app.ui.components.PrintSourceBadge
import com.raddstream.app.ui.components.QualityRungCard
import com.raddstream.app.ui.components.SectionHeader
import com.raddstream.app.ui.components.SubtitleBadge
import com.raddstream.app.player.LadderForScope
import com.raddstream.app.player.QualityOption
import com.raddstream.app.ui.navigation.DeepLinks
import com.raddstream.app.ui.theme.rememberArtworkAccent
import com.raddstream.app.viewmodel.DetailNavigationEvent
import com.raddstream.app.viewmodel.DetailViewModel
import com.raddstream.app.viewmodel.EpisodeGroup
import com.raddstream.app.viewmodel.EpisodeProgress
import com.raddstream.app.viewmodel.PendingKeep
import com.raddstream.app.viewmodel.RankedPrint
import com.raddstream.app.viewmodel.ResumePoint
import com.raddstream.app.viewmodel.SeasonGroup
import com.raddstream.app.viewmodel.formatRuntimeMinutes
import com.raddstream.app.viewmodel.keepSizeLabel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DetailScreen(
    onBackClick: () -> Unit,
    onPlayStream: (streamId: String, title: String) -> Unit,
    /** A link the server calls a page: show the provider's own page rather than fail quietly. */
    onOpenProviderPage: (streamId: String, title: String) -> Unit = { _, _ -> },
    onOpenDownloads: () -> Unit = {},
    onOpenVipUpgrade: () -> Unit = {},
    viewModel: DetailViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var pendingDownload by remember { mutableStateOf<(() -> Unit)?>(null) }
    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        val action = pendingDownload
        pendingDownload = null
        if (granted) action?.invoke()
        else Toast.makeText(
            context,
            "Storage access is needed to save videos in Movies/RaddStream.",
            Toast.LENGTH_LONG,
        ).show()
    }
    val notificationLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) {
        val action = pendingDownload
        pendingDownload = null
        // A denied notification still lets the download run; only the progress card is silent.
        action?.invoke()
    }

    fun requestNotificationsThen(action: () -> Unit) {
        val needsGrant = Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.POST_NOTIFICATIONS,
            ) != PackageManager.PERMISSION_GRANTED
        if (needsGrant) {
            pendingDownload = action
            notificationLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        } else {
            action()
        }
    }

    fun downloadWithStoragePermission(action: () -> Unit) {
        val needsLegacyGrant = Build.VERSION.SDK_INT < Build.VERSION_CODES.Q &&
            ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.WRITE_EXTERNAL_STORAGE,
            ) != PackageManager.PERMISSION_GRANTED
        if (needsLegacyGrant) {
            pendingDownload = { requestNotificationsThen(action) }
            permissionLauncher.launch(Manifest.permission.WRITE_EXTERNAL_STORAGE)
        } else {
            requestNotificationsThen(action)
        }
    }

    LaunchedEffect(viewModel.navEvents) {
        viewModel.navEvents.collect { event ->
            when (event) {
                is DetailNavigationEvent.PlayStream -> onPlayStream(event.streamId, event.title)
                is DetailNavigationEvent.OpenProviderPage ->
                    onOpenProviderPage(event.streamId, event.title)
                is DetailNavigationEvent.OpenExternal -> openInExternalPlayer(context, event.playUrl)
                is DetailNavigationEvent.DownloadStarted -> onOpenDownloads()
                is DetailNavigationEvent.DownloadNeedsPermission ->
                    downloadWithStoragePermission { viewModel.retryLastDownload() }
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
        containerColor = MaterialTheme.colorScheme.background,
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
                actions = {},
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
            )
        },
    ) { paddingValues ->
        val post = state.post
        when {
            state.isLoading -> LoadingState(Modifier.padding(paddingValues))
            state.error != null && post == null -> ErrorState(
                message = state.error ?: "Unable to load title.",
                onRetry = viewModel::loadDetail,
                modifier = Modifier.padding(paddingValues),
            )
            post != null -> DetailContent(
                post = post,
                seasons = state.layout?.seasons ?: emptyList(),
                workPrints = state.layout?.workPrints ?: emptyList(),
                capabilities = state.layout?.capabilities ?: emptyList(),
                officialPrintCount = state.layout?.officialPrintCount ?: 0,
                camPrintCount = state.layout?.camPrintCount ?: 0,
                isSeries = state.layout?.isSeriesLike ?: false,
                resume = state.resume.takeIf { state.resumePlayable },
                onPlayResume = viewModel::playResume,
                episodeProgress = state.episodeProgress,
                includedLine = state.includedLine,
                selectedSeason = state.selectedSeason,
                onSelectSeason = viewModel::selectSeason,
                onPlayPrint = { print -> viewModel.playPrint(print, external = false) },
                onOpenExternal = { print -> viewModel.playPrint(print, external = true) },
                onKeep = { print -> downloadWithStoragePermission { viewModel.keepPrint(print) } },
                rungs = RungActions(
                    ladder = state.ladder,
                    selectedBand = state.selectedBand,
                    onPlay = viewModel::playLadder,
                    onKeep = { option -> downloadWithStoragePermission { viewModel.keepRung(option) } },
                    tierLabel = viewModel::tierLabelFor,
                ),
                ladderScope = rungScopeLabel(state.ladderSeason, state.ladderEpisode),
                adFree = state.adFree,
                premiumSourcesLocked = state.premiumSourcesLocked,
                onAskRungs = viewModel::showRungsFor,
                hasRungs = { season, episode -> !viewModel.ladderFor(season, episode).isEmpty },
                onOpenVipUpgrade = onOpenVipUpgrade,
                reloadError = state.error,
                onRetryReload = viewModel::loadDetail,
                isFavorite = state.isFavorite,
                onToggleFavorite = viewModel::toggleFavorite,
                onShare = {
                    shareTitle(context, post) { viewModel.reportShare(post.workRef) }
                },
                contentPadding = paddingValues,
            )
        }
    }

    state.pendingKeep?.let { pending ->
        KeepConfirmDialog(
            pending = pending,
            onConfirm = viewModel::confirmKeep,
            onDismiss = viewModel::dismissKeep,
            // Session 73 (Phase 5): a free viewer asking for a file gets the
            // external-browser route as well — the browser follows the server's
            // redirect to ShrinkMe (when enabled) or the file. VIP viewers never
            // see it; their downloads are already direct.
            showWebLink = !state.vip,
            onWebLink = { openWebPage(context, viewModel.webDownloadUrlFor(pending.handle)) },
            // Session 76 (Build 4): the same free viewer can spend coins on a
            // direct link instead — the button is there only when the server
            // published a price, and only enabled when the wallet covers it.
            showDirectLink = !state.vip && state.downloadCreditPrice > 0,
            directLinkPrice = state.downloadCreditPrice,
            directLinkEnabled = state.coinBalance >= state.downloadCreditPrice,
            directLinkMessage = state.directLinkMessage,
            onDirectLink = {
                scope.launch {
                    val url = viewModel.directDownloadUrlFor(pending.handle)
                    if (url != null) openWebPage(context, url)
                }
            },
        )
    }
}

/**
 * The size and the quality before the download starts. The size is the one
 * the metadata ask measured — never a guess — and when the server named no
 * size the dialog says so instead of inventing one. Nothing downloads until
 * Confirm; Cancel leaves nothing behind.
 */
@Composable
private fun KeepConfirmDialog(
    pending: PendingKeep,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
    showWebLink: Boolean = false,
    onWebLink: () -> Unit = {},
    showDirectLink: Boolean = false,
    directLinkPrice: Int = 0,
    directLinkEnabled: Boolean = false,
    directLinkMessage: String? = null,
    onDirectLink: () -> Unit = {},
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Download this title?") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(pending.title, style = MaterialTheme.typography.titleSmall)
                Text(
                    pending.printLabel,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    keepSizeLabel(pending.sizeBytes),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (showWebLink) {
                    TextButton(onClick = onWebLink) { Text("Get Free Web Link") }
                }
                if (showDirectLink) {
                    // Session 76 (Build 4): a direct link for one movie, bought
                    // with coins — the button is disabled while the wallet is
                    // short, so a tap can never spend what is not there.
                    TextButton(onClick = onDirectLink, enabled = directLinkEnabled) {
                        Text("Direct Link — $directLinkPrice coins")
                    }
                    if (directLinkMessage != null) {
                        Text(
                            directLinkMessage,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        },
        confirmButton = {
            Button(onClick = onConfirm) { Text("Download") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel") }
        },
    )
}

/**
 * The quality switch and the download card as one bundle: the same rows render under the work
 * and under an episode, so a series never inherits another episode's links by accident.
 */
private data class RungActions(
    val ladder: LadderForScope,
    val selectedBand: String?,
    val onPlay: (QualityOption) -> Unit,
    val onKeep: (QualityOption) -> Unit,
    /** The tier each rung requires ("VIP" / "Standard"), from the ViewModel. */
    val tierLabel: (QualityOption) -> String,
)

/** Which scope a ladder belongs to, in the viewer's words. Null means the whole work. */
private fun rungScopeLabel(season: Int?, episode: Int?): String? = when {
    season != null && episode != null -> "Season $season · Episode $episode"
    episode != null -> "Episode $episode"
    season != null -> "Season $season"
    else -> null
}

@Composable
private fun DetailContent(
    post: PostDetail,
    seasons: List<SeasonGroup>,
    workPrints: List<RankedPrint>,
    capabilities: List<String>,
    officialPrintCount: Int,
    camPrintCount: Int,
    isSeries: Boolean,
    /** The latest scope this device stopped in, if it has a print to play — else null. */
    resume: ResumePoint?,
    onPlayResume: () -> Unit,
    /** Per-episode progress, keyed by (season, episode). */
    episodeProgress: Map<Pair<Int, Int>, EpisodeProgress>,
    /** What this viewer can watch of this title, in one line — null when it has no prints. */
    includedLine: String?,
    selectedSeason: Int?,
    onSelectSeason: (Int) -> Unit,
    onPlayPrint: (RankedPrint) -> Unit,
    onOpenExternal: (RankedPrint) -> Unit,
    onKeep: (RankedPrint) -> Unit,
    /** The quality switch and the download card, as one bundle the rows can reuse. */
    rungs: RungActions,
    /** "Season 2 · Episode 5", or null when these rungs are the whole work's. */
    ladderScope: String?,
    /** False only for a viewer the operator has not confirmed: it decides the sponsor slot. */
    adFree: Boolean,
    /** True when this title has 4K/1080p sources the current viewer may not take. */
    premiumSourcesLocked: Boolean,
    onAskRungs: (season: Int?, episode: Int?) -> Unit,
    hasRungs: (season: Int?, episode: Int?) -> Boolean,
    onOpenVipUpgrade: () -> Unit,
    /**
     * A reload of a title that is already on screen. Null in the normal case. It arrives here
     * rather than through the full-screen error because the viewer can already read the
     * synopsis, the prints and the play button — what failed is the refresh underneath them,
     * and silently keeping a stale list looks exactly like a successful one.
     */
    reloadError: String?,
    onRetryReload: () -> Unit,
    isFavorite: Boolean,
    onToggleFavorite: () -> Unit,
    onShare: () -> Unit,
    contentPadding: PaddingValues,
) {
    val allPrints = (workPrints + seasons.flatMap { it.episodes.flatMap { e -> e.prints } } + seasons.flatMap { it.packedPrints })
    val bestPrint = allPrints.maxByOrNull { it.rankKey }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(
            top = contentPadding.calculateTopPadding(),
            bottom = 40.dp,
            start = 16.dp,
            end = 16.dp,
        ),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        reloadError?.let { failure ->
            item(contentType = "reload-failure") {
                InlineLoadFailure(message = failure, onRetry = onRetryReload)
            }
        }

        item {
            PosterHeader(
                post = post,
                capabilities = capabilities,
                seasonCount = if (isSeries) seasons.size else 0,
                includedLine = includedLine,
            )
        }

        item {
            PrimaryActions(
                bestPrint = bestPrint,
                hasAnyPrint = allPrints.isNotEmpty(),
                resume = resume,
                onPlayResume = onPlayResume,
                onPlay = { bestPrint?.let(onPlayPrint) },
                onKeep = { bestPrint?.let(onKeep) },
                isFavorite = isFavorite,
                onToggleFavorite = onToggleFavorite,
                onShare = onShare,
            )
        }

        // A first-party sponsor slot: no third-party SDK, no hidden network call, and it
        // says who paid for the space. The upgrade is the same flow Settings offers.
        // Removing it for an entitled viewer is the purchase: both the paid card and the
        // rewarded one promise exactly this, on screen, in words.
        if (!adFree) {
            item { SponsorCard(onOpenVipUpgrade = onOpenVipUpgrade) }
        }

        // One row per quality band, exactly as the server collapsed the copies of this
        // title: the viewer picks a picture, never a server, and never a list of links.
        // An episode's rungs belong under that episode, not up here.
        if (!rungs.ladder.isEmpty && ladderScope == null) {
            item {
                QualityRungCard(
                    ladder = rungs.ladder,
                    selectedBand = rungs.selectedBand,
                    onPlayRung = rungs.onPlay,
                    onKeepRung = rungs.onKeep,
                    tierLabel = rungs.tierLabel,
                )
            }
        }

        // The gate is not a silent removal: a viewer who came for the 4K copy is told where
        // it went and given the same upgrade door the sponsor card uses.
        if (premiumSourcesLocked) {
            item { VipSourcesCard(onOpenVipUpgrade = onOpenVipUpgrade) }
        }

        val synopsis = post.synopsis?.takeIf { it.isNotBlank() }
        if (synopsis != null) {
            item { ExpandableSynopsis(text = synopsis) }
        }

        // Print-first summary line (owner brief: "4 official prints available").
        item {
            PrintSummary(officialPrintCount = officialPrintCount, camPrintCount = camPrintCount)
        }

        if (isSeries) {
            if (seasons.size > 1) {
                item { SeasonChips(seasons = seasons, selectedSeason = selectedSeason, onSelect = onSelectSeason) }
            }
            val season = seasons.firstOrNull { it.number == selectedSeason } ?: seasons.firstOrNull()
            if (season != null) {
                item { SeasonHeader(season) }
                if (season.packedPrints.isNotEmpty()) {
                    item {
                        PackedSeasonBanner(
                            season = season,
                            onPlay = onPlayPrint,
                            onKeep = onKeep,
                        )
                    }
                }
                items(season.episodes, key = { "ep-${season.number}-${it.numberWithinSeason}" }) { episode ->
                    // A packed season is one file: its ladder is the season's, not an episode's.
                    val episodeKey = if (episode.onlyPacked) null else episode.numberWithinSeason
                    val scopeLabel = rungScopeLabel(season.number, episodeKey)
                    EpisodeRow(
                        episode = episode,
                        progress = episodeProgress[season.number to episode.numberWithinSeason],
                        onPlayPrint = onPlayPrint,
                        onOpenExternal = onOpenExternal,
                        onKeep = onKeep,
                        scopeLabel = scopeLabel,
                        canChooseQuality = hasRungs(season.number, episodeKey),
                        showQuality = ladderScope == scopeLabel && !rungs.ladder.isEmpty,
                        onChooseQuality = {
                            onAskRungs(season.number, episodeKey)
                        },
                        rungs = rungs,
                    )
                }
            }
        } else {
            if (workPrints.isEmpty()) {
                item {
                    Text(
                        "No playable releases are attached to this title on the connected server yet.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            } else {
                items(workPrints, key = { "print-${it.releaseId}" }) { print ->
                    PrintCard(
                        print = print,
                        onPlayPrint = onPlayPrint,
                        onOpenExternal = onOpenExternal,
                        onKeep = onKeep,
                    )
                }
            }
        }
    }
}

@Composable
private fun PosterHeader(
    post: PostDetail,
    capabilities: List<String>,
    /** Seasons, for a series — 0 for a movie, which has none to count. */
    seasonCount: Int = 0,
    /** What this viewer can watch of this title, in one line — null when it has no prints. */
    includedLine: String? = null,
) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
        // The poster's own colour, sampled once it loads: a 1dp border in the
        // artwork accent frames the poster in its own palette. No bitmap yet
        // (still loading, gated, or failed) means no border at all — the
        // brand jade is the fallback inside rememberArtworkAccent, and a
        // jade frame around a not-yet-loaded poster would be a decoration
        // pretending to be a sample.
        var posterBitmap by remember(post.id) { mutableStateOf<android.graphics.Bitmap?>(null) }
        val posterAccent = rememberArtworkAccent(posterBitmap)
        Box(
            modifier = Modifier
                .width(120.dp)
                .aspectRatio(0.68f)
                .clip(RoundedCornerShape(12.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant)
                .border(
                    width = 1.dp,
                    color = if (posterBitmap != null) posterAccent.copy(alpha = 0.6f) else Color.Transparent,
                    shape = RoundedCornerShape(12.dp),
                ),
            contentAlignment = Alignment.Center,
        ) {
            if (!post.posterUrl.isNullOrBlank()) {
                CatalogImage(
                    url = post.posterUrl,
                    contentDescription = "${post.cleanTitle ?: post.title} poster",
                    modifier = Modifier.fillMaxSize(),
                    fallbackLabel = (post.cleanTitle ?: post.title).take(2).uppercase(),
                    onBitmap = { posterBitmap = it },
                )
            } else {
                ImageFallbackCard(
                    modifier = Modifier.fillMaxSize(),
                    label = (post.cleanTitle ?: post.title).take(2).uppercase(),
                )
            }
        }

        Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(
                text = post.cleanTitle?.takeIf(String::isNotBlank) ?: post.title,
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onBackground,
                maxLines = 3,
                overflow = TextOverflow.Ellipsis,
            )
            val meta = listOfNotNull(
                post.year?.takeIf { it > 0 }?.toString(),
                post.typeLabel,
                post.language?.takeIf(String::isNotBlank),
                formatRuntimeMinutes(post.runtimeMinutes),
                if (seasonCount > 0) "$seasonCount ${if (seasonCount == 1) "season" else "seasons"}" else null,
            )
            if (meta.isNotEmpty()) {
                Text(meta.joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            includedLine?.let { line ->
                Text(line, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
            }
            post.imdbRating?.takeIf(String::isNotBlank)?.let { rating ->
                Pill(text = "★ $rating IMDb", backgroundColor = MaterialTheme.colorScheme.tertiaryContainer, contentColor = MaterialTheme.colorScheme.onTertiaryContainer)
            }
            val genres = post.genreList
            if (genres.isNotEmpty()) {
                Row(
                    modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    genres.forEach { CapabilityChip(it) }
                }
            }
            if (capabilities.isNotEmpty()) {
                Row(
                    modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    capabilities.forEach { CapabilityChip(it) }
                }
            }
        }
    }
}

@Composable
private fun PrimaryActions(
    bestPrint: RankedPrint?,
    hasAnyPrint: Boolean,
    /** The latest scope this device stopped in — null shows plain Play. */
    resume: ResumePoint?,
    onPlayResume: () -> Unit,
    onPlay: () -> Unit,
    onKeep: () -> Unit,
    isFavorite: Boolean,
    onToggleFavorite: () -> Unit,
    onShare: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        // Hero Play Button (full width)
        Button(
            onClick = if (resume != null) onPlayResume else onPlay,
            enabled = if (resume != null) true else bestPrint?.canStart == true,
            modifier = Modifier
                .fillMaxWidth()
                .height(52.dp),
            colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary),
        ) {
            Icon(Icons.Default.PlayArrow, contentDescription = null, modifier = Modifier.size(20.dp))
            Spacer(Modifier.width(8.dp))
            Text(
                text = resume?.label ?: (bestPrint?.playLabel() ?: "Play"),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }

        // Three plain buttons under Play: Add to My List, Download, Share
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            OutlinedButton(
                onClick = onToggleFavorite,
                modifier = Modifier
                    .weight(1f)
                    .height(48.dp),
                contentPadding = PaddingValues(horizontal = 4.dp),
            ) {
                Icon(
                    imageVector = if (isFavorite) Icons.Default.Favorite else Icons.Default.FavoriteBorder,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp),
                    tint = if (isFavorite) MaterialTheme.colorScheme.secondary else MaterialTheme.colorScheme.onSurface,
                )
                Spacer(Modifier.width(4.dp))
                Text(
                    text = favoriteActionLabel(isFavorite),
                    style = MaterialTheme.typography.labelMedium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }

            OutlinedButton(
                onClick = onKeep,
                enabled = hasAnyPrint,
                modifier = Modifier
                    .weight(1f)
                    .height(48.dp),
                contentPadding = PaddingValues(horizontal = 4.dp),
            ) {
                Icon(Icons.Default.Download, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(4.dp))
                Text(
                    text = "Download",
                    style = MaterialTheme.typography.labelMedium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }

            OutlinedButton(
                onClick = onShare,
                modifier = Modifier
                    .weight(1f)
                    .height(48.dp),
                contentPadding = PaddingValues(horizontal = 4.dp),
            ) {
                Icon(Icons.Default.Share, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(4.dp))
                Text(
                    text = "Share",
                    style = MaterialTheme.typography.labelMedium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

/** Action label for the My List toggle button under Play. */
internal fun favoriteActionLabel(isFavorite: Boolean): String =
    if (isFavorite) "My List" else "Add to List"

/**
 * Whether this print gets the viewer somewhere: our player can start a file, or the provider's own
 * page can be opened. One owner, so the hero button and the release-row button never disagree about
 * whether a tapped row does something.
 */
private val RankedPrint.canStart: Boolean get() = playableHere || opensProviderPage

/** The button's word. A page is OPENED, a file is played, and a cam says so while it does. */
private fun RankedPrint.playLabel(): String = when {
    playableHere && isCam -> "Play (cam)"
    playableHere -> "Play"
    // Not "Open": a one-word verb hid that this leaves the app's player for the
    // provider's own page, with its player and its ads. The button says where
    // the tap goes, so the viewer chooses it knowingly.
    opensProviderPage -> "Opens the provider's page"
    else -> "Play"
}

/**
 * The native sponsor slot. It is a first-party house card: the app renders no remote HTML,
 * loads no third-party script, and sends no ad-network request, so it cannot quietly become
 * a tracker. The space is honestly labelled, and the action is the same VIP flow the
 * Settings screen opens.
 */
@Composable
private fun SponsorCard(onOpenVipUpgrade: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .padding(14.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(38.dp)
                .clip(RoundedCornerShape(19.dp))
                .background(MaterialTheme.colorScheme.primaryContainer),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                Icons.Default.Star,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onPrimaryContainer,
                modifier = Modifier.size(20.dp),
            )
        }
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(
                text = "Sponsored",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                text = Brand.copy("sponsor_title", "Go VIP — no sponsor cards"),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = Brand.copy("sponsor_body", "A membership keeps this catalog running."),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        TextButton(onClick = onOpenVipUpgrade) { Text("Upgrade") }
    }
}

@Composable
private fun VipSourcesCard(onOpenVipUpgrade: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(MaterialTheme.colorScheme.surfaceContainerHigh)
            .padding(14.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(
                text = "4K and 1080p are part of VIP",
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = "Free playback stays at 720p and below. Upgrade to unlock every source on this title.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        TextButton(onClick = onOpenVipUpgrade) { Text("Upgrade") }
    }
}

@Composable
private fun ExpandableSynopsis(text: String) {
    var expanded by remember { mutableStateOf(false) }
    Column {
        Text(
            text = text,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurface,
            maxLines = if (expanded) Int.MAX_VALUE else 4,
            overflow = TextOverflow.Ellipsis,
        )
        if (text.length > 180) {
            TextButton(onClick = { expanded = !expanded }) {
                Text(if (expanded) "Show less" else "Read more")
            }
        }
    }
}

@Composable
private fun PrintSummary(officialPrintCount: Int, camPrintCount: Int) {
    val total = officialPrintCount + camPrintCount
    val officialText = when {
        total == 0 -> "No prints available on the connected server"
        officialPrintCount > 0 -> "$officialPrintCount official print${if (officialPrintCount == 1) "" else "s"} available"
        else -> "No official prints"
    }
    Column {
        Text(
            text = officialText,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
            color = if (officialPrintCount > 0) MaterialTheme.colorScheme.onBackground else MaterialTheme.colorScheme.error,
        )
        if (camPrintCount > 0) {
            Text(
                text = "$camPrintCount cam/bootleg print${if (camPrintCount == 1) "" else "s"} — low quality, shown last and labelled.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
        }
    }
}

@Composable
private fun SeasonChips(seasons: List<SeasonGroup>, selectedSeason: Int?, onSelect: (Int) -> Unit) {
    Column {
        SectionHeader(title = "Seasons", modifier = Modifier.padding(horizontal = 0.dp))
        Row(
            modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            seasons.forEach { s ->
                FilterChip(
                    selected = selectedSeason == s.number,
                    onClick = { onSelect(s.number) },
                    label = { Text("Season ${s.number} · ${s.episodeCount}") },
                    leadingIcon = { SeasonThumbnail(season = s, modifier = Modifier.size(24.dp)) },
                )
            }
        }
    }
}

/** A season's own artwork at chip size. Null art is answered by the branded gradient, not a hole. */
@Composable
private fun SeasonThumbnail(season: SeasonGroup, modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(4.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant),
    ) {
        val art = season.artworkUrl
        if (art != null) {
            CatalogImage(
                url = art,
                contentDescription = null,
                modifier = Modifier.fillMaxSize(),
                fallbackLabel = "S${season.number}",
            )
        } else {
            ImageFallbackCard(modifier = Modifier.fillMaxSize())
        }
    }
}

/**
 * The selected season's header. Its image is the season's slice of the work's wide art, so a
 * multi-season show never presents the same root poster above every season's episode list.
 */
@Composable
private fun SeasonHeader(season: SeasonGroup) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .aspectRatio(3.2f)
            .clip(RoundedCornerShape(12.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant),
    ) {
        val art = season.artworkUrl
        if (art != null) {
            CatalogImage(
                url = art,
                contentDescription = "Season ${season.number} artwork",
                modifier = Modifier.fillMaxSize(),
                fallbackLabel = "S${season.number}",
            )
        } else {
            ImageFallbackCard(modifier = Modifier.fillMaxSize(), label = "S${season.number}")
        }
        Box(
            Modifier
                .fillMaxSize()
                .background(
                    Brush.verticalGradient(
                        listOf(
                            Color.Transparent,
                            MaterialTheme.colorScheme.scrim.copy(alpha = 0.85f),
                        )
                    )
                )
        )
        Column(
            modifier = Modifier.align(Alignment.BottomStart).padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            Text(
                text = "Season ${season.number}",
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onBackground,
            )
            Text(
                text = "${season.episodeCount} episode${if (season.episodeCount == 1) "" else "s"}",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onBackground,
            )
        }
    }
}

@Composable
private fun PackedSeasonBanner(season: SeasonGroup, onPlay: (RankedPrint) -> Unit, onKeep: (RankedPrint) -> Unit) {
    val pack = season.packedPrints.maxByOrNull { it.rankKey } ?: return
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(
            "This season is offered as one file (${pack.qualityLabel}).",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurface,
        )
        Text(
            "Playing a packed season starts the whole-season video — pick a specific episode below for per-episode files when available.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { onPlay(pack) }) {
                Icon(Icons.Default.PlayArrow, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
                Text("Play season")
            }
            OutlinedButton(onClick = { onKeep(pack) }) {
                Icon(Icons.Default.Download, contentDescription = "Download season")
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun EpisodeRow(
    episode: EpisodeGroup,
    /** This episode's progress on this device — null when never watched. */
    progress: EpisodeProgress?,
    onPlayPrint: (RankedPrint) -> Unit,
    onOpenExternal: (RankedPrint) -> Unit,
    onKeep: (RankedPrint) -> Unit,
    /** "Season 1 · Episode 5" — the card the row opens has to say what it is the ladder of. */
    scopeLabel: String?,
    canChooseQuality: Boolean,
    showQuality: Boolean,
    onChooseQuality: () -> Unit,
    rungs: RungActions,
) {
    var expanded by remember(episode.absoluteNumber) { mutableStateOf(false) }
    val best = episode.bestPrint
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(MaterialTheme.colorScheme.surface)
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Box(
                modifier = Modifier
                    .width(88.dp)
                    .aspectRatio(16f / 9f)
                    .clip(RoundedCornerShape(8.dp))
                    .background(MaterialTheme.colorScheme.surfaceVariant),
                contentAlignment = Alignment.Center,
            ) {
                val still = episode.stillUrl
                if (still != null) {
                    CatalogImage(
                        url = still,
                        contentDescription = "Episode ${episode.numberWithinSeason} preview",
                        modifier = Modifier.fillMaxSize(),
                        fallbackLabel = "E${episode.numberWithinSeason}",
                    )
                } else {
                    ImageFallbackCard(modifier = Modifier.fillMaxSize())
                }
                Box(
                    modifier = Modifier
                        .align(Alignment.BottomStart)
                        .padding(3.dp)
                        .clip(RoundedCornerShape(4.dp))
                        .background(MaterialTheme.colorScheme.scrim.copy(alpha = 0.75f))
                        .padding(horizontal = 4.dp, vertical = 1.dp),
                ) {
                    Text(
                        text = "${episode.absoluteNumber}",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onBackground,
                    )
                }
            }
            Column(Modifier.weight(1f)) {
                Text(
                    text = episode.title ?: "Episode ${episode.numberWithinSeason}",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onSurface,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                val suffix = if (episode.onlyPacked) " · packed in season file" else
                    if (episode.prints.size > 1) " · ${episode.prints.size} prints" else ""
                if (best != null) {
                    // The same three axes the print card leads with, condensed for the row:
                    // quality, HDR and audio. Subtitles stay on the expanded print card.
                    FlowRow(
                        horizontalArrangement = Arrangement.spacedBy(4.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        PrintQualityBadge(print = best)
                        HdrBadge(print = best)
                        AudioBadge(print = best)
                    }
                } else {
                    Text(
                        text = "No quality info",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                if (suffix.isNotBlank()) {
                    Text(
                        text = suffix.trim().removePrefix("·").trim(),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            best?.let {
                IconButton(
                    onClick = { onPlayPrint(it) },
                    modifier = Modifier.size(48.dp),
                ) {
                    Icon(Icons.Default.PlayArrow, contentDescription = "Play episode ${episode.numberWithinSeason}", tint = MaterialTheme.colorScheme.primary)
                }
            }
            if (canChooseQuality) {
                IconButton(
                    onClick = onChooseQuality,
                    modifier = Modifier.size(48.dp),
                ) {
                    Icon(
                        Icons.Default.Tune,
                        contentDescription = "Choose quality for episode ${episode.numberWithinSeason}",
                        tint = if (showQuality) MaterialTheme.colorScheme.primary
                        else MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }

        if (episode.onlyPacked) {
            Pill(text = "Whole season in one file", backgroundColor = MaterialTheme.colorScheme.surfaceVariant, contentColor = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        // The mark this device left: a bar and what is left, or "Watched"
        // when it ran to the end. A row never watched shows nothing — no
        // bar, no guess — because an empty bar would claim a position
        // nobody has.
        progress?.let { p ->
            if (p.watched) {
                Text(
                    text = "Watched",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.primary,
                )
            } else if (p.fraction != null) {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    LinearProgressIndicator(
                        progress = { p.fraction },
                        modifier = Modifier.fillMaxWidth(),
                    )
                    p.remainingLabel?.let { label ->
                        Text(
                            text = label,
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }
        // The collapsed ladder replaces the print list wherever the server could fold one
        // best copy per band; a ledger that cannot is still shown as before, not hidden.
        if (episode.prints.size > 1 && !canChooseQuality) {
            TextButton(onClick = { expanded = !expanded }) {
                Text(if (expanded) "Hide prints" else "Show ${episode.prints.size} prints")
            }
        }
        if (expanded) {
            episode.prints.forEach { print ->
                PrintCard(
                    print = print,
                    onPlayPrint = onPlayPrint,
                    onOpenExternal = onOpenExternal,
                    onKeep = onKeep,
                )
            }
        }
        if (showQuality) {
            QualityRungCard(
                ladder = rungs.ladder,
                selectedBand = rungs.selectedBand,
                onPlayRung = rungs.onPlay,
                onKeepRung = rungs.onKeep,
                scopeTitle = scopeLabel,
                tierLabel = rungs.tierLabel,
            )
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun PrintCard(
    print: RankedPrint,
    onPlayPrint: (RankedPrint) -> Unit,
    onOpenExternal: (RankedPrint) -> Unit,
    onKeep: (RankedPrint) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(MaterialTheme.colorScheme.surface)
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            PrintQualityBadge(print = print)
            if (print.isCam) CamBadge()
            Spacer(Modifier.weight(1f))
            print.bestOptionLabel?.let {
                Text(
                    text = it,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        if (print.detailLine.isNotBlank()) {
            Text(print.detailLine, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }

        // The tier's own facts, as badges rather than one run-on sentence: a 4K HDR
        // WEB-DL print and its audio/subtitle story read in a glance here.
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            HdrBadge(print = print)
            PrintSourceBadge(print = print)
            AudioBadge(print = print)
            SubtitleBadge(print = print)
        }

        if (print.isCam) {
            Text(
                "This is a cam/bootleg recording. Pick an official print above when one exists.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
        }

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            Button(
                onClick = { onPlayPrint(print) },
                enabled = print.canStart,
                modifier = Modifier.weight(1f),
            ) {
                Icon(Icons.Default.PlayArrow, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
                Text(print.playLabel())
            }
            OutlinedButton(onClick = { onKeep(print) }) {
                Icon(Icons.Default.Download, contentDescription = "Download video")
            }
            if (print.playableHere) {
                IconButton(onClick = { onOpenExternal(print) }, modifier = Modifier.size(40.dp)) {
                    Icon(Icons.Default.OpenInNew, contentDescription = "Open in external player",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}

// ── Platform helpers (share keeps the app's own copy honest) ────────────────
private fun shareTitle(context: Context, post: PostDetail, onShared: () -> Unit) {
    val title = post.cleanTitle?.takeIf { it.isNotBlank() } ?: post.title
    // The template is the operator's words; the link is the app's own deep
    // link to the title's page — a share that only says "check this out"
    // leaves the receiver with nowhere to go.
    val text = Brand.copy("share_template", "", "title" to title) +
        "\n" + DeepLinks.detailUri(post.id)
    val intent = Intent(Intent.ACTION_SEND).apply {
        type = "text/plain"
        putExtra(Intent.EXTRA_SUBJECT, title)
        putExtra(Intent.EXTRA_TEXT, text)
    }
    try {
        context.startActivity(Intent.createChooser(intent, "Share via").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        // The chooser firing is the share, as far as this phone can know: the
        // server pays once a day on the report, and a failed report is silent
        // because the share already left the phone.
        onShared()
    } catch (_: Exception) {
        Toast.makeText(context, "No share target available", Toast.LENGTH_SHORT).show()
    }
}

private fun openInExternalPlayer(context: Context, url: String) {
    try {
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(Uri.parse(url), "video/*")
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(Intent.createChooser(intent, "Play stream with…"))
    } catch (_: Exception) {
        try {
            context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        } catch (_: Exception) {
            Toast.makeText(context, "No player or browser installed", Toast.LENGTH_SHORT).show()
        }
    }
}

/**
 * Session 73 (Phase 5): open a plain web link in the external browser — the
 * Web Download link for a free viewer. Unlike [openInExternalPlayer] this sets
 * no MIME type, so the system picks the browser, not a video player.
 */
private fun openWebPage(context: Context, url: String) {
    try {
        context.startActivity(
            Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        )
    } catch (_: Exception) {
        Toast.makeText(context, "No browser installed", Toast.LENGTH_SHORT).show()
    }
}
