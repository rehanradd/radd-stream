package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** App-design audit (2026-11-12, issue #4): one status word per state. */
class PlayerStatusWordTest {

    @Test
    fun startInFlightIsLoadingEvenWhenPaused() {
        assertEquals(
            PlayerStatusWord.LOADING,
            playerStatusWord(StartPhase.STARTING, isBuffering = false, isPlaying = false),
        )
    }

    @Test
    fun midPlayStallIsBuffering() {
        assertEquals(
            PlayerStatusWord.BUFFERING,
            playerStatusWord(StartPhase.NONE, isBuffering = true, isPlaying = true),
        )
    }

    @Test
    fun settledPauseIsPaused() {
        assertEquals(
            PlayerStatusWord.PAUSED,
            playerStatusWord(StartPhase.NONE, isBuffering = false, isPlaying = false),
        )
    }

    @Test
    fun playingIsNoWord() {
        assertEquals(
            PlayerStatusWord.NONE,
            playerStatusWord(StartPhase.NONE, isBuffering = false, isPlaying = true),
        )
    }

    // F4 (Batch B): the buffering notice's percent.

    @Test
    fun bufferingPercentIsHalfWhenHalfTheFileIsBuffered() {
        assertEquals(50, bufferingPercent(bufferedMs = 45_000, durationMs = 90_000))
    }

    @Test
    fun bufferingPercentIsNullBeforeADurationIsKnown() {
        assertNull(bufferingPercent(bufferedMs = 1_000, durationMs = 0))
    }

    @Test
    fun bufferingPercentIsNullOnALiveStream() {
        // A live window's "percent" is a DVR-window fraction, not progress.
        assertNull(bufferingPercent(bufferedMs = 60_000, durationMs = 7_200_000, isLive = true))
    }

    @Test
    fun bufferingPercentClampsPastTheEndToOneHundred() {
        assertEquals(100, bufferingPercent(bufferedMs = 95_000, durationMs = 90_000))
    }

    // F29 (Batch B): a live stream has no seek path at all.

    @Test
    fun aLiveStreamCannotSeekEvenUnlocked() {
        assertFalse(PlayerUiState(isLive = true, durationMs = 7_200_000).seekEnabled)
    }

    @Test
    fun aLockedVodCannotSeekEither() {
        assertFalse(PlayerUiState(locked = true, durationMs = 90_000).seekEnabled)
    }

    @Test
    fun anUnlockedVodCanSeek() {
        assertTrue(PlayerUiState(durationMs = 90_000).seekEnabled)
    }
}
