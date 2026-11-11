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
