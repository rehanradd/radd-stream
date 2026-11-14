package com.raddstream.app.player

/**
 * App-design audit (2026-11-12, issue #4): the player must say, in one
 * word beside the scrubber, which of its three states it is in — loading,
 * paused, or buffering — instead of leaving the viewer to guess from a
 * play triangle. The decision is pure so the player screen cannot drift
 * from it; the screen only maps the word to a string resource.
 */
enum class PlayerStatusWord {
    LOADING,
    BUFFERING,
    PAUSED,
    /** Playing normally: no status word, the time alone speaks. */
    NONE,
}

fun playerStatusWord(
    startPhase: StartPhase,
    isBuffering: Boolean,
    isPlaying: Boolean,
): PlayerStatusWord = when {
    startPhase != StartPhase.NONE -> PlayerStatusWord.LOADING
    isBuffering -> PlayerStatusWord.BUFFERING
    !isPlaying -> PlayerStatusWord.PAUSED
    else -> PlayerStatusWord.NONE
}

/**
 * F4 (Batch B): how much of the file is buffered ahead, as a whole percent —
 * the buffering notice's number. Null when there is no duration to measure
 * against (still starting, or a live stream: a live window's "percent" is a
 * DVR-window fraction, not progress, so it never shows one). A buffered
 * position past the end clamps to 100; a negative reading clamps to 0 —
 * neither is a number a viewer should ever see.
 */
fun bufferingPercent(bufferedMs: Long, durationMs: Long, isLive: Boolean = false): Int? {
    if (isLive || durationMs <= 0L || bufferedMs < 0L) return null
    return ((bufferedMs.toFloat() / durationMs).coerceIn(0f, 1f) * 100).toInt()
}
