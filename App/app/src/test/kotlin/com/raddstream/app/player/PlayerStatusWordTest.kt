package com.raddstream.app.player

import org.junit.Assert.assertEquals
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
}
