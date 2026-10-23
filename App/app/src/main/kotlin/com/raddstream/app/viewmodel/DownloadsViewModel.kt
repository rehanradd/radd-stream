package com.raddstream.app.viewmodel

import android.content.Context
import android.os.StatFs
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

enum class KeepState { QUEUED, DOWNLOADING, PAUSED, READY, EXPIRING, FAILED }

/**
 * One offline keep as the Downloads screen should render it. This mirrors the
 * queue contract requested from the cache engine (docs/CACHE_SPEC.md /
 * HANDOFF_appui.md #6): bytes progress + a TTL expiry that must be honoured because
 * ephemeral CDN links rot, and the fact that these files are playable **only inside
 * this app**. The engine will emit these; until it does the list stays empty and the
 * screen explains why rather than showing fabricated items.
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
) : ViewModel() {

    private val _uiState = MutableStateFlow(DownloadsUiState())
    val uiState = _uiState.asStateFlow()

    init {
        viewModelScope.launch {
            _uiState.update { it.copy(storage = readStorage(), isLoading = false) }
        }
    }

    fun refresh() {
        viewModelScope.launch { _uiState.update { it.copy(storage = readStorage()) } }
    }

    fun clearStatus() = _uiState.update { it.copy(statusMessage = null) }

    /**
     * Real, cheap, and always meaningful: how much space is left on the app's
     * primary storage. Used for the storage warning + the "playable only in this
     * app" explanation while the queue source is being wired.
     */
    private fun readStorage(): StorageInfo? = try {
        val stat = StatFs(context.filesDir.absolutePath)
        StorageInfo(freeBytes = stat.availableBytes, totalBytes = stat.totalBytes)
    } catch (_: Exception) {
        null
    }

    // --- engine actions (delegate once docs/CACHE_SPEC.md lands) ---

    fun cancel(item: KeptItem) {
        _uiState.update { it.copy(statusMessage = "Cancel requires the offline cache engine (not yet wired).") }
    }

    fun retry(item: KeptItem) {
        _uiState.update { it.copy(statusMessage = "Retry requires the offline cache engine (not yet wired).") }
    }
}
