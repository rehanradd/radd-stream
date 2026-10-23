package com.raddstream.app.player

/**
 * Player-side computation behind the "watching → downloading" affordance (the app's
 * signature feature). Pure Kotlin — `CacheAffordanceTest` pins the math. The engine is only
 * consulted through [ProgressiveCacheEngine]; without it ([CacheEngineHolder.engine] == null)
 * the affordance reports [KeepUiState.Unavailable] instead of pretending.
 */

sealed class KeepUiState {
    /** No engine wired into [CacheEngineHolder] yet — hide the chip, honestly labeled. */
    object Unavailable : KeepUiState()

    /** Watching with a live preview copy: shows saved/remaining + a Keep action. */
    data class Watching(
        val savedBytes: Long,
        val totalBytes: Long?, // null → UI renders "? remaining"
        val isEstimate: Boolean,
        val expiringInMs: Long?, // preview TTL countdown, null → permanent/unknown
    ) : KeepUiState()

    /** Keep requested, engine still fetching the rest. */
    data class Keeping(val savedBytes: Long, val totalBytes: Long?, val bytesPerSec: Long) : KeepUiState()

    /** Fully kept — offline playable (possibly app-private, message carried). */
    data class Stored(val playableOffline: Boolean, val note: String?) : KeepUiState()

    /** Hostile reality carrying a user-visible reason. */
    data class Blocked(val state: CacheState, val message: String) : KeepUiState()
}

object CacheAffordance {

    /**
     * Byte estimate from time progress when the engine has not adopted the session yet:
     * `floor(bufferedFraction × totalBytes)` — conservative (never overstates what was saved).
     * Returns null when the total size is unknown.
     */
    fun estimateBytesSaved(bufferedMs: Long, durationMs: Long, totalBytes: Long?): Long? {
        if (totalBytes == null || totalBytes <= 0 || durationMs <= 0) return null
        val fraction = (bufferedMs.toFloat() / durationMs.toFloat()).coerceIn(0f, 1f)
        return (fraction * totalBytes).toLong()
    }

    fun remaining(savedBytes: Long, totalBytes: Long?): Long? =
        totalBytes?.let { (it - savedBytes).coerceAtLeast(0) }

    /** Map engine snapshot (+ nothing else) into UI state. */
    fun uiStateFor(snapshot: CacheSnapshot?, keepRequested: Boolean): KeepUiState {
        if (snapshot == null) {
            // No engine data at all — never invent progress. keepRequested=true just means the
            // user tapped Keep on a build where the engine isn't wired yet.
            return KeepUiState.Unavailable
        }
        val expiringIn = snapshot.previewExpiresAt?.let {
            (it - System.currentTimeMillis()).coerceAtLeast(0)
        }
        return when (snapshot.state) {
            CacheState.PROGRESSIVE -> KeepUiState.Watching(
                savedBytes = snapshot.bytesSaved,
                totalBytes = snapshot.totalBytes,
                isEstimate = snapshot.isEstimate,
                expiringInMs = expiringIn,
            )
            CacheState.KEEPING -> KeepUiState.Keeping(
                savedBytes = snapshot.bytesSaved,
                totalBytes = snapshot.totalBytes,
                bytesPerSec = snapshot.bytesPerSec,
            )
            CacheState.STORED -> KeepUiState.Stored(playableOffline = true, note = null)
            CacheState.APP_PRIVATE_ONLY -> KeepUiState.Stored(
                playableOffline = true,
                note = "Playable in Radd Stream only",
            )
            CacheState.INTERRUPTED -> KeepUiState.Blocked(
                CacheState.INTERRUPTED,
                "Keep interrupted — will resume from ${formatBytes(snapshot.bytesSaved)}",
            )
            CacheState.STORAGE_FULL -> KeepUiState.Blocked(
                CacheState.STORAGE_FULL,
                "Storage full — free space to keep this file",
            )
            CacheState.EXPIRED -> KeepUiState.Blocked(
                CacheState.EXPIRED,
                "Preview expired (auto-deleted after TTL)",
            )
            CacheState.FAILED -> KeepUiState.Blocked(CacheState.FAILED, "Cache engine failed")
        }
    }

    /** Build the adopt handoff from live player numbers. See contract rules in CacheContract.kt. */
    fun buildAdoptRequest(
        key: CacheSessionKey,
        snapshot: CacheSnapshot?,
        positionMs: Long,
        bufferedMs: Long,
        durationMs: Long,
        expectedTotalBytes: Long?,
        resumable: Boolean,
        printLabel: String,
    ): AdoptRequest {
        val authoritative = snapshot?.takeIf { !it.isEstimate }?.bytesSaved
        val estimate = estimateBytesSaved(bufferedMs, durationMs, expectedTotalBytes ?: snapshot?.totalBytes)
        val bytes = authoritative ?: estimate ?: 0L
        return AdoptRequest(
            key = key,
            url = key.url,
            fetchedBytesSoFar = bytes,
            isByteCursorKnown = authoritative != null,
            positionMs = positionMs,
            bufferedMs = bufferedMs,
            durationMs = durationMs,
            expectedTotalBytes = expectedTotalBytes ?: snapshot?.totalBytes,
            resumable = resumable,
            printLabel = printLabel,
            sharesCacheStorage = snapshot != null,
        )
    }

    fun formatBytes(bytes: Long): String = when {
        bytes >= 1_000_000_000L -> String.format("%.2f GB", bytes / 1_000_000_000.0)
        bytes >= 1_000_000L -> String.format("%.1f MB", bytes / 1_000_000.0)
        bytes >= 1_000L -> String.format("%.1f KB", bytes / 1_000.0)
        else -> "$bytes B"
    }

    /** "1.2 GB of 4.5 GB" style chip text; unknown total handled. */
    fun chipText(state: KeepUiState): String = when (state) {
        is KeepUiState.Watching -> {
            val saved = formatBytes(state.savedBytes)
            val total = state.totalBytes?.let { " of ${formatBytes(it)}" } ?: ""
            val approx = if (state.isEstimate) "~" else ""
            "$approx$saved$total saved"
        }
        is KeepUiState.Keeping ->
            "Keeping ${formatBytes(state.savedBytes)}" +
                (state.totalBytes?.let { " of ${formatBytes(it)}" } ?: "") +
                (if (state.bytesPerSec > 0) " · ${formatBytes(state.bytesPerSec)}/s" else "")
        is KeepUiState.Stored -> "Kept ✓" + (state.note?.let { " · $it" } ?: "")
        is KeepUiState.Blocked -> state.message
        KeepUiState.Unavailable -> "Keep unavailable"
    }
}
