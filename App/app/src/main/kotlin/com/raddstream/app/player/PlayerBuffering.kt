package com.raddstream.app.player

/**
 * How much media the player keeps ahead of the playhead, and how little it needs before it
 * shows a picture.
 *
 * These four numbers are one owner because [androidx.media3.exoplayer.DefaultLoadControl]
 * checks their relationship against each other when the load control is built, and a wrong
 * pair is a crash at playback start rather than a compile error: the startup buffer must not
 * exceed either the minimum buffer or the rebuffer threshold. Stating the numbers here lets a
 * unit test on a JVM hold that relationship, instead of a phone finding it on the first tap of
 * a poster.
 *
 * The shape of the choice: 500 ms of buffered media is enough to fill the first frame, so
 * starting is immediate — a viewer sees the picture, not a spinner. Fifteen seconds is what
 * the player then tries to hold, and fifty is the ceiling a fast link may run to before it
 * stops fetching to save battery and cache. The rebuffer threshold is deliberately twice the
 * startup threshold: getting going is cheap, and recovering from a stall should not start
 * again into the same stall one frame later.
 *
 * [PRIORITIZE_TIME_OVER_SIZE] decides what happens when the two budgets disagree. A
 * progressive MKV at a high bitrate reaches the default 50 MB byte cap well before it holds
 * fifteen seconds, and a player that stops on the byte cap is a player that re-buffers while
 * it still has bandwidth — which is the exact stutter this whole file exists to remove. Time
 * wins.
 */
object PlayerBuffering {
    const val MIN_BUFFER_MS = 15_000
    const val MAX_BUFFER_MS = 50_000
    const val BUFFER_FOR_PLAYBACK_MS = 500
    const val BUFFER_FOR_PLAYBACK_AFTER_REBUFFER_MS = 1_000
    const val PRIORITIZE_TIME_OVER_SIZE = true
}
