package com.raddstream.app.player.subtitles

import androidx.annotation.OptIn
import androidx.media3.common.C
import androidx.media3.common.Format
import androidx.media3.common.text.Cue
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.text.SubtitleDecoderFactory
import androidx.media3.extractor.text.SubtitleDecoder
import androidx.media3.extractor.text.SubtitleInputBuffer
import androidx.media3.extractor.text.SubtitleOutputBuffer

/**
 * Media3 1.3.1 has no `setSubtitleOffsetUs`, so the player applies the delay one layer below
 * the API the directive names: a [SubtitleDecoder] wrapper holds each decoded block back until
 * the viewer's position reaches the block's delayed start, and [androidx.media3.exoplayer.text.TextRenderer]
 * keeps rendering exactly as it did.
 *
 * Holding a block back is equivalent to shifting every cue later, but unlike rewriting event
 * times it stays correct when the slider moves mid-cue: the due time is re-evaluated against
 * the live offset on every frame, not frozen when the block was decoded. It also keeps the
 * renderer's own sample hand-over, seek reset and end-of-stream handling untouched.
 *
 * Only the *legacy* text pipeline is affected — which is the one this app uses, because
 * [androidx.media3.exoplayer.source.DefaultMediaSourceFactory] parses subtitles during
 * extraction only when asked (`experimentalParseSubtitlesDuringExtraction`), and this service
 * never asks. Embedded SRT/SSA/VTT clips therefore reach [SubtitleDecoderFactory.DEFAULT] and
 * pass through here. External SRT/VTT files never take this path: they are parsed in-app and
 * drawn by the custom overlay, which honours [SubtitleUiSettings.delayMs] directly.
 *
 * Sign convention matches the overlay and the sheet: a POSITIVE offset shows text later.
 */
@OptIn(UnstableApi::class)
class OffsetSubtitleDecoderFactory(
    private val offsetMs: () -> Long,
) : SubtitleDecoderFactory {

    override fun supportsFormat(format: Format): Boolean =
        SubtitleDecoderFactory.DEFAULT.supportsFormat(format)

    override fun createDecoder(format: Format): SubtitleDecoder =
        OffsetSubtitleDecoder(SubtitleDecoderFactory.DEFAULT.createDecoder(format), offsetMs)
}

@OptIn(UnstableApi::class)
internal class OffsetSubtitleDecoder(
    private val delegate: SubtitleDecoder,
    private val offsetMs: () -> Long,
) : SubtitleDecoder {

    /** Decoded but not yet due. Bounded by the delegate's own tiny output pool. */
    private val pending = ArrayDeque<OffsetSubtitleOutputBuffer>()

    private var positionUs = 0L

    /**
     * Set at end of stream: the remaining cues render on the unshifted timeline so the
     * renderer can actually finish. Otherwise a positive offset would keep its last event
     * "in the future" past the media's end and stall the period hand-over.
     */
    private var drainingToEnd = false

    private fun activeOffsetMs(): Long = if (drainingToEnd) 0L else offsetMs()

    override fun getName(): String = "offset-" + delegate.name

    override fun setOutputStartTimeUs(outputStartTimeUs: Long) {
        delegate.setOutputStartTimeUs(outputStartTimeUs)
    }

    override fun setPositionUs(positionUs: Long) {
        this.positionUs = positionUs
        delegate.setPositionUs(positionUs)
    }

    override fun dequeueInputBuffer(): SubtitleInputBuffer? = delegate.dequeueInputBuffer()

    override fun queueInputBuffer(inputBuffer: SubtitleInputBuffer) {
        delegate.queueInputBuffer(inputBuffer)
    }

    override fun dequeueOutputBuffer(): SubtitleOutputBuffer? {
        while (true) {
            val head = pending.firstOrNull()
            if (head != null && head.dueAtUs(activeOffsetMs()) <= positionUs) {
                pending.removeFirst()
                return head
            }
            val next = delegate.dequeueOutputBuffer() ?: return null
            if (next.isEndOfStream) {
                // The renderer only learns the stream ended from this buffer, so it must not
                // wait behind cues that a positive offset has pushed past the media's end.
                drainingToEnd = true
                releasePending()
                return OffsetSubtitleOutputBuffer(next, ::activeOffsetMs)
            }
            pending.addLast(OffsetSubtitleOutputBuffer(next, ::activeOffsetMs))
        }
    }

    override fun flush() {
        releasePending()
        drainingToEnd = false
        delegate.flush()
    }

    override fun release() {
        releasePending()
        delegate.release()
    }

    private fun releasePending() {
        while (pending.isNotEmpty()) pending.removeFirst().release()
    }
}

/**
 * One decoded block, re-timed by query rather than by copying its cues: event times move by
 * the live offset (which is what the renderer compares against its position) and every cue
 * lookup asks the delegate for the time that many microseconds earlier.
 */
@OptIn(UnstableApi::class)
internal class OffsetSubtitleOutputBuffer(
    private var source: SubtitleOutputBuffer?,
    private val offsetMs: () -> Long,
) : SubtitleOutputBuffer() {

    init {
        val delegate = source
        if (delegate != null) {
            timeUs = delegate.timeUs
            skippedOutputBufferCount = delegate.skippedOutputBufferCount
            shouldBeSkipped = delegate.shouldBeSkipped
            if (delegate.isEndOfStream) addFlag(C.BUFFER_FLAG_END_OF_STREAM)
            if (delegate.isDecodeOnly) addFlag(C.BUFFER_FLAG_DECODE_ONLY)
            if (delegate.isFirstSample) addFlag(C.BUFFER_FLAG_FIRST_SAMPLE)
            if (delegate.isKeyFrame) addFlag(C.BUFFER_FLAG_KEY_FRAME)
            if (delegate.isLastSample) addFlag(C.BUFFER_FLAG_LAST_SAMPLE)
            if (delegate.hasSupplementalData()) addFlag(C.BUFFER_FLAG_HAS_SUPPLEMENTAL_DATA)
        }
    }

    /** When this block starts on the viewer's timeline, for a given live offset. */
    fun dueAtUs(liveOffsetMs: Long): Long = timeUs + liveOffsetMs * 1_000L

    private fun offsetUs(): Long = offsetMs() * 1_000L

    override fun getEventTimeCount(): Int = source?.getEventTimeCount() ?: 0

    override fun getEventTime(index: Int): Long =
        (source?.getEventTime(index) ?: 0L) + offsetUs()

    override fun getNextEventTimeIndex(timeUs: Long): Int =
        source?.getNextEventTimeIndex(timeUs - offsetUs()) ?: -1

    override fun getCues(timeUs: Long): MutableList<Cue> {
        val delegate = source ?: return mutableListOf()
        return delegate.getCues(timeUs - offsetUs()).toMutableList()
    }

    override fun release() {
        val delegate = source ?: return
        source = null
        delegate.release()
    }

    override fun clear() {
        source = null
        super.clear()
    }
}
