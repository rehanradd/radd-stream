package com.raddstream.app.viewmodel

import android.content.Context
import android.os.StatFs
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.data.cache.CacheCoordinator
import com.raddstream.app.data.cache.CacheOrigin
import com.raddstream.app.data.cache.CacheTaskEntity
import com.raddstream.app.data.cache.CacheTaskState
import com.raddstream.app.data.cache.KeepTtlHolder
import com.raddstream.app.data.cache.OfflineCacheEngine
import com.raddstream.app.data.downloads.DeviceDownload
import com.raddstream.app.data.downloads.DeviceDownloadsRepository
import com.raddstream.app.data.local.WatchHistoryDao
import com.raddstream.app.data.local.WatchHistoryEntity
import com.raddstream.app.repository.CacheRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

enum class KeepState { QUEUED, DOWNLOADING, PAUSED, READY, EXPIRING, EXPIRED, NO_SPACE, FAILED }

/**
 * One offline keep as the Downloads screen should render it, projected from the cache engine's
 * task rows. Bytes progress is real; the expiry is the engine's retention window applied, never a
 * locally invented timer. These files are playable **only inside this app**.
 */
data class KeptItem(
    val id: String,
    val title: String,
    val printLabel: String,
    val bytesDownloaded: Long,
    val bytesTotal: Long,
    val state: KeepState,
    val expiresAtMillis: Long?,
    /**
     * The opaque redirector handle this keep plays through — the same handle a stream route
     * takes, and the only address the player may be handed. Null when the engine never got one
     * (a task created before the keep was resolved, or one the server refused to name), which
     * is why [playable] checks it rather than trusting the state alone.
     */
    val streamHandle: String? = null,
    /**
     * The engine's opaque task key, so a tap can ask for this keep's own bytes without the screen
     * ever holding a URL or a host. No provenance and no locator — an identity inside this app.
     */
    val sourceKey: String = "",
) {
    val progress: Float
        get() = if (bytesTotal > 0) (bytesDownloaded.toFloat() / bytesTotal.toFloat()).coerceIn(0f, 1f) else 0f

    /** Whole-file percent for the downloading line; null when the size was never learned. */
    val percent: Int?
        get() = if (bytesTotal > 0) (progress * 100).toInt().coerceIn(0, 100) else null

    /**
     * A row may be tapped to play only while bytes are on the device AND the engine has a
     * handle to play them through. An expiring keep is included deliberately: it is still
     * here, and the screen already says out loud how long it will be.
     */
    val playable: Boolean
        get() = !streamHandle.isNullOrBlank() &&
            (state == KeepState.READY || state == KeepState.EXPIRING)

    fun remainingMillis(now: Long): Long? = expiresAtMillis?.let { (it - now).coerceAtLeast(0) }
}

/**
 * What a tapped keep should do: play the bytes already on this device, play through the
 * redirector handle, or explain that neither is possible yet.
 */
sealed class KeepRoute {
    data class Local(val uri: String) : KeepRoute()
    data class Stream(val handle: String) : KeepRoute()
    object NothingPlayable : KeepRoute()
}

object KeepPlayback {
    /**
     * Local bytes win whenever the engine could serve them: a complete keep needs no network, no
     * resolver round-trip, and no live upstream, and the loopback server answers `Range` so seeking
     * stays cheap. [streamHandle] is the fallback for a keep whose file the engine cannot name —
     * a task written before the resolver ever saw it, or one whose bytes were swept since.
     */
    fun route(localUri: String?, streamHandle: String?, playable: Boolean): KeepRoute = when {
        !localUri.isNullOrBlank() -> KeepRoute.Local(localUri)
        playable && !streamHandle.isNullOrBlank() -> KeepRoute.Stream(streamHandle)
        else -> KeepRoute.NothingPlayable
    }
}

data class StorageInfo(val freeBytes: Long, val totalBytes: Long) {
    val usedBytes: Long get() = (totalBytes - freeBytes).coerceAtLeast(0)
    val usedFraction: Float get() = if (totalBytes > 0) usedBytes.toFloat() / totalBytes.toFloat() else 0f
    val lowSpace: Boolean get() = freeBytes in 1 until LOW_SPACE_BYTES

    companion object {
        const val LOW_SPACE_BYTES = 500_000_000L // warn under ~500 MB free
    }
}

data class DownloadsUiState(
    /** Public files in `Movies/RaddStream/`, owned by Android's DownloadManager. */
    val deviceDownloads: List<DeviceDownload> = emptyList(),
    /** In-app keeps from the cache engine — private storage, expiry-bound. */
    val items: List<KeptItem> = emptyList(),
    val storage: StorageInfo? = null,
    val isLoading: Boolean = true,
    val engineAvailable: Boolean = false,
    val statusMessage: String? = null,
) {
    val hasAnything: Boolean get() = deviceDownloads.isNotEmpty() || items.isNotEmpty()

    /**
     * ONE list, one word: every download on this screen, whatever system
     * owns the copy. Files first — they are the foreground downloads the
     * viewer is watching — then the in-app keeps. Each row still carries
     * its own actions and its own one state word; the split the viewer
     * used to see ("Saved to this device" vs "In-app keeps") was two
     * systems' names, not two things the viewer asked for.
     */
    val allDownloads: List<DownloadRow>
        get() = deviceDownloads.map { DownloadRow.Device(it) } + items.map { DownloadRow.Keep(it) }
}

/** One row of the single Downloads list — the system that owns the copy is its detail, not its kind. */
sealed interface DownloadRow {
    data class Device(val download: DeviceDownload) : DownloadRow
    data class Keep(val item: KeptItem) : DownloadRow
}

@HiltViewModel
class DownloadsViewModel @Inject constructor(
    @ApplicationContext private val context: Context,
    private val cacheRepository: CacheRepository,
    private val keepTtl: KeepTtlHolder,
    private val deviceDownloads: DeviceDownloadsRepository,
    private val cacheEngine: OfflineCacheEngine,
    private val watchHistoryDao: WatchHistoryDao,
    private val settingsRepository: ServerSettingsRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(DownloadsUiState())
    val uiState = _uiState.asStateFlow()

    private var autoDeleteWatched: Boolean = true

    init {
        viewModelScope.launch {
            settingsRepository.autoDeleteWatched.collect { autoDeleteWatched = it }
        }
        viewModelScope.launch {
            _uiState.update { it.copy(storage = readStorage(), engineAvailable = true) }
        }
        viewModelScope.launch {
            cacheRepository.tasksFlow().collect { rows ->
                val items = rows.map(::toKeptItem)
                _uiState.update { it.copy(items = items, isLoading = false) }
                sweepWatched(items)
            }
        }
        viewModelScope.launch {
            deviceDownloads.downloads.collect { rows ->
                _uiState.update { it.copy(deviceDownloads = rows, isLoading = false) }
            }
        }
    }

    fun refresh() {
        viewModelScope.launch { _uiState.update { it.copy(storage = readStorage()) } }
    }

    fun clearStatus() = _uiState.update { it.copy(statusMessage = null) }

    /**
     * Real, cheap, and always meaningful: how much space is left on the app's primary storage.
     * Used for the storage warning + the "playable only in this app" explanation.
     */
    private fun readStorage(): StorageInfo? = try {
        val stat = StatFs(context.filesDir.absolutePath)
        StorageInfo(freeBytes = stat.availableBytes, totalBytes = stat.totalBytes)
    } catch (_: Exception) {
        null
    }

    // --- engine actions ---

    fun cancel(item: KeptItem) {
        val taskId = item.id.toLongOrNull() ?: return
        viewModelScope.launch {
            runCatching { cacheRepository.cancel(taskId) }
                .onFailure { _uiState.update { s -> s.copy(statusMessage = "Could not cancel that download.") } }
        }
    }

    /**
     * Delete finished movies on their own, to free the space. Only a fully
     * downloaded keep (READY/EXPIRING) whose title is in the watched set is
     * touched — a download still in flight is never deleted, and a series
     * keep never matches, because the watched set holds movie titles only.
     * Series episodes are deleted at the player instead, when the episode
     * ends (`PlayerViewModel.maybeAutoDeleteWatchedEpisode`): there the
     * identity is the episode's own cache key, so one watched episode can
     * never delete the rest of the season. The notice names what went, so
     * the deletion is never silent.
     */
    private fun sweepWatched(items: List<KeptItem>) {
        if (!autoDeleteWatched) return
        viewModelScope.launch {
            val watched = runCatching { watchedTitles(watchHistoryDao.findMovieRows()) }.getOrNull()
                ?: return@launch
            if (watched.isEmpty()) return@launch
            val finished = items.filter {
                (it.state == KeepState.READY || it.state == KeepState.EXPIRING) && it.title in watched
            }
            if (finished.isEmpty()) return@launch
            finished.forEach { item ->
                item.id.toLongOrNull()?.let { runCatching { cacheRepository.cancel(it) } }
            }
            _uiState.update { s ->
                s.copy(
                    statusMessage = if (finished.size == 1) {
                        "Deleted ${finished.first().title} — you finished watching it."
                    } else {
                        "Deleted ${finished.size} finished downloads."
                    },
                )
            }
        }
    }

    fun retry(item: KeptItem) {
        val taskId = item.id.toLongOrNull() ?: return
        viewModelScope.launch {
            runCatching { cacheRepository.resume(taskId) }
                .onFailure { _uiState.update { s -> s.copy(statusMessage = "Could not resume that download.") } }
        }
    }

    // --- public download service actions ---

    fun pauseDownload(item: DeviceDownload) {
        deviceDownloads.requestPause(item.id)
    }

    fun resumeDownload(item: DeviceDownload) {
        deviceDownloads.requestResume(item.id)
    }

    fun removeDownload(item: DeviceDownload) {
        deviceDownloads.requestRemove(item.id)
    }

    /**
     * Project one engine task onto a list row. Every field is honest: the state comes straight from
     * the state machine, a pause is only labelled "no space" when the engine parked it for that
     * reason, and a finished ephemeral keep gets the retention window's own expiry stamp.
     */
    private fun toKeptItem(task: CacheTaskEntity): KeptItem {
        val now = System.currentTimeMillis()
        val expiresAt = expiryFor(task)
        val state = when (task.stateEnum) {
            CacheTaskState.QUEUED -> KeepState.QUEUED
            CacheTaskState.LOADING -> KeepState.DOWNLOADING
            CacheTaskState.PAUSED ->
                if (task.lastError == CacheCoordinator.ERR_NO_SPACE) KeepState.NO_SPACE else KeepState.PAUSED
            CacheTaskState.COMPLETED ->
                if (expiresAt != null && expiresAt - now <= EXPIRING_SOON_MILLIS) KeepState.EXPIRING else KeepState.READY
            CacheTaskState.EXPIRED -> KeepState.EXPIRED
            CacheTaskState.FAILED -> KeepState.FAILED
            CacheTaskState.DELETED -> KeepState.EXPIRED // filtered by the query; defensive mapping
        }
        return KeptItem(
            id = task.id.toString(),
            // A title is a title: the print label is a quality, not a name,
            // and "Saved file" is a status, not a name either. Old rows whose
            // title was never stored fall back to the print label, then to
            // an honest untitled.
            title = task.title.ifBlank { task.printLabel.ifBlank { "Untitled download" } },
            printLabel = task.printLabel,
            bytesDownloaded = task.downloadedBytes,
            bytesTotal = task.totalSizeBytes,
            state = state,
            expiresAtMillis = expiresAt,
            streamHandle = task.resourceId?.takeIf { it.isNotBlank() },
            sourceKey = task.sourceKey,
        )
    }

    /**
     * Resolve a tap. The engine answers from the file manifest, so a keep the sweep already
     * truncated — or one that never finished landing — has no local address and falls back to the
     * handle rather than opening a player on bytes that are not there.
     */
    suspend fun playRoute(item: KeptItem): KeepRoute {
        val complete = item.state == KeepState.READY || item.state == KeepState.EXPIRING
        val local = if (complete) {
            runCatching { cacheEngine.playableUriForSourceKey(item.sourceKey) }.getOrNull()
        } else {
            null
        }
        return KeepPlayback.route(local, item.streamHandle, item.playable)
    }

    /** The row said Play and nothing behind it is playable any more — say so instead of idling. */
    fun reportUnplayable() {
        _uiState.update { it.copy(statusMessage = "That keep is no longer stored on this device.") }
    }

    /** The retention window's own expiry for a finished ephemeral keep; null for a permanent one. */
    private fun expiryFor(task: CacheTaskEntity): Long? {
        if (task.originEnum == CacheOrigin.USER_KEEP) return null
        if (task.stateEnum != CacheTaskState.COMPLETED && task.stateEnum != CacheTaskState.EXPIRED) return null
        // Read live from [KeepTtlHolder] — the same source the sweep deletes against — so this row
        // cannot promise a minute the engine has no intention of honouring. A settings change lands
        // on the next task emission; nothing here owns a timer of its own.
        return task.createdAtWallClock + keepTtl.ttlHours().millis
    }

    companion object {
        const val EXPIRING_SOON_MILLIS = 60 * 60_000L // last hour before auto-delete reads "Expiring"
    }
}

/**
 * Titles of finished movies, from watch-history rows. A row counts only
 * when the viewer reached the end — the same end-guard the Continue
 * Watching rail uses — so a half-watched film stays. Series rows never
 * reach this helper (the DAO returns movie rows only), so one watched
 * episode can never delete a season keep.
 */
fun watchedTitles(rows: List<WatchHistoryEntity>): Set<String> =
    rows.filter { it.durationMs > 0 && it.positionMs >= it.durationMs - WatchHistoryEntity.END_GUARD_MS }
        .map { it.title }
        .filter { it.isNotBlank() }
        .toSet()
