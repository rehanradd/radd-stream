package com.raddstream.app.player

/**
 * MX Player sleep timer with fade-out (menu → Tools → Sleep timer, confirmed in the official
 * changelog; fade-out is MX's shipped behavior). Pure logic — the ViewModel feeds ticks and
 * applies [volumeFactor] to `player.volume`, pauses when [shouldPause] (volume 0..1 setter
 * verified in Player.java 1.3.1).
 */

enum class SleepMode { OFF, COUNTDOWN, END_OF_VIDEO }

data class SleepTimerState(
    val mode: SleepMode = SleepMode.OFF,
    /** Milliseconds remaining in COUNTDOWN mode; ignored otherwise. */
    val remainingMs: Long = 0,
    /** Fade window in ms (MX default feel ≈ 30 s; ours configurable). */
    val fadeMs: Long = DEFAULT_FADE_MS,
) {
    val active: Boolean get() = mode != SleepMode.OFF

    companion object {
        const val DEFAULT_FADE_MS = 30_000L
        val PRESETS_MS: List<Long> = listOf(5, 10, 15, 30, 45, 60, 90, 120).map { it * 60_000L }
    }
}

data class SleepTick(
    val state: SleepTimerState,
    /** Multiply the user's own volume by this to get the volume to set on the player. */
    val volumeFactor: Float,
    val shouldPause: Boolean,
    /** True on the tick the timer just fired, for one-shot UI messaging. */
    val justFired: Boolean,
)

class SleepTimer(initial: SleepTimerState = SleepTimerState()) {

    private var state = initial

    fun snapshot(): SleepTimerState = state

    /** COUNTDOWN mode: start/replace the timer. */
    fun start(ms: Long) {
        state = SleepTimerState(
            mode = SleepMode.COUNTDOWN,
            remainingMs = ms.coerceAtLeast(0),
            fadeMs = state.fadeMs,
        )
    }

    /** END_OF_VIDEO mode: pause at the media boundary instead of a clock. */
    fun armEndOfVideo() {
        state = SleepTimerState(mode = SleepMode.END_OF_VIDEO, remainingMs = 0, fadeMs = state.fadeMs)
    }

    fun cancel() {
        state = SleepTimerState(mode = SleepMode.OFF, remainingMs = 0, fadeMs = state.fadeMs)
    }

    /** Advance the countdown; call from the UI ticker with real elapsed milliseconds. */
    fun onTick(elapsedMs: Long): SleepTick {
        if (state.mode != SleepMode.COUNTDOWN) {
            return SleepTick(state, 1f, false, false)
        }
        val before = state.remainingMs
        val remaining = (before - elapsedMs).coerceAtLeast(0)
        val fired = before > 0 && remaining == 0L
        state = state.copy(remainingMs = remaining)
        return SleepTick(
            state = state,
            volumeFactor = volumeFactorFor(remaining, state.fadeMs),
            shouldPause = fired,
            justFired = fired,
        )
    }

    companion object {
        /**
         * Linear fade from 1 → 0 across the last [fadeMs]; 1 outside the window.
         * Pure so tests can pin the curve.
         */
        fun volumeFactorFor(remainingMs: Long, fadeMs: Long): Float {
            if (fadeMs <= 0) return if (remainingMs <= 0) 0f else 1f
            if (remainingMs >= fadeMs) return 1f
            if (remainingMs <= 0) return 0f
            return (remainingMs.toFloat() / fadeMs.toFloat()).coerceIn(0f, 1f)
        }
    }
}
