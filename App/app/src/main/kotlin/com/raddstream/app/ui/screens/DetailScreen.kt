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
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.WindowInsetsSides
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.displayCutout
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.only
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
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
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.hilt.navigation.compose.hiltViewModel
import com.raddstream.app.brand.Brand
import com.raddstream.app.network.models.PostDetail
import com.raddstream.app.network.models.WireText
import com.raddstream.app.network.models.parseCastNames
import com.raddstream.app.ui.components.AudioBadge
import com.raddstream.app.ui.components.CapabilityChip
import com.raddstream.app.ui.components.CamBadge
import com.raddstream.app.ui.components.CatalogImage
import com.raddstream.app.ui.components.DetailSkeleton
import com.raddstream.app.ui.components.ErrorState
import com.raddstream.app.ui.components.HdrBadge
import com.raddstream.app.ui.components.ImageFallbackCard
import com.raddstream.app.ui.components.InlineLoadFailure
import com.raddstream.app.ui.components.Pill
import com.raddstream.app.ui.components.UserWords
import com.raddstream.app.ui.components.PrintQualityBadge
import com.raddstream.app.ui.components.PrintSourceBadge
import com.raddstream.app.ui.components.QualityRungCard
import com.raddstream.app.ui.components.RaddDialogTitle
import com.raddstream.app.ui.components.RatingBadge
import com.raddstream.app.ui.components.SectionHeader
import com.raddstream.app.ui.components.SubtitleBadge
import com.raddstream.app.ui.components.audioBadgeText
import com.raddstream.app.ui.components.hdrBadgeText
import com.raddstream.app.ui.components.raddFilterChipColors
import com.raddstream.app.ui.components.sourceBadgeText
import com.raddstream.app.ui.components.subtitleBadgeText
import com.raddstream.app.ui.layout.CardGeometry
import com.raddstream.app.player.LadderForScope
import com.raddstream.app.player.QualityOption
import com.raddstream.app.player.preferredAudioLanguages
import com.raddstream.app.ui.navigation.DeepLinks
import com.raddstream.app.ui.theme.PressHaptics
import com.raddstream.app.ui.theme.pressScale
import com.raddstream.app.ui.theme.rememberArtworkAccent
import com.raddstream.app.viewmodel.DetailNavigationEvent
import com.raddstream.app.viewmodel.DetailViewModel
import com.raddstream.app.viewmodel.downloadConfirmLabel
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
    /** An actor chip in the cast row: open that actor's titles in Search. */
    onActorClick: (String) -> Unit = {},
    /** Session 121 (P-26): the hero's Watch Now — start the best print once the title loads. */
    autoplay: Boolean = false,
    viewModel: DetailViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }
    val context = LocalContext.current
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

    // Session 121 (P-26): the hero's Watch Now. Once per title, when the title has
    // loaded: the best print starts, and a title with nothing playable (or a locked
    // print) simply stays here with the reason in front of the viewer — `playBest`
    // never navigates, so there is nothing to unwind.
    // Session 123 (DE-1): autoplay respects Resume — a title the viewer left
    // halfway through restarts from where they left off, not from the
    // beginning. `playResume` is the same path the Resume card's own button
    // takes, so the behaviour is identical either way in. The effect waits
    // for `resumeLoaded`: the resume lookup reads the local history in its
    // own coroutine and lands after the title does, so deciding on `post`
    // alone would almost always decide before the answer existed and play
    // from the beginning anyway.
    var autoPlayedFor by remember { mutableStateOf<Int?>(null) }
    LaunchedEffect(state.post?.id, state.resumeLoaded, autoplay) {
        val post = state.post ?: return@LaunchedEffect
        if (autoplay && state.resumeLoaded && autoPlayedFor != post.id) {
            autoPlayedFor = post.id
            if (state.resume != null && state.resumePlayable) viewModel.playResume() else viewModel.playBest()
        }
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = {
            TopAppBar(
                // Audit #25: the bar carries only the back arrow (and
                // actions). The title appears ONCE, next to the poster
                // below — the bar used to repeat it, so the screen read
                // its own name twice.
                title = {},
                // Samsung RTL (v1.1.2, Issue 9): in landscape the camera
                // cutout sits on one side, and the Scaffold's insets do not
                // carry it — the back arrow must clear the hole, not sit
                // under it. The cutout inset is zero in portrait, so this
                // changes nothing there.
                modifier = Modifier.windowInsetsPadding(
                    WindowInsets.displayCutout.only(WindowInsetsSides.Horizontal),
                ),
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
        // Issue 9: the safe-drawing insets (system bars + display cutout)
        // are what keep the content off the camera hole and the system
        // navigation in landscape; the Scaffold's padding alone does not
        // carry the cutout. Every state of this screen goes through the
        // same padding, so the skeleton and the error state cannot sit
        // under the cutout either.
        val safeDrawingPadding = WindowInsets.safeDrawing.asPaddingValues()
        val layoutDirection = LocalLayoutDirection.current
        val detailPadding = detailContentPadding(paddingValues, safeDrawingPadding, layoutDirection)
        val post = state.post
        when {
            state.isLoading -> DetailSkeleton(Modifier.padding(detailPadding))
            state.error != null && post == null -> ErrorState(
                title = "Couldn't load this title",
                message = state.error ?: "Unable to load title.",
                onRetry = viewModel::loadDetail,
                modifier = Modifier.padding(detailPadding),
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
                /** Phase 7 (D1): "Start over" — forget where viewing stopped. */
                onStartOver = viewModel::removeProgress,
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
                    // Audit #32: the card leads with the viewer's own audio.
                    preferredAudio = preferredAudioLanguages(state.region),
                ),
                ladderScope = rungScopeLabel(state.ladderSeason, state.ladderEpisode),
                adFree = state.adFree,
                premiumSourcesLocked = state.premiumSourcesLocked,
                onAskRungs = viewModel::showRungsFor,
                hasRungs = { season, episode -> !viewModel.ladderFor(season, episode).isEmpty },
                onOpenVipUpgrade = onOpenVipUpgrade,
                onActorClick = onActorClick,
                reloadError = state.error,
                onRetryReload = viewModel::loadDetail,
                isFavorite = state.isFavorite,
                onToggleFavorite = viewModel::toggleFavorite,
                onShare = {
                    shareTitle(context, post) { viewModel.reportShare(post.workRef) }
                },
                contentPadding = detailPadding,
            )
        }
    }

    state.pendingKeep?.let { pending ->
        KeepConfirmDialog(
            pending = pending,
            onConfirm = viewModel::confirmKeep,
            onDismiss = viewModel::dismissKeep,
            // UI-fix P1-D9: the coins Direct Link row is gone — it opened the
            // browser in the middle of a download (the one remaining external-
            // browser route on the download path). It returns only when a bought
            // credit can download in-app through the same DownloadService.
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
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        // D-2: one dialog title style everywhere — display family,
        // semibold, 20sp.
        title = { RaddDialogTitle("Download this title?") },
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
            }
        },
        confirmButton = {
            // Audit #10/#11: one dialog, one primary action — the version
            // and its size, named together.
            Button(onClick = onConfirm) { Text(downloadConfirmLabel(pending.printLabel, pending.sizeBytes)) }
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
    /** The viewer's preferred audio languages (audit #32) — empty orders nothing. */
    val preferredAudio: Set<String> = emptySet(),
)

/** Which scope a ladder belongs to, in the viewer's words. Null means the whole work. */
private fun rungScopeLabel(season: Int?, episode: Int?): String? = when {
    season != null && episode != null -> "Season $season · Episode $episode"
    episode != null -> "Episode $episode"
    season != null -> "Season $season"
    else -> null
}

/**
 * The detail page's content padding, safe for landscape (Samsung RTL
 * v1.1.2, Issue 9). The page is a single portrait column, and in
 * landscape its full-width Play button ran off the right edge while the
 * system navigation overlapped it: the Scaffold's padding covers the
 * status and navigation bars, but not the display cutout — on a phone
 * whose camera hole sits mid-height on one side in landscape, the
 * content ran to the physical edge and under the hole.
 *
 * Every side takes the larger of the Scaffold's ask and the safe-drawing
 * inset (system bars + cutout), so the two are never double-counted: in
 * portrait the safe-drawing sides are zero and nothing changes; in
 * landscape the cutout side wins and the content clears it. The 40 dp of
 * breathing room stays on top of the bottom (Session 121, P-22: the
 * bottom VIP card sat half-hidden behind the system nav bar when this
 * was a fixed 40 dp while the Scaffold's own bottom padding was
 * ignored). Pure so the max-per-side rule is testable without a device.
 */
internal fun detailContentPadding(
    scaffoldPadding: PaddingValues,
    safeDrawingPadding: PaddingValues,
    layoutDirection: LayoutDirection,
    baseHorizontal: Dp = 16.dp,
    bottomBreathing: Dp = 40.dp,
): PaddingValues {
    // This Compose version (BOM 2024.06.00 / foundation-layout 1.7) has no
    // calculateStartPadding/calculateEndPadding on PaddingValues, so
    // start/end resolve through the left/right members: in LTR the start
    // side is the physical left, in RTL it is the physical right.
    val safeStart = if (layoutDirection == LayoutDirection.Ltr) {
        safeDrawingPadding.calculateLeftPadding(layoutDirection)
    } else {
        safeDrawingPadding.calculateRightPadding(layoutDirection)
    }
    val safeEnd = if (layoutDirection == LayoutDirection.Ltr) {
        safeDrawingPadding.calculateRightPadding(layoutDirection)
    } else {
        safeDrawingPadding.calculateLeftPadding(layoutDirection)
    }
    return PaddingValues(
        start = maxOf(baseHorizontal, safeStart),
        top = maxOf(
            scaffoldPadding.calculateTopPadding(),
            safeDrawingPadding.calculateTopPadding(),
        ),
        end = maxOf(baseHorizontal, safeEnd),
        bottom = maxOf(
            scaffoldPadding.calculateBottomPadding(),
            safeDrawingPadding.calculateBottomPadding(),
        ) + bottomBreathing,
    )
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
    /** Phase 7 (D1): "Start over" — forget where viewing stopped, on the server and locally. */
    onStartOver: () -> Unit = {},
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
    /** An actor chip in the cast row: open that actor's titles in Search. */
    onActorClick: (String) -> Unit = {},
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
    // UI-fix P1-D2: the version list folds to 3 until the viewer asks for all.
    var showAllVersions by remember { mutableStateOf(false) }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        // Already inset-aware: the caller passes [detailContentPadding],
        // which takes the larger of the Scaffold's ask and the safe-drawing
        // inset per side (system bars + display cutout), plus the 40 dp of
        // breathing room at the bottom (Session 121, P-22).
        contentPadding = contentPadding,
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
                onStartOver = onStartOver,
                isFavorite = isFavorite,
                onToggleFavorite = onToggleFavorite,
                onShare = onShare,
            )
        }

        // The "No playable copy" sentence now rides inside PrimaryActions,
        // above the Download hero — this item used to repeat it below.
        // A first-party VIP house card: no third-party SDK, no hidden network call.
        // It is our own membership, not a sponsored slot, so it carries no
        // "Sponsored" label — and it is shown only when the VIP-sources card is
        // not, so the two upsells never stack (Session 121, P-10).
        // Audit #30: neither upsell shows on a title with no playable copy —
        // selling VIP on a title the viewer cannot watch is the wrong pitch.
        val playable = resume != null || bestPrint?.canStart == true
        if (!adFree && !premiumSourcesLocked && playable) {
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
                    preferredAudio = rungs.preferredAudio,
                )
            }
        }

        // The gate is not a silent removal: a viewer who came for the 4K copy is told where
        // it went and given the same upgrade door the sponsor card uses.
        // Audit #30: like the sponsor card, never on a title with no playable copy.
        if (premiumSourcesLocked && playable) {
            item { VipSourcesCard(onOpenVipUpgrade = onOpenVipUpgrade) }
        }

        val synopsis = post.synopsis?.takeIf { it.isNotBlank() }
        if (synopsis != null) {
            item { ExpandableSynopsis(text = UserWords.stripSectionMarkers(synopsis)) }
        }

        // Cast, from the catalog's own scraped list — only what the server
        // actually stored, parsed into names (see parseCastNames). A title
        // with no cast data shows no section at all: no fake names, no
        // empty "Cast" header. A tap searches that actor's titles.
        val cast = parseCastNames(post.castNames)
        if (cast.isNotEmpty()) {
            item { CastSection(cast = cast, onActorClick = onActorClick) }
        }

        // Version-first summary line (owner brief: "4 official prints available").
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
                        "Nothing to play for this title yet.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            } else {
                // UI-fix P1-D2: a title can carry a long list of near-identical
                // version cards (Salaar has 10 posts). Show at most 3, with
                // "Show all versions" for the rest — the quality rungs above
                // already carry the folded choice.
                val shownPrints = if (showAllVersions) workPrints else workPrints.take(3)
                val workCopies = copyNumbers(workPrints)
                items(shownPrints, key = { "print-${it.releaseId}" }) { print ->
                    PrintCard(
                        print = print,
                        onPlayPrint = onPlayPrint,
                        onOpenExternal = onOpenExternal,
                        onKeep = onKeep,
                        copyIndex = workCopies[print.releaseId]?.first ?: 1,
                        copyTotal = workCopies[print.releaseId]?.second ?: 1,
                    )
                }
                if (workPrints.size > 3) {
                    item {
                        TextButton(onClick = { showAllVersions = !showAllVersions }) {
                            Text(
                                if (showAllVersions) "Show fewer versions"
                                else "Show all ${workPrints.size} versions",
                            )
                        }
                    }
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
        // (still loading, gated, or failed) means no accent sample — but the
        // frame is still there, in the neutral outlineVariant, so the poster
        // always reads as a defined card against the dark background instead
        // of a flat rectangle that blends into it (Robo run 6: the unloaded
        // poster's image contrast, 1.33). A neutral frame is not a fake
        // accent sample: it claims no colour from the artwork.
        var posterBitmap by remember(post.id) { mutableStateOf<android.graphics.Bitmap?>(null) }
        val posterAccent = rememberArtworkAccent(posterBitmap)
        Box(
            modifier = Modifier
                .width(CardGeometry.DETAIL_POSTER_WIDTH_DP.dp)
                .aspectRatio(CardGeometry.POSTER_ASPECT)
                .clip(RoundedCornerShape(12.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant)
                .border(
                    width = 1.dp,
                    color = if (posterBitmap != null) posterAccent.copy(alpha = 0.6f) else MaterialTheme.colorScheme.outlineVariant,
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
            // Robo run 3: this title text is identical to the bar title above
            // it, so the big title carries its own spoken name.
            val titleText = post.cleanTitle?.takeIf(String::isNotBlank) ?: post.title
            Text(
                text = UserWords.breakableTitle(titleText),
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onBackground,
                maxLines = 3,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.semantics { contentDescription = "Title: $titleText" },
            )
            val meta = listOfNotNull(
                post.year?.takeIf { it > 0 }?.toString(),
                post.typeLabel,
                // P-5 (Session 121): normalize again at the render site — a language that
                // arrives as a raw JSON array string ("[\"Tamil\", \"English\"]") reads
                // "Tamil, English". Idempotent with the mapper-side normalization.
                WireText.listOf(post.language).joinToString(", ").takeIf { it.isNotBlank() },
                formatRuntimeMinutes(post.runtimeMinutes),
                if (seasonCount > 0) "$seasonCount ${if (seasonCount == 1) "season" else "seasons"}" else null,
            )
            if (meta.isNotEmpty()) {
                Text(meta.joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            includedLine?.let { line ->
                Text(line, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
            }
            UserWords.displayRating(post.imdbRating)?.let { rating ->
                RatingBadge(rating = "$rating IMDb")
            }
            // UI-fix P1-D5: genres + capabilities were two identical scrolling
            // pill rows under the title. One row now; capabilities ride with
            // the genres.
            val allChips = post.genreList + capabilities
            if (allChips.isNotEmpty()) {
                Row(
                    modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    allChips.forEach { CapabilityChip(it) }
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
    /** Phase 7 (D1): forget where viewing stopped — only offered while a resume exists. */
    onStartOver: () -> Unit,
    isFavorite: Boolean,
    onToggleFavorite: () -> Unit,
    onShare: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        // Audit #29: whether anything here can start. A resume is playable
        // by definition (only a playable resume is ever passed in).
        val playable = resume != null || bestPrint?.canStart == true
        // UI-fix P1-D1: the hero button plays video, nothing else. A title
        // whose only option is the provider's own page gets a secondary row
        // instead — the big green button must never open a web page.
        val canPlayHere = resume != null || bestPrint?.playableHere == true
        val providerOnly = resume == null && bestPrint != null &&
            !bestPrint.playableHere && bestPrint.opensProviderPage
        if (canPlayHere) {
            // Hero Play Button (full width). UI-fix P1-X1: press scale +
            // haptic on the primary action.
            val playSource = remember { MutableInteractionSource() }
            PressHaptics(playSource)
            Button(
                onClick = if (resume != null) onPlayResume else onPlay,
                interactionSource = playSource,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(52.dp)
                    .pressScale(playSource),
                // D-29: a disabled Play keeps the same shape and language as the
                // enabled one — a tonal fill, not a dead grey slab. The reason it
                // cannot start rides right under the button, so the tonal state
                // is never mistaken for a working one.
                colors = ButtonDefaults.buttonColors(
                    containerColor = MaterialTheme.colorScheme.primary,
                ),
            ) {
                Icon(Icons.Default.PlayArrow, contentDescription = null, modifier = Modifier.size(20.dp))
                Spacer(Modifier.width(8.dp))
                Text(
                    text = resume?.label ?: "Play",
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        } else if (providerOnly) {
            OutlinedButton(
                onClick = onPlay,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(52.dp),
            ) {
                Icon(Icons.Default.OpenInNew, contentDescription = null, modifier = Modifier.size(20.dp))
                Spacer(Modifier.width(8.dp))
                Text(
                    text = "Watch on the provider's page",
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Text(
                text = "This title plays on the provider's own page, with its own player and ads.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        } else {
            // No playable copy: Play is hidden, never a dead button — and
            // Download becomes the primary, full-width and green, with the
            // reason in plain words. When no print exists at all there is
            // nothing to download either, so the button stays disabled and
            // the sentence stays out (it would promise a download that
            // does not exist).
            if (hasAnyPrint) {
                Text(
                    text = "Not available to stream yet — download it instead.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Button(
                onClick = onKeep,
                enabled = hasAnyPrint,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(52.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = MaterialTheme.colorScheme.primary,
                    disabledContainerColor = MaterialTheme.colorScheme.primaryContainer,
                    disabledContentColor = MaterialTheme.colorScheme.onPrimaryContainer,
                ),
            ) {
                Icon(Icons.Default.Download, contentDescription = null, modifier = Modifier.size(20.dp))
                Spacer(Modifier.width(8.dp))
                Text(
                    text = "Download",
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }

        // Three plain buttons under Play: Add to My List, Download, Share.
        // When Download is already the hero above, it leaves this row —
        // the same action must never appear twice on one screen.
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

            if (playable) {
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

        // Phase 7 (D1): only while a resume exists — after "Start over" the
        // button above reads plain Play again, so this row must not linger.
        if (resume != null) {
            TextButton(onClick = onStartOver) {
                Text("Start over")
            }
        }
    }
}

/** Action label for the My List toggle button under Play. */
internal fun favoriteActionLabel(isFavorite: Boolean): String =
    if (isFavorite) "Saved in My List" else "Save to My List"

/**
 * Whether this print gets the viewer somewhere: our player can start a file, or the provider's own
 * page can be opened. One owner, so the hero button and the release-row button never disagree about
 * whether a tapped row does something.
 */
private val RankedPrint.canStart: Boolean get() = playableHere || opensProviderPage

/** The button's word. A page is OPENED, a file is played, and a cam says so while it does. */
private fun RankedPrint.playLabel(): String = when {
    playableHere -> "Play"
    // Not "Open": a one-word verb hid that this leaves the app's player for the
    // provider's own page, with its player and its ads. The button says where
    // the tap goes, so the viewer chooses it knowingly.
    opensProviderPage -> "Opens the provider's page"
    else -> "Play"
}

/**
 * The first-party VIP house card: the app renders no remote HTML, loads no third-party
 * script, and sends no ad-network request, so it cannot quietly become a tracker. The
 * action is the same VIP flow the Settings screen opens.
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
                .clip(RoundedCornerShape(20.dp))
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
                text = Brand.copy("sponsor_title", "Go VIP"),
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
                text = "Free playback stays at 720p and below. Upgrade to unlock 4K and 1080p on this title.",
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
    var hasOverflow by remember { mutableStateOf(false) }
    Column {
        Text(
            text = text,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurface,
            maxLines = if (expanded) Int.MAX_VALUE else 4,
            overflow = TextOverflow.Ellipsis,
            // D-31: the "Read more" affordance appears exactly when the text
            // is actually cut — a length gate hid it on short-but-tall text
            // and showed it on long-but-fitting text. The layout result is
            // the truth; a short synopsis that fits shows no button at all.
            onTextLayout = { result -> hasOverflow = result.hasVisualOverflow },
        )
        if (expanded || hasOverflow) {
            TextButton(onClick = { expanded = !expanded }) {
                Text(if (expanded) "Show less" else "Read more")
            }
        }
    }
}

/**
 * The cast row: one tappable chip per actor, in the order the catalog
 * lists them. Six chips, then a plain count of the rest: the row is a
 * doorway to the actor's titles, not a full cast list, and there is no
 * cast screen to open. A tap searches the actor in the search bar, which
 * matches `cast_names` server-side.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun CastSection(cast: List<String>, onActorClick: (String) -> Unit) {
    // UI-fix P1-D3: "and N more" was dead text with no cast screen to open.
    // It now expands the row in place.
    var expanded by remember { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(
            text = "Cast",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
            color = MaterialTheme.colorScheme.onSurface,
        )
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            (if (expanded) cast else cast.take(6)).forEach { actor ->
                FilterChip(
                    colors = raddFilterChipColors(),
                    selected = false,
                    onClick = { onActorClick(actor) },
                    label = { Text(actor) },
                    // Robo run 2: a cast chip is 32dp tall — the touch-target
                    // floor is 48dp, so the chip itself carries it.
                    modifier = Modifier.heightIn(min = 48.dp),
                )
            }
        }
        if (cast.size > 6) {
            TextButton(onClick = { expanded = !expanded }) {
                Text(
                    if (expanded) "Show less" else "and ${cast.size - 6} more",
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
    }
}

@Composable
private fun PrintSummary(officialPrintCount: Int, camPrintCount: Int) {
    val total = officialPrintCount + camPrintCount
    val officialText = when {
        total == 0 -> "No versions available here yet"
        officialPrintCount > 0 -> "$officialPrintCount official version${if (officialPrintCount == 1) "" else "s"} available"
        else -> "No official versions"
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
                text = "$camPrintCount cam/bootleg version${if (camPrintCount == 1) "" else "s"} — low quality, shown last and labelled.",
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
                    colors = raddFilterChipColors(),
                    selected = selectedSeason == s.number,
                    onClick = { onSelect(s.number) },
                    label = { Text("Season ${s.number} · ${s.episodeCount}") },
                    leadingIcon = { SeasonThumbnail(season = s, modifier = Modifier.size(24.dp)) },
                    // Robo run 2: a season chip is 32dp tall — the touch-target
                    // floor is 48dp, so the chip itself carries it.
                    modifier = Modifier.heightIn(min = 48.dp),
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
            .aspectRatio(CardGeometry.SEASON_ART_ASPECT)
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
    // The only copy this row can start: a download-only episode has a best
    // print but no playable one, so the triangle must not pretend otherwise.
    val playableBest = best?.takeIf { it.canStart }
    // A row that looks tappable must do something: open the episode's quality
    // ladder when it has one, else play its playable copy. A download-only
    // episode has neither — the "Download only" label below says so instead
    // of a dead tap.
    val rowAction: (() -> Unit)? = when {
        canChooseQuality -> onChooseQuality
        playableBest != null -> { { onPlayPrint(playableBest) } }
        else -> null
    }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(MaterialTheme.colorScheme.surface)
            .then(if (rowAction != null) Modifier.clickable(onClick = rowAction) else Modifier)
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Box(
                modifier = Modifier
                    .width(88.dp)
                    .aspectRatio(CardGeometry.WIDE_ART_ASPECT)
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
                    if (episode.prints.size > 1) " · ${episode.prints.size} versions" else ""
                if (best != null) {
                    // The same three axes the print card leads with, condensed for the row:
                    // quality, HDR and audio. Subtitles stay on the expanded print card.
                    // Robo run 2: the same "Picture quality 720p" badge repeated on
                    // every episode row. Paint-only here: the facts are spoken once,
                    // on the Play button below — but only while a Play button exists
                    // to carry them; a download-only episode keeps its badges, its
                    // only spoken quality signal.
                    FlowRow(
                        modifier = if (playableBest != null) Modifier.clearAndSetSemantics { } else Modifier,
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
            // The row's badge facts, spoken once on the Play button (the badge
            // row above is paint-only while this button exists): quality, HDR,
            // audio. A download-only episode has no Play button, so its badges
            // stay spoken — see the FlowRow modifier above.
            val episodeFacts = playableBest?.let { bestPrint ->
                listOfNotNull(
                    hdrBadgeText(bestPrint.hdr)?.let { "High dynamic range $it" },
                    audioBadgeText(bestPrint.dualAudio, bestPrint.languages)?.let { "Audio $it" },
                ).joinToString(prefix = ", ", separator = ", ").ifBlank { "" }
            } ?: ""
            if (playableBest != null) {
                IconButton(
                    onClick = { onPlayPrint(playableBest) },
                    modifier = Modifier.size(48.dp),
                ) {
                    Icon(Icons.Default.PlayArrow, contentDescription = "Play episode ${episode.numberWithinSeason}, ${playableBest.qualityLabel}$episodeFacts", tint = MaterialTheme.colorScheme.primary)
                }
            } else if (best != null) {
                // No playable copy on this episode: the button that would have
                // pretended to play becomes the honest word instead.
                Text(
                    text = "Download only",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
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
                Text(if (expanded) "Hide versions" else "Show ${episode.prints.size} versions")
            }
        }
        if (expanded) {
            val episodeCopies = copyNumbers(episode.prints)
            episode.prints.forEach { print ->
                PrintCard(
                    print = print,
                    onPlayPrint = onPlayPrint,
                    onOpenExternal = onOpenExternal,
                    onKeep = onKeep,
                    copyIndex = episodeCopies[print.releaseId]?.first ?: 1,
                    copyTotal = episodeCopies[print.releaseId]?.second ?: 1,
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
                preferredAudio = rungs.preferredAudio,
            )
        }
    }
}

/**
 * The spoken name for a print card's best-option line. The painted text is
 * the tier plus the playability ("Standard · Plays here"), and two prints at
 * one quality share it — so the spoken line carries the print's own facts
 * (its codec/size detail line) and its copy number, and each card speaks
 * differently while the painted text stays the short label. Robo run 6.
 * Pure, so PrintCardSpokenLabelTest pins it.
 */
internal fun printSpokenLabel(print: RankedPrint, copyIndex: Int, copyTotal: Int): String =
    buildString {
        append(print.bestOptionLabel.orEmpty())
        if (print.detailLine.isNotBlank()) append(" · ").append(print.detailLine)
        if (copyTotal > 1) append(", copy $copyIndex of $copyTotal")
    }

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun PrintCard(
    print: RankedPrint,
    onPlayPrint: (RankedPrint) -> Unit,
    onOpenExternal: (RankedPrint) -> Unit,
    onKeep: (RankedPrint) -> Unit,
    /** 1-based position among this list's prints at the same quality. */
    copyIndex: Int = 1,
    /** How many prints in this list share the quality. 1 of 1 needs no word. */
    copyTotal: Int = 1,
) {
    // Robo run 2: two prints at one quality announced identically — "Play
    // 720p", "Download video", "Open in external player", "Picture quality
    // 720p" — once per print. The copy number makes each print's actions
    // distinct, and the badge facts move into the Play button's spoken label,
    // so the badges stay paint-only instead of repeating on every card. The
    // visible Play text is unchanged (CL-4); only what is spoken grows.
    val copySuffix = if (copyTotal > 1) ", copy $copyIndex" else ""
    val playText = "${print.playLabel()} ${print.qualityLabel}"
    val spokenPlay = playText + copySuffix + print.spokenBadgeFacts()
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(MaterialTheme.colorScheme.surface)
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            // Paint-only (the quality is spoken on the Play button below): a
            // clearing modifier passed INTO the badge would lose to Pill's own
            // semantics, so the badges sit inside a cleared wrapper instead.
            Row(
                modifier = Modifier.clearAndSetSemantics { },
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                PrintQualityBadge(print = print)
                if (print.isCam) CamBadge()
            }
            Spacer(Modifier.weight(1f))
            print.bestOptionLabel?.let {
                // Robo run 6: two prints at one quality announced the same
                // "Standard · Plays here" line — the label is the tier plus
                // the playability, and neither names the print. The spoken
                // line carries the print's own facts (codec/size) and its
                // copy number, so each card speaks differently; the painted
                // text stays the short label. The run-3 pattern (the rung's
                // subtext carries its quality in its spoken name).
                Text(
                    text = it,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.semantics {
                        contentDescription = printSpokenLabel(print, copyIndex, copyTotal)
                    },
                )
            }
        }

        if (print.detailLine.isNotBlank()) {
            Text(print.detailLine, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }

        // The tier's own facts, as badges rather than one run-on sentence: a 4K HDR
        // WEB-DL print and its audio/subtitle story read in a glance here.
        // Paint-only: the same facts are spoken once, on the Play button below.
        FlowRow(
            modifier = Modifier.clearAndSetSemantics { },
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
                "This is a cam/bootleg recording — low quality.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
        }

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            Button(
                onClick = { onPlayPrint(print) },
                enabled = print.canStart,
                modifier = Modifier
                    .weight(1f)
                    .semantics(mergeDescendants = true) { contentDescription = spokenPlay },
            ) {
                Icon(Icons.Default.PlayArrow, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
                // CL-4: every print's Play button said bare "Play", so three
                // prints announced identically. The verb stays (a provider page
                // still says where the tap goes); the quality makes each one
                // distinct. The PrimaryActions hero button above keeps bare
                // "Play" — it is the single hero action.
                Text(playText, modifier = Modifier.clearAndSetSemantics { })
            }
            OutlinedButton(onClick = { onKeep(print) }) {
                Icon(Icons.Default.Download, contentDescription = "Download ${print.qualityLabel} video$copySuffix")
            }
            if (print.playableHere) {
                IconButton(onClick = { onOpenExternal(print) }, modifier = Modifier.size(48.dp)) {
                    Icon(Icons.Default.OpenInNew, contentDescription = "Open ${print.qualityLabel} in external player$copySuffix",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }

        // The disabled Play above is silent about why: a print the server
        // only offers for download says so in words, under its own buttons.
        if (!print.canStart) {
            Text(
                text = "Download only — no playable copy for this print.",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/**
 * Copy numbers within one quality, keyed by releaseId: the first 1080p print
 * is copy 1 of 2, the second copy 2 of 2, and a print alone at its quality is
 * copy 1 of 1 (no suffix — nothing to distinguish it from).
 */
private fun copyNumbers(prints: List<RankedPrint>): Map<Int, Pair<Int, Int>> {
    val totals = prints.groupingBy { it.qualityLabel }.eachCount()
    val seen = mutableMapOf<String, Int>()
    return prints.associate { print ->
        val index = (seen[print.qualityLabel] ?: 0) + 1
        seen[print.qualityLabel] = index
        print.releaseId to (index to (totals[print.qualityLabel] ?: 1))
    }
}

/**
 * The print's badge facts as one spoken tail — the same words the badges paint
 * ("High dynamic range DV", "Source WEB-DL", "Audio Hindi + English audio",
 * "Subtitles English"), or "" when it carries none. The quality itself is not
 * repeated here: the Play label already says it.
 */
private fun RankedPrint.spokenBadgeFacts(): String {
    val facts = listOfNotNull(
        hdrBadgeText(hdr)?.let { "High dynamic range $it" },
        sourceBadgeText(sourceTag)?.let { "Source $it" },
        audioBadgeText(dualAudio, languages)?.let { "Audio $it" },
        subtitleBadgeText(subtitlesAvailable, subtitlesExternal, subtitlesHardcoded, subtitleLangs),
    )
    return if (facts.isEmpty()) "" else facts.joinToString(prefix = ", ", separator = ", ")
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
