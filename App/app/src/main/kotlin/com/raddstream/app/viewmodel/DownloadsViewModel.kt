package com.raddstream.app.viewmodel

import android.content.Context
import android.os.StatFs
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.data.cache.CacheCoordinator
import com.raddstream.app.data.cache.CacheOrigin
import com.raddstream.app.data.cache.CacheTaskEntity
import com.raddstream.app.data.cache.CacheTaskState
import com.raddstream.app.data.cache.TtlHours
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
) {
    val progress: Float
        get() = if (bytesTotal > 0) (bytesDownloaded.toFloat() / bytesTotal.toFloat()).coerceIn(0f, 1f) else 0f

    /** Whole-file percent for the downloading line; null when the size was never learned. */
    val percent: Int?
        get() = if (bytesTotal > 0) (progress * 100).toInt().coerceIn(0, 100) else null

    fun remainingMillis(now: Long): Long? = expiresAtMillis?.let { (it - now).coerceAtLeast(0) }
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
    val items: List<KeptItem> = emptyList(),
    val storage: StorageInfo? = null,
    val isLoading: Boolean = true,
    val engineAvailable: Boolean = false,
    val statusMessage: String? = null,
)

@HiltViewModel
class DownloadsViewModel @Inject constructor(
    @ApplicationContext private val context: Context,
    private val cacheRepository: CacheRepository,
    private val ttlHours: TtlHours,
) : ViewModel() {

    private val _uiState = MutableStateFlow(DownloadsUiState())
    val uiState = _uiState.asStateFlow()

    init {
        viewModelScope.launch {
            _uiState.update { it.copy(storage = readStorage(), engineAvailable = true) }
        }
        viewModelScope.launch {
            cacheRepository.tasksFlow().collect { rows ->
                _uiState.update { it.copy(items = rows.map(::toKeptItem), isLoading = false) }
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

    fun retry(item: KeptItem) {
        val taskId = item.id.toLongOrNull() ?: return
        viewModelScope.launch {
            runCatching { cacheRepository.resume(taskId) }
                .onFailure { _uiState.update { s -> s.copy(statusMessage = "Could not resume that download.") } }
        }
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
            title = task.title.ifBlank { "Saved file" },
            printLabel = task.printLabel,
            bytesDownloaded = task.downloadedBytes,
            bytesTotal = task.totalSizeBytes,
            state = state,
            expiresAtMillis = expiresAt,
        )
    }

    /** The retention window's own expiry for a finished ephemeral keep; null for a permanent one. */
    private fun expiryFor(task: CacheTaskEntity): Long? {
        if (task.originEnum == CacheOrigin.USER_KEEP) return null
        if (task.stateEnum != CacheTaskState.COMPLETED && task.stateEnum != CacheTaskState.EXPIRED) return null
        return task.createdAtWallClock + ttlHours.millis
    }

    companion object {
        const val EXPIRING_SOON_MILLIS = 60 * 60_000L // last hour before auto-delete reads "Expiring"
    }
}
