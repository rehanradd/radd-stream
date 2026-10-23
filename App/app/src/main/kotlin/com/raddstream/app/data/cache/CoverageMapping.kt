package com.raddstream.app.data.cache

/**
 * Time ↔ byte mapping, including the packed-season case from `API_V2.md` §2.3 / §5.
 *
 * Two shapes of file exist:
 *  - `single_episode` / `whole_work`: playback time is relative to the file start.
 *  - `season_pack` / `episode_range`: one file contains many episodes; episode N starts at
 *    `offsetSeconds` inside the pack (the `cat_release_episodes.offset_seconds` value, or a
 *    user-calibrated offset via `POST /api/v2/episodes/{id}/offset`).
 *
 * We assume constant bitrate to convert seconds ↔ bytes (`size_bytes` is known from the
 * release/print). This is an approximation, but the ledger is byte-accurate — the mapping
 * only decides *which* bytes to prioritise, never which bytes are valid. When the real
 * container is variable-bitrate the estimate is corrected organically: the verified prefix
 * on disk is the truth and playback never reads beyond it.
 */
data class CoverageMapping(
    val totalSizeBytes: Long,
    val totalDurationSeconds: Double,
    /** Start time, in seconds *within the pack file*, of the current episode. 0 for a movie. */
    val episodeOffsetSeconds: Double = 0.0,
    /** Length of the current episode in seconds; ignored when 0 (movie / unknown). */
    val episodeDurationSeconds: Double = 0.0,
    val isPacked: Boolean = false,
) {
    private val bytesPerSecond: Double
        get() = if (totalDurationSeconds > 0 && totalSizeBytes > 0)
            totalSizeBytes / totalDurationSeconds else 0.0

    /** Absolute byte offset in the file for a time measured from the start of the file. */
    fun fileByteAt(fileTimeSeconds: Double): Long {
        if (bytesPerSecond <= 0.0) return 0L
        val clamped = fileTimeSeconds.coerceIn(0.0, totalDurationSeconds)
        return (clamped * bytesPerSecond).toLong().coerceIn(0L, totalSizeBytes)
    }

    /** File-relative time (seconds) for an absolute byte offset. */
    fun fileTimeAtByte(byteOffset: Long): Double {
        if (bytesPerSecond <= 0.0) return 0.0
        val clamped = byteOffset.coerceIn(0L, totalSizeBytes)
        return clamped / bytesPerSecond
    }

    /** Byte offset for a time measured *within the current episode* (player position). */
    fun episodeByteAt(episodeTimeSeconds: Double): Long =
        fileByteAt(episodeOffsetSeconds + episodeTimeSeconds)

    /** The absolute byte window that holds just the current episode inside a pack. */
    fun episodeByteRange(): LongRange? {
        if (!isPacked || episodeDurationSeconds <= 0.0 || bytesPerSecond <= 0.0) return null
        val start = fileByteAt(episodeOffsetSeconds)
        val end = fileByteAt(episodeOffsetSeconds + episodeDurationSeconds)
        return if (end > start) start until end else null
    }

    /**
     * When a user pauses at `episodeTimeSeconds` and taps "keep this", how many episode-
     * relative seconds are already safely on disk (bounded by the verified byte prefix).
     */
    fun watchedSecondsCovered(verifiedPrefixBytes: Long, episodeTimeSeconds: Double): Double {
        val coveredFileSeconds = fileTimeAtByte(verifiedPrefixBytes)
        val coveredEpisodeSeconds = coveredFileSeconds - episodeOffsetSeconds
        return coveredEpisodeSeconds.coerceIn(0.0, episodeTimeSeconds)
    }

    companion object {
        /** A plain movie / single-episode file: no pack offset. */
        fun simple(totalSizeBytes: Long, totalDurationSeconds: Double) =
            CoverageMapping(totalSizeBytes, totalDurationSeconds)
    }
}
