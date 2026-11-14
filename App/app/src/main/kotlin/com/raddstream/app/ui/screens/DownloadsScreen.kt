package com.raddstream.app.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.raddstream.app.R
import com.raddstream.app.data.downloads.DeviceDownload
import com.raddstream.app.data.downloads.DeviceDownloadState
import com.raddstream.app.data.downloads.DownloadSpeed
import com.raddstream.app.ui.components.EmptyState
import com.raddstream.app.ui.components.Pill
import com.raddstream.app.viewmodel.DownloadRow
import com.raddstream.app.viewmodel.DownloadsViewModel
import com.raddstream.app.viewmodel.KeepState
import com.raddstream.app.viewmodel.KeepRoute
import com.raddstream.app.viewmodel.KeptItem
import com.raddstream.app.viewmodel.StorageInfo
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DownloadsScreen(
    onBackClick: () -> Unit,
    onPlay: (KeptItem) -> Unit = {},
    onPlayLocal: (uri: String, title: String) -> Unit = { _, _ -> },
    onOpenLocalFiles: () -> Unit = {},
    viewModel: DownloadsViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsState()
    // A keep tap has to ask the engine a question before it can navigate, and navigation is a
    // side effect — so it runs on the composition's own scope and dies with the screen.
    val clicks = rememberCoroutineScope()

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = { Text("Downloads") },
                navigationIcon = {
                    IconButton(onClick = onBackClick) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                },
                actions = {
                    IconButton(onClick = viewModel::refresh) {
                        Icon(Icons.Default.Refresh, contentDescription = "Refresh storage")
                    }
                },
            )
        },
    ) { contentPadding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(contentPadding),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            item { StorageCard(state.storage) }
            item { LocalFilesEntry(onOpenLocalFiles) }
            state.statusMessage?.let { msg ->
                item {
                    Text(
                        text = msg,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.primary,
                    )
                }
            }

            if (state.hasAnything) {
                item {
                    NoticeCard(
                        "Files in Movies/RaddStream play anywhere, even after the app closes. " +
                            "Downloads play here.",
                    )
                }
                items(
                    state.allDownloads,
                    key = { row ->
                        when (row) {
                            is DownloadRow.Device -> "device-${row.download.id}"
                            is DownloadRow.Keep -> "keep-${row.item.id}"
                        }
                    },
                ) { row ->
                    when (row) {
                        is DownloadRow.Device -> DeviceDownloadRow(
                            item = row.download,
                            onPlay = { row.download.localUri?.let { onPlayLocal(it, row.download.title) } },
                            onPause = { viewModel.pauseDownload(row.download) },
                            onResume = { viewModel.resumeDownload(row.download) },
                            onRemove = { viewModel.removeDownload(row.download) },
                        )
                        is DownloadRow.Keep -> KeptItemRow(
                            item = row.item,
                            // Local bytes first, the redirector handle only if the engine could not
                            // name a complete file: a keep that is really on the device needs no
                            // network, no resolver round-trip, and no live upstream to play.
                            onPlay = {
                                clicks.launch {
                                    when (val route = viewModel.playRoute(row.item)) {
                                        is KeepRoute.Local -> onPlayLocal(route.uri, row.item.title)
                                        is KeepRoute.Stream -> onPlay(row.item)
                                        KeepRoute.NothingPlayable -> viewModel.reportUnplayable()
                                    }
                                }
                            },
                            onCancel = { viewModel.cancel(row.item) },
                            onRetry = { viewModel.retry(row.item) },
                        )
                    }
                }
            }

            if (!state.hasAnything && !state.isLoading) {
                item {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(240.dp),
                        verticalArrangement = Arrangement.Center,
                    ) {
                        EmptyState(
                            title = "Nothing downloaded yet",
                            message = "Use the Download button on a movie or episode. " +
                                "Files go to Movies/RaddStream and play anywhere; downloads play here.",
                            icon = {
                                Icon(
                                    Icons.Default.Download,
                                    contentDescription = null,
                                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                    modifier = Modifier.size(40.dp),
                                )
                            },
                            modifier = Modifier.fillMaxSize(),
                            action = {
                                // A downloads tab nobody has used yet is not a dead end: the way
                                // to fill it is one tap away, on the title they came from.
                                OutlinedButton(onClick = onBackClick) { Text("Find something to download") }
                            },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun LocalFilesEntry(onOpenLocalFiles: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(MaterialTheme.colorScheme.surface)
            .clickable { onOpenLocalFiles() }
            .padding(16.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            Icons.Default.Folder,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(28.dp),
        )
        Column(
            modifier = Modifier.weight(1f).padding(start = 12.dp),
        ) {
            Text(
                "Videos on this phone",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                "Browse Movies and Downloads",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Icon(
            Icons.Default.ChevronRight,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun NoticeCard(text: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .padding(14.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Icon(
            Icons.Default.Info,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(20.dp),
        )
        Text(
            text = text,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun StorageCard(storage: StorageInfo?) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(MaterialTheme.colorScheme.surface)
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text("Device storage", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurface)
        if (storage == null) {
            Text("Storage information unavailable.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            return
        }
        LinearProgressIndicator(
            progress = { storage.usedFraction },
            modifier = Modifier.fillMaxWidth(),
            color = if (storage.lowSpace) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary,
        )
        Text(
            "${formatGib(storage.freeBytes)} free of ${formatGib(storage.totalBytes)}",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        if (storage.lowSpace) {
            Text(
                "Low space — a download needs room for the whole file.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
        }
    }
}

// Robo run 9: the print label is painted only when it says something the
// title does not — and it speaks with the title, so two files sharing one
// quality label never speak identically. Internal for the run-9 label test.
@Composable
internal fun DeviceDownloadRow(
    item: DeviceDownload,
    onPlay: () -> Unit,
    onPause: () -> Unit,
    onResume: () -> Unit,
    onRemove: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(MaterialTheme.colorScheme.surface)
            // A finished download is a file on this device: the whole row opens it
            // in the local player, with no server and no redirector involved. The
            // inner buttons still consume their own taps.
            .clickable(
                enabled = item.playing,
                onClickLabel = if (item.playing) "Play ${item.title} offline" else null,
                onClick = onPlay,
            )
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                text = item.title,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onSurface,
                maxLines = 2,
                modifier = Modifier.weight(1f),
            )
            DeviceStatusPill(item.state)
        }
        item.shownPrintLabel()?.let { label ->
            Text(
                label,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.semantics { contentDescription = item.printLabelDescription() },
            )
        }
        Text(
            deviceStatusLine(item),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurface,
        )
        if (item.state == DeviceDownloadState.DOWNLOADING ||
            item.state == DeviceDownloadState.QUEUED
        ) {
            // Restyle 2026-11-13: rounded ends + a visible track — the bar
            // reads as a progress bar, not a hairline.
            LinearProgressIndicator(
                progress = { item.progress },
                modifier = Modifier.fillMaxWidth(),
                color = MaterialTheme.colorScheme.primary,
                trackColor = MaterialTheme.colorScheme.surfaceVariant,
                strokeCap = StrokeCap.Round,
            )
            val total = if (item.bytesTotal > 0) formatMiB(item.bytesTotal) else "unknown size"
            // Audit #12: % + MB + speed + ETA, from the same rolling rate the
            // service reports — "calculating" until the second tick, never a
            // guessed number.
            val speedEta = if (item.bytesPerSec > 0) {
                " · ${DownloadSpeed.formatSpeed(item.bytesPerSec)}" +
                    (DownloadSpeed.formatEta(item.etaSeconds)?.let { " · $it" } ?: "")
            } else {
                " · calculating…"
            }
            Text(
                "${formatMiB(item.bytesDownloaded)} / $total$speedEta",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (item.playing) {
                Button(
                    onClick = onPlay,
                    modifier = Modifier.weight(1f).semantics { contentDescription = "Play ${item.title}" },
                ) {
                    Icon(Icons.Default.PlayArrow, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.size(6.dp))
                    Text("Play")
                }
            }
            if (item.canPause) {
                OutlinedButton(
                    onClick = onPause,
                    modifier = Modifier.semantics { contentDescription = "Pause ${item.title}" },
                ) {
                    Icon(Icons.Default.Pause, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.size(6.dp))
                    Text("Pause")
                }
            }
            if (item.canResume) {
                OutlinedButton(
                    onClick = onResume,
                    modifier = Modifier.semantics { contentDescription = "Resume ${item.title}" },
                ) { Text("Resume") }
            }
            OutlinedButton(
                onClick = onRemove,
                modifier = Modifier.semantics {
                    contentDescription = "${if (item.playing) "Delete" else "Cancel"} ${item.title}"
                },
            ) {
                Text(if (item.playing) "Delete" else "Cancel")
            }
        }
    }
}

/** One honest sentence per DownloadManager state. */
private fun deviceStatusLine(item: DeviceDownload): String {
    val percent = item.percent?.let { " $it%" } ?: ""
    return when (item.state) {
        DeviceDownloadState.QUEUED -> "Queued$percent"
        DeviceDownloadState.DOWNLOADING -> "Downloading$percent"
        DeviceDownloadState.PAUSED -> "Paused — resume when you are ready"
        DeviceDownloadState.READY -> "Saved on device — plays here or in any video player"
        DeviceDownloadState.FAILED -> "Download failed — resume, or cancel and try again"
    }
}

@Composable
private fun DeviceStatusPill(state: DeviceDownloadState) {
    // SC.8: a finished download wears "Saved on device", not the bare "Saved".
    val text = when (state) {
        DeviceDownloadState.QUEUED -> "Queued"
        DeviceDownloadState.DOWNLOADING -> "Downloading"
        DeviceDownloadState.PAUSED -> "Paused"
        DeviceDownloadState.READY -> stringResource(R.string.downloads_saved_on_device)
        DeviceDownloadState.FAILED -> "Failed"
    }
    val error = state == DeviceDownloadState.FAILED
    Pill(
        text = text,
        backgroundColor = if (error) MaterialTheme.colorScheme.errorContainer else MaterialTheme.colorScheme.surfaceVariant,
        contentColor = if (error) MaterialTheme.colorScheme.onErrorContainer else MaterialTheme.colorScheme.onSurfaceVariant,
        // F31 (Batch B): paint-only — the status line under the title already
        // speaks this state ("Downloading 42%", "Saved on device"), so a
        // speaking pill would say it twice, once per row, with no title.
        modifier = Modifier.clearAndSetSemantics {},
    )
}

// Robo run 9: the print label is painted only when it says something the
// title does not — and it speaks with the title, so two keeps sharing one
// rank label ("Rank #1") never speak identically. Internal for the run-9
// label test.
@Composable
internal fun KeptItemRow(
    item: KeptItem,
    onPlay: () -> Unit,
    onCancel: () -> Unit,
    onRetry: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(MaterialTheme.colorScheme.surface)
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(item.title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurface, maxLines = 2)
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            // Robo run 9: a "Rank #1" print label identical to the title (or
            // shared with another card) speaks identically — the row paints
            // the label only when it says something the title does not, and
            // the spoken line names the title so two cards never share it.
            item.shownPrintLabel()?.let { label ->
                Text(
                    label,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.semantics { contentDescription = item.printLabelDescription() },
                )
            }
            Spacer(Modifier.weight(1f))
            StatusPill(item.state)
        }
        Text(statusLine(item), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurface)
        if (item.state == KeepState.DOWNLOADING || item.state == KeepState.QUEUED || item.state == KeepState.NO_SPACE) {
            // Restyle 2026-11-13: rounded ends + a visible track, same as
            // the active-download bar above — one progress language.
            LinearProgressIndicator(
                progress = { item.progress },
                modifier = Modifier.fillMaxWidth(),
                color = MaterialTheme.colorScheme.primary,
                trackColor = MaterialTheme.colorScheme.surfaceVariant,
                strokeCap = StrokeCap.Round,
            )
            val total = if (item.bytesTotal > 0) formatMiB(item.bytesTotal) else "unknown size"
            Text("${formatMiB(item.bytesDownloaded)} / $total", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (item.playable) {
                Button(
                    onClick = onPlay,
                    modifier = Modifier.weight(1f).semantics { contentDescription = "Play ${item.title}" },
                ) { Text("Play") }
            }
            when (item.state) {
                KeepState.FAILED, KeepState.NO_SPACE -> OutlinedButton(
                    onClick = onRetry,
                    modifier = Modifier.semantics { contentDescription = "Retry ${item.title}" },
                ) { Text("Retry") }
                KeepState.DOWNLOADING, KeepState.QUEUED, KeepState.PAUSED,
                KeepState.READY, KeepState.EXPIRING ->
                    OutlinedButton(
                        onClick = onCancel,
                        modifier = Modifier.semantics {
                            contentDescription = "${keepActionLabel(item.state) ?: "Cancel"} ${item.title}"
                        },
                    ) { Text(keepActionLabel(item.state) ?: "Cancel") }
                else -> {}
            }
        }
    }
}

/**
 * The destructive/cancellation action label for a kept item:
 * "Cancel" while in-flight or waiting, "Delete" once completed on device.
 */
internal fun keepActionLabel(state: KeepState): String? = when (state) {
    KeepState.READY, KeepState.EXPIRING -> "Delete"
    KeepState.DOWNLOADING, KeepState.QUEUED, KeepState.PAUSED -> "Cancel"
    KeepState.FAILED, KeepState.NO_SPACE -> "Retry"
    else -> null
}

/** One honest sentence per state. No provenance, no invented progress. */
private fun statusLine(item: KeptItem): String {
    val percent = item.percent?.let { " $it%" } ?: ""
    return when (item.state) {
        KeepState.QUEUED -> "Queued for download$percent"
        KeepState.DOWNLOADING -> "Downloading$percent"
        KeepState.PAUSED -> "Paused"
        KeepState.NO_SPACE -> "Not enough space to finish — free room and retry"
        KeepState.READY -> "Saved on device — available offline"
        KeepState.EXPIRING -> "Kept — expires soon and auto-deletes"
        KeepState.EXPIRED -> "Expired — removed automatically"
        KeepState.FAILED -> "Download failed — retry to resume"
    }
}

@Composable
private fun StatusPill(state: KeepState) {
    // SC.8: same badge as the device downloads — "Saved on device".
    val text = when (state) {
        KeepState.QUEUED -> "Queued"
        KeepState.DOWNLOADING -> "Downloading"
        KeepState.PAUSED -> "Paused"
        KeepState.READY -> stringResource(R.string.downloads_saved_on_device)
        KeepState.EXPIRING -> "Expiring soon"
        KeepState.EXPIRED -> "Expired"
        KeepState.NO_SPACE -> "No space"
        KeepState.FAILED -> "Failed"
    }
    val bg = if (state == KeepState.FAILED || state == KeepState.EXPIRING || state == KeepState.EXPIRED || state == KeepState.NO_SPACE) {
        MaterialTheme.colorScheme.errorContainer
    } else {
        MaterialTheme.colorScheme.surfaceVariant
    }
    val fg = if (state == KeepState.FAILED || state == KeepState.EXPIRING || state == KeepState.EXPIRED || state == KeepState.NO_SPACE) {
        MaterialTheme.colorScheme.onErrorContainer
    } else {
        MaterialTheme.colorScheme.onSurfaceVariant
    }
    Pill(
        text = text,
        backgroundColor = bg,
        contentColor = fg,
        // F31 (Batch B): paint-only — the status line under the title already
        // speaks this state, so a speaking pill would say it twice, once
        // per row, with no title.
        modifier = Modifier.clearAndSetSemantics {},
    )
}

private fun formatGib(bytes: Long): String = "%.1f GB".format(bytes / 1_000_000_000.0)
private fun formatMiB(bytes: Long): String = when {
    bytes >= 1_000_000_000 -> "%.1f GB".format(bytes / 1_000_000_000.0)
    bytes >= 1_000_000 -> "%.0f MB".format(bytes / 1_000_000.0)
    else -> "%.0f KB".format(bytes / 1_000.0)
}
