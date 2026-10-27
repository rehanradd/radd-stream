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
import androidx.compose.material.icons.filled.Download
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.raddstream.app.brand.Brand
import com.raddstream.app.data.downloads.DeviceDownload
import com.raddstream.app.data.downloads.DeviceDownloadState
import com.raddstream.app.ui.components.EmptyState
import com.raddstream.app.ui.components.Pill
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
            state.statusMessage?.let { msg ->
                item {
                    Text(
                        text = msg,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.primary,
                    )
                }
            }

            if (state.deviceDownloads.isNotEmpty()) {
                item { SectionTitle("Saved to this device") }
                item {
                    NoticeCard(
                        "Files live in Movies/RaddStream and keep playing after the app closes. " +
                            "The notification shows live progress; pause or resume here.",
                    )
                }
                items(state.deviceDownloads, key = { "device-${it.id}" }) { item ->
                    DeviceDownloadRow(
                        item = item,
                        onPlay = { item.localUri?.let { onPlayLocal(it, item.title) } },
                        onPause = { viewModel.pauseDownload(item) },
                        onResume = { viewModel.resumeDownload(item) },
                        onRemove = { viewModel.removeDownload(item) },
                    )
                }
            }

            if (state.items.isNotEmpty()) {
                item { SectionTitle("In-app keeps") }
                item { PlayableOnlyNotice() }
                items(state.items, key = { it.id }) { item ->
                    KeptItemRow(
                        item = item,
                        // Local bytes first, the redirector handle only if the engine could not
                        // name a complete file: a keep that is really on the device needs no
                        // network, no resolver round-trip, and no live upstream to play.
                        onPlay = {
                            clicks.launch {
                                when (val route = viewModel.playRoute(item)) {
                                    is KeepRoute.Local -> onPlayLocal(route.uri, item.title)
                                    is KeepRoute.Stream -> onPlay(item)
                                    KeepRoute.NothingPlayable -> viewModel.reportUnplayable()
                                }
                            }
                        },
                        onCancel = { viewModel.cancel(item) },
                        onRetry = { viewModel.retry(item) },
                    )
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
                            message = "Use the download button on a print or episode. " +
                                "The file is saved to Movies/RaddStream with live progress and plays here when finished.",
                            icon = {
                                Icon(
                                    Icons.Default.Download,
                                    contentDescription = null,
                                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                    modifier = Modifier.size(40.dp),
                                )
                            },
                            modifier = Modifier.fillMaxSize(),
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun SectionTitle(text: String) {
    Text(
        text = text,
        style = MaterialTheme.typography.titleMedium,
        fontWeight = FontWeight.SemiBold,
        color = MaterialTheme.colorScheme.onBackground,
    )
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

@Composable
private fun PlayableOnlyNotice() {
    NoticeCard(Brand.copy("offline_notice"))
}

@Composable
private fun DeviceDownloadRow(
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
        if (item.printLabel.isNotBlank()) {
            Text(
                item.printLabel,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
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
            LinearProgressIndicator(progress = { item.progress }, modifier = Modifier.fillMaxWidth())
            val total = if (item.bytesTotal > 0) formatMiB(item.bytesTotal) else "unknown size"
            Text(
                "${formatMiB(item.bytesDownloaded)} / $total",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (item.playing) {
                Button(onClick = onPlay, modifier = Modifier.weight(1f)) {
                    Icon(Icons.Default.PlayArrow, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.size(6.dp))
                    Text("Play")
                }
            }
            if (item.canPause) {
                OutlinedButton(onClick = onPause) {
                    Icon(Icons.Default.Pause, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.size(6.dp))
                    Text("Pause")
                }
            }
            if (item.canResume) {
                OutlinedButton(onClick = onResume) { Text("Resume") }
            }
            OutlinedButton(onClick = onRemove) {
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
        DeviceDownloadState.READY -> "Saved — plays here or in any video player"
        DeviceDownloadState.FAILED -> "Download failed — resume, or cancel and try again"
    }
}

@Composable
private fun DeviceStatusPill(state: DeviceDownloadState) {
    val text = when (state) {
        DeviceDownloadState.QUEUED -> "Queued"
        DeviceDownloadState.DOWNLOADING -> "Downloading"
        DeviceDownloadState.PAUSED -> "Paused"
        DeviceDownloadState.READY -> "Saved"
        DeviceDownloadState.FAILED -> "Failed"
    }
    val error = state == DeviceDownloadState.FAILED
    Pill(
        text = text,
        backgroundColor = if (error) MaterialTheme.colorScheme.errorContainer else MaterialTheme.colorScheme.surfaceVariant,
        contentColor = if (error) MaterialTheme.colorScheme.onErrorContainer else MaterialTheme.colorScheme.onSurfaceVariant,
    )
}

@Composable
private fun KeptItemRow(
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
            Text(item.printLabel, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.weight(1f))
            StatusPill(item.state)
        }
        Text(statusLine(item), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurface)
        if (item.state == KeepState.DOWNLOADING || item.state == KeepState.QUEUED || item.state == KeepState.NO_SPACE) {
            LinearProgressIndicator(progress = { item.progress }, modifier = Modifier.fillMaxWidth())
            val total = if (item.bytesTotal > 0) formatMiB(item.bytesTotal) else "unknown size"
            Text("${formatMiB(item.bytesDownloaded)} / $total", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (item.playable) {
                Button(onClick = onPlay, modifier = Modifier.weight(1f)) { Text("Play") }
            }
            when (item.state) {
                KeepState.FAILED, KeepState.NO_SPACE -> OutlinedButton(onClick = onRetry) { Text("Retry") }
                KeepState.DOWNLOADING, KeepState.QUEUED, KeepState.PAUSED, KeepState.READY, KeepState.EXPIRING ->
                    OutlinedButton(onClick = onCancel) { Text("Cancel") }
                else -> {}
            }
        }
    }
}

/** One honest sentence per state. No provenance, no invented progress. */
private fun statusLine(item: KeptItem): String {
    val percent = item.percent?.let { " $it%" } ?: ""
    return when (item.state) {
        KeepState.QUEUED -> "Queued for download$percent"
        KeepState.DOWNLOADING -> "Downloading$percent"
        KeepState.PAUSED -> "Paused"
        KeepState.NO_SPACE -> "Not enough space to finish — free room and retry"
        KeepState.READY -> "Kept — available offline"
        KeepState.EXPIRING -> "Kept — expires soon and auto-deletes"
        KeepState.EXPIRED -> "Expired — auto-deleted to respect link rot"
        KeepState.FAILED -> "Download failed — retry to resume"
    }
}

@Composable
private fun StatusPill(state: KeepState) {
    val text = when (state) {
        KeepState.QUEUED -> "Queued"
        KeepState.DOWNLOADING -> "Downloading"
        KeepState.PAUSED -> "Paused"
        KeepState.READY -> "Kept"
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
    Pill(text = text, backgroundColor = bg, contentColor = fg)
}

private fun formatGib(bytes: Long): String = "%.1f GB".format(bytes / 1_000_000_000.0)
private fun formatMiB(bytes: Long): String = when {
    bytes >= 1_000_000_000 -> "%.1f GB".format(bytes / 1_000_000_000.0)
    bytes >= 1_000_000 -> "%.0f MB".format(bytes / 1_000_000.0)
    else -> "%.0f KB".format(bytes / 1_000.0)
}
