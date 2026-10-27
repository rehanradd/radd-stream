package com.raddstream.app.player.subtitles

import androidx.media3.common.C
import androidx.media3.common.text.Cue
import androidx.media3.common.util.UnstableApi
import androidx.media3.extractor.text.Subtitle
import androidx.media3.extractor.text.SubtitleDecoder
import androidx.media3.extractor.text.SubtitleInputBuffer
import androidx.media3.extractor.text.SubtitleOutputBuffer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The offset pipeline is pure timing math on top of Media3's own interfaces, so it is
 * verifiable without a device: event times, cue lookups and the hold-back gate are all
 * deterministic.
 */
@OptIn(UnstableApi::class)
class SubtitleOffsetPipelineTest {

    private val cueA: Cue = Cue.Builder().setText("A").build()
    private val cueB: Cue = Cue.Builder().setText("B").build()

    /** Event at 1 s shows cue A; event at 2 s replaces it with cue B. */
    private val twoCues = TimedSubtitle(
        eventsUs = longArrayOf(1_000_000L, 2_000_000L),
        cues = listOf(listOf(cueA), listOf(cueB)),
    )

    private var offsetMs = 0L

    private fun shifted(source: SubtitleOutputBuffer = FakeBuffer(1_000_000L, twoCues)) =
        OffsetSubtitleOutputBuffer(source, { offsetMs })

    @Test
    fun positiveOffsetPushesEventsAndCueLookupLater() {
        offsetMs = 500

        val buffer = shifted()

        assertEquals(1_500_000L, buffer.getEventTime(0))
        assertEquals(2_500_000L, buffer.getEventTime(1))
        // 1.6 s on the delayed timeline is still before the second event.
        assertEquals(listOf(cueA), buffer.getCues(1_600_000L))
        assertEquals(listOf(cueB), buffer.getCues(2_600_000L))
        assertEquals(0, buffer.getNextEventTimeIndex(1_400_000L))
        assertEquals(1, buffer.getNextEventTimeIndex(1_600_000L))
    }

    @Test
    fun negativeOffsetShowsCuesEarlier() {
        offsetMs = -500

        val buffer = shifted()

        assertEquals(500_000L, buffer.getEventTime(0))
        assertEquals(1_500_000L, buffer.getEventTime(1))
        assertEquals(listOf(cueA), buffer.getCues(600_000L))
        assertEquals(listOf(cueB), buffer.getCues(1_600_000L))
        assertEquals(emptyList<Cue>(), buffer.getCues(400_000L))
    }

    @Test
    fun anAlreadyDecodedBlockFollowsALiveOffsetChange() {
        val buffer = shifted()
        assertEquals(1_000_000L, buffer.getEventTime(0))

        offsetMs = 250

        assertEquals(1_250_000L, buffer.getEventTime(0))
        assertEquals(listOf(cueA), buffer.getCues(1_300_000L))
    }

    @Test
    fun wrappingKeepsSampleTimeAndEndOfStreamFlag() {
        offsetMs = 500
        val source = FakeBuffer(9_000_000L, twoCues).apply { addFlag(C.BUFFER_FLAG_END_OF_STREAM) }

        val buffer = shifted(source)

        assertEquals(9_000_000L, buffer.timeUs)
        assertEquals(9_500_000L, buffer.dueAtUs(offsetMs))
        assertTrue(buffer.isEndOfStream)
    }

    @Test
    fun decoderHoldsEachBlockUntilItsDelayedStart() {
        offsetMs = 500
        val decoder = OffsetSubtitleDecoder(
            FakeDecoder(listOf(FakeBuffer(1_000_000L, twoCues), FakeBuffer(2_000_000L, twoCues))),
            { offsetMs },
        )

        decoder.setPositionUs(1_400_000L)
        assertNull(decoder.dequeueOutputBuffer())

        decoder.setPositionUs(1_500_000L)
        val first = decoder.dequeueOutputBuffer()
        assertNotNull(first)
        assertEquals(1_500_000L, first!!.getEventTime(0))

        decoder.setPositionUs(2_400_000L)
        assertNull(decoder.dequeueOutputBuffer())

        decoder.setPositionUs(2_500_000L)
        assertNotNull(decoder.dequeueOutputBuffer())
    }

    @Test
    fun endOfStreamIsNeverHeldBackForTheOffset() {
        offsetMs = 5_000
        val eos = FakeBuffer(30_000_000L, twoCues).apply { addFlag(C.BUFFER_FLAG_END_OF_STREAM) }
        val decoder = OffsetSubtitleDecoder(
            FakeDecoder(listOf(FakeBuffer(20_000_000L, twoCues), eos)),
            { offsetMs },
        )

        decoder.setPositionUs(1_000_000L)
        val out = decoder.dequeueOutputBuffer()

        assertNotNull(out)
        assertTrue(out!!.isEndOfStream)
        assertFalse(out.isDecodeOnly)
        // Once the stream is ending, the remaining cues use the unshifted timeline.
        assertEquals(1_000_000L, out.getEventTime(0))
    }
}

private class TimedSubtitle(
    private val eventsUs: LongArray,
    private val cues: List<List<Cue>>,
) : Subtitle {

    override fun getEventTimeCount(): Int = eventsUs.size

    override fun getEventTime(index: Int): Long = eventsUs[index]

    override fun getNextEventTimeIndex(timeUs: Long): Int {
        for (index in eventsUs.indices) {
            if (eventsUs[index] > timeUs) return index
        }
        return -1
    }

    override fun getCues(timeUs: Long): MutableList<Cue> {
        var active = -1
        for (index in eventsUs.indices) {
            if (eventsUs[index] <= timeUs) active = index
        }
        return if (active < 0) mutableListOf() else cues[active].toMutableList()
    }
}

private class FakeBuffer(
    timeUs: Long,
    subtitle: Subtitle,
) : SubtitleOutputBuffer() {

    init {
        setContent(timeUs, subtitle, 0L)
    }

    override fun release() = Unit
}

private class FakeDecoder(
    outputs: List<SubtitleOutputBuffer>,
) : SubtitleDecoder {

    private val pending = ArrayDeque(outputs)

    override fun getName(): String = "fake"

    override fun setOutputStartTimeUs(outputStartTimeUs: Long) = Unit

    override fun setPositionUs(positionUs: Long) = Unit

    override fun dequeueInputBuffer(): SubtitleInputBuffer? = null

    override fun queueInputBuffer(inputBuffer: SubtitleInputBuffer) = Unit

    override fun dequeueOutputBuffer(): SubtitleOutputBuffer? =
        if (pending.isEmpty()) null else pending.removeFirst()

    override fun flush() = Unit

    override fun release() = Unit
}
