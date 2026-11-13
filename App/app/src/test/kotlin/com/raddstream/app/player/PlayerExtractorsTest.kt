package com.raddstream.app.player

import android.net.Uri
import androidx.media3.common.DataReader
import androidx.media3.common.Format
import androidx.media3.common.util.ParsableByteArray
import androidx.media3.extractor.DefaultExtractorsFactory
import androidx.media3.extractor.Extractor
import androidx.media3.extractor.ExtractorInput
import androidx.media3.extractor.ExtractorOutput
import androidx.media3.extractor.PositionHolder
import androidx.media3.extractor.SeekMap
import androidx.media3.extractor.TrackOutput
import androidx.media3.extractor.mkv.MatroskaExtractor
import java.io.EOFException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * Session 156 (2026-11-13) — Salaar play: the winner file is a 973 MB
 * MKV muxed by mkvmerge v4.9.1 with its Cues element at the tail. The
 * default MatroskaExtractor seeks to those cues while preparing, so on a
 * host that ignores Range the player must skip-by-read the whole file to
 * get there and the 20 s start watchdog fires first (Sauce Labs S3: 13
 * presses, 8 server 302s, never a frame). With
 * [MatroskaExtractor.FLAG_DISABLE_SEEK_FOR_CUES] the extractor starts
 * from the first cluster at once.
 *
 * The vector below is a synthetic file in exactly that shape: an EBML
 * header, a Segment whose SeekHead advertises Cues at 973,456,222, Info,
 * one HEVC track, and two clusters. The input pretends to be a
 * 973,535,486-byte file (the real Salaar size) while holding only the
 * 380-byte prefix; reads past the real bytes return end-of-input, the
 * way a Range-ignoring host behaves when the player asks for the tail.
 * The control test (no flag) proves the vector actually exercises the
 * cue seek — without it the flagged test could pass vacuously.
 *
 * Robolectric (x86_64-only like every Robolectric suite): the extractor
 * needs real `android.util` classes, which the plain JVM stubs cannot
 * give it.
 */
@RunWith(RobolectricTestRunner::class)
class PlayerExtractorsTest {

    // 380 bytes
    private val TAIL_CUED_MKV: ByteArray = byteArrayOf(
            0x1A.toByte(), 0x45.toByte(), 0xDF.toByte(), 0xA3.toByte(), 0xA3.toByte(), 0x42.toByte(), 0x86.toByte(), 0x81.toByte(), 0x01.toByte(), 0x42.toByte(), 0xF7.toByte(), 0x81.toByte(), 0x01.toByte(), 0x42.toByte(), 0xF2.toByte(), 0x81.toByte(),
            0x04.toByte(), 0x42.toByte(), 0xF3.toByte(), 0x81.toByte(), 0x08.toByte(), 0x42.toByte(), 0x82.toByte(), 0x88.toByte(), 0x6D.toByte(), 0x61.toByte(), 0x74.toByte(), 0x72.toByte(), 0x6F.toByte(), 0x73.toByte(), 0x6B.toByte(), 0x61.toByte(),
            0x42.toByte(), 0x87.toByte(), 0x81.toByte(), 0x04.toByte(), 0x42.toByte(), 0x85.toByte(), 0x81.toByte(), 0x02.toByte(), 0x18.toByte(), 0x53.toByte(), 0x80.toByte(), 0x67.toByte(), 0x01.toByte(), 0xFF.toByte(), 0xFF.toByte(), 0xFF.toByte(),
            0xFF.toByte(), 0xFF.toByte(), 0xFF.toByte(), 0xFF.toByte(), 0x11.toByte(), 0x4D.toByte(), 0x9B.toByte(), 0x74.toByte(), 0x91.toByte(), 0x4D.toByte(), 0xBB.toByte(), 0x8E.toByte(), 0x53.toByte(), 0xAB.toByte(), 0x84.toByte(), 0x1C.toByte(),
            0x53.toByte(), 0xBB.toByte(), 0x6B.toByte(), 0x53.toByte(), 0xAC.toByte(), 0x84.toByte(), 0x3A.toByte(), 0x05.toByte(), 0xC3.toByte(), 0x5E.toByte(), 0x15.toByte(), 0x49.toByte(), 0xA9.toByte(), 0x66.toByte(), 0xCA.toByte(), 0x2A.toByte(),
            0xD7.toByte(), 0xB1.toByte(), 0x83.toByte(), 0x0F.toByte(), 0x42.toByte(), 0x40.toByte(), 0x44.toByte(), 0x89.toByte(), 0x88.toByte(), 0x40.toByte(), 0xED.toByte(), 0x4C.toByte(), 0x00.toByte(), 0x00.toByte(), 0x00.toByte(), 0x00.toByte(),
            0x00.toByte(), 0x4D.toByte(), 0x80.toByte(), 0xA3.toByte(), 0x6C.toByte(), 0x69.toByte(), 0x62.toByte(), 0x65.toByte(), 0x62.toByte(), 0x6D.toByte(), 0x6C.toByte(), 0x20.toByte(), 0x76.toByte(), 0x31.toByte(), 0x2E.toByte(), 0x32.toByte(),
            0x2E.toByte(), 0x31.toByte(), 0x20.toByte(), 0x2B.toByte(), 0x20.toByte(), 0x6C.toByte(), 0x69.toByte(), 0x62.toByte(), 0x6D.toByte(), 0x61.toByte(), 0x74.toByte(), 0x72.toByte(), 0x6F.toByte(), 0x73.toByte(), 0x6B.toByte(), 0x61.toByte(),
            0x20.toByte(), 0x76.toByte(), 0x31.toByte(), 0x2E.toByte(), 0x31.toByte(), 0x2E.toByte(), 0x31.toByte(), 0x57.toByte(), 0x41.toByte(), 0x8F.toByte(), 0x6D.toByte(), 0x6B.toByte(), 0x76.toByte(), 0x6D.toByte(), 0x65.toByte(), 0x72.toByte(),
            0x67.toByte(), 0x65.toByte(), 0x20.toByte(), 0x76.toByte(), 0x34.toByte(), 0x2E.toByte(), 0x39.toByte(), 0x2E.toByte(), 0x31.toByte(), 0x16.toByte(), 0x54.toByte(), 0xAE.toByte(), 0x6B.toByte(), 0xC2.toByte(), 0xAE.toByte(), 0xC0.toByte(),
            0xD7.toByte(), 0x81.toByte(), 0x01.toByte(), 0x73.toByte(), 0xC5.toByte(), 0x81.toByte(), 0x01.toByte(), 0x83.toByte(), 0x81.toByte(), 0x01.toByte(), 0x86.toByte(), 0x90.toByte(), 0x56.toByte(), 0x5F.toByte(), 0x4D.toByte(), 0x50.toByte(),
            0x45.toByte(), 0x47.toByte(), 0x48.toByte(), 0x2F.toByte(), 0x49.toByte(), 0x53.toByte(), 0x4F.toByte(), 0x2F.toByte(), 0x48.toByte(), 0x45.toByte(), 0x56.toByte(), 0x43.toByte(), 0x63.toByte(), 0xA2.toByte(), 0x97.toByte(), 0x01.toByte(),
            0x01.toByte(), 0x60.toByte(), 0x00.toByte(), 0x00.toByte(), 0x00.toByte(), 0x90.toByte(), 0x00.toByte(), 0x00.toByte(), 0x00.toByte(), 0x00.toByte(), 0x00.toByte(), 0x78.toByte(), 0xF0.toByte(), 0x00.toByte(), 0xFC.toByte(), 0xFD.toByte(),
            0xF8.toByte(), 0xF8.toByte(), 0x00.toByte(), 0x00.toByte(), 0x03.toByte(), 0x00.toByte(), 0xE0.toByte(), 0x88.toByte(), 0xB0.toByte(), 0x82.toByte(), 0x07.toByte(), 0x80.toByte(), 0xBA.toByte(), 0x82.toByte(), 0x04.toByte(), 0x38.toByte(),
            0x1F.toByte(), 0x43.toByte(), 0xB6.toByte(), 0x75.toByte(), 0xC9.toByte(), 0xE7.toByte(), 0x81.toByte(), 0x00.toByte(), 0xA3.toByte(), 0xC4.toByte(), 0x81.toByte(), 0x00.toByte(), 0x00.toByte(), 0x01.toByte(), 0x00.toByte(), 0x01.toByte(),
            0x02.toByte(), 0x03.toByte(), 0x04.toByte(), 0x05.toByte(), 0x06.toByte(), 0x07.toByte(), 0x08.toByte(), 0x09.toByte(), 0x0A.toByte(), 0x0B.toByte(), 0x0C.toByte(), 0x0D.toByte(), 0x0E.toByte(), 0x0F.toByte(), 0x10.toByte(), 0x11.toByte(),
            0x12.toByte(), 0x13.toByte(), 0x14.toByte(), 0x15.toByte(), 0x16.toByte(), 0x17.toByte(), 0x18.toByte(), 0x19.toByte(), 0x1A.toByte(), 0x1B.toByte(), 0x1C.toByte(), 0x1D.toByte(), 0x1E.toByte(), 0x1F.toByte(), 0x20.toByte(), 0x21.toByte(),
            0x22.toByte(), 0x23.toByte(), 0x24.toByte(), 0x25.toByte(), 0x26.toByte(), 0x27.toByte(), 0x28.toByte(), 0x29.toByte(), 0x2A.toByte(), 0x2B.toByte(), 0x2C.toByte(), 0x2D.toByte(), 0x2E.toByte(), 0x2F.toByte(), 0x30.toByte(), 0x31.toByte(),
            0x32.toByte(), 0x33.toByte(), 0x34.toByte(), 0x35.toByte(), 0x36.toByte(), 0x37.toByte(), 0x38.toByte(), 0x39.toByte(), 0x3A.toByte(), 0x3B.toByte(), 0x3C.toByte(), 0x3D.toByte(), 0x3E.toByte(), 0x3F.toByte(), 0x1F.toByte(), 0x43.toByte(),
            0xB6.toByte(), 0x75.toByte(), 0xC9.toByte(), 0xE7.toByte(), 0x81.toByte(), 0x20.toByte(), 0xA3.toByte(), 0xC4.toByte(), 0x81.toByte(), 0x00.toByte(), 0x20.toByte(), 0x01.toByte(), 0x00.toByte(), 0x01.toByte(), 0x02.toByte(), 0x03.toByte(),
            0x04.toByte(), 0x05.toByte(), 0x06.toByte(), 0x07.toByte(), 0x08.toByte(), 0x09.toByte(), 0x0A.toByte(), 0x0B.toByte(), 0x0C.toByte(), 0x0D.toByte(), 0x0E.toByte(), 0x0F.toByte(), 0x10.toByte(), 0x11.toByte(), 0x12.toByte(), 0x13.toByte(),
            0x14.toByte(), 0x15.toByte(), 0x16.toByte(), 0x17.toByte(), 0x18.toByte(), 0x19.toByte(), 0x1A.toByte(), 0x1B.toByte(), 0x1C.toByte(), 0x1D.toByte(), 0x1E.toByte(), 0x1F.toByte(), 0x20.toByte(), 0x21.toByte(), 0x22.toByte(), 0x23.toByte(),
            0x24.toByte(), 0x25.toByte(), 0x26.toByte(), 0x27.toByte(), 0x28.toByte(), 0x29.toByte(), 0x2A.toByte(), 0x2B.toByte(), 0x2C.toByte(), 0x2D.toByte(), 0x2E.toByte(), 0x2F.toByte(), 0x30.toByte(), 0x31.toByte(), 0x32.toByte(), 0x33.toByte(),
            0x34.toByte(), 0x35.toByte(), 0x36.toByte(), 0x37.toByte(), 0x38.toByte(), 0x39.toByte(), 0x3A.toByte(), 0x3B.toByte(), 0x3C.toByte(), 0x3D.toByte(), 0x3E.toByte(), 0x3F.toByte(),
        )

    /** The Cues position the synthetic SeekHead advertises (segment-relative). */
    private val advertisedCuesPosition = 973_456_222L

    /** The real Salaar file size the input pretends to be. */
    private val fakeLength = 973_535_486L

    private data class DriveOutcome(
        val sniffed: Boolean,
        val outcome: String,
        val seeks: List<Long>,
        val samples: Int,
    )

    /**
     * An [ExtractorInput] over the synthetic prefix that reports the real
     * Salaar length. Seeks are recorded, not performed by the extractor:
     * the extractor returns `RESULT_SEEK` and the caller seeks, which is
     * the contract — so the recorded seeks are exactly the seeks the
     * extractor asked for.
     */
    private inner class FakeInput(private val data: ByteArray) : ExtractorInput {
        val seeks = mutableListOf<Long>()
        private var position = 0L
        private var peekPosition = 0L

        fun seekTo(pos: Long) {
            seeks.add(pos)
            position = pos
            peekPosition = pos
        }

        private fun readAt(pos: Long, target: ByteArray, offset: Int, length: Int): Int {
            if (pos >= data.size) return -1
            val n = minOf(length, (data.size - pos).toInt())
            data.copyInto(target, offset, pos.toInt(), pos.toInt() + n)
            return n
        }

        override fun read(target: ByteArray, offset: Int, length: Int): Int {
            val n = readAt(position, target, offset, length)
            if (n > 0) {
                position += n
                peekPosition = position
            }
            return n
        }

        override fun readFully(target: ByteArray, offset: Int, length: Int, allowEndOfInput: Boolean): Boolean {
            var read = 0
            while (read < length) {
                val n = read(target, offset + read, length - read)
                if (n == -1) {
                    if (allowEndOfInput) return false
                    throw EOFException()
                }
                read += n
            }
            return true
        }

        override fun readFully(target: ByteArray, offset: Int, length: Int) {
            readFully(target, offset, length, false)
        }

        override fun skip(length: Int): Int {
            val remaining = data.size - position
            if (remaining <= 0) return -1
            val n = minOf(length.toLong(), remaining).toInt()
            position += n
            peekPosition = position
            return n
        }

        override fun skipFully(length: Int, allowEndOfInput: Boolean): Boolean {
            var skipped = 0
            while (skipped < length) {
                val n = skip(length - skipped)
                if (n == -1) {
                    if (allowEndOfInput) return false
                    throw EOFException()
                }
                skipped += n
            }
            return true
        }

        override fun skipFully(length: Int) {
            skipFully(length, false)
        }

        override fun peek(target: ByteArray, offset: Int, length: Int): Int {
            val n = readAt(peekPosition, target, offset, length)
            if (n > 0) peekPosition += n
            return n
        }

        override fun peekFully(target: ByteArray, offset: Int, length: Int, allowEndOfInput: Boolean): Boolean {
            var read = 0
            while (read < length) {
                val n = peek(target, offset + read, length - read)
                if (n == -1) {
                    if (allowEndOfInput) return false
                    throw EOFException()
                }
                read += n
            }
            return true
        }

        override fun peekFully(target: ByteArray, offset: Int, length: Int) {
            peekFully(target, offset, length, false)
        }

        override fun advancePeekPosition(length: Int, allowEndOfInput: Boolean): Boolean {
            if (peekPosition + length > data.size) {
                if (allowEndOfInput) return false
                throw EOFException()
            }
            peekPosition += length
            return true
        }

        override fun advancePeekPosition(length: Int) {
            advancePeekPosition(length, false)
        }

        override fun resetPeekPosition() {
            peekPosition = position
        }

        override fun getPeekPosition(): Long = peekPosition
        override fun getPosition(): Long = position
        override fun getLength(): Long = fakeLength

        override fun <E : Throwable> setRetryPosition(position: Long, e: E) {
            throw e
        }
    }

    private class FakeOutput : ExtractorOutput {
        var samples = 0
        var seekable: Boolean? = null

        override fun track(id: Int, type: Int): TrackOutput {
            return object : TrackOutput {
                override fun format(format: Format) = Unit

                override fun sampleData(
                    input: DataReader,
                    length: Int,
                    allowEndOfInput: Boolean,
                    sampleDataPart: Int,
                ): Int {
                    var remaining = length
                    val scratch = ByteArray(minOf(length, 8192))
                    while (remaining > 0) {
                        val n = input.read(scratch, 0, minOf(remaining, scratch.size))
                        if (n == -1) break
                        remaining -= n
                    }
                    return length - remaining
                }

                override fun sampleData(data: ParsableByteArray, length: Int, sampleDataPart: Int) = Unit

                override fun sampleMetadata(
                    timeUs: Long,
                    flags: Int,
                    size: Int,
                    offset: Int,
                    cryptoData: TrackOutput.CryptoData?,
                ) {
                    samples++
                }
            }
        }

        override fun endTracks() = Unit
        override fun seekMap(seekMap: SeekMap) {
            seekable = seekMap.isSeekable
        }
    }

    private fun drive(extractor: Extractor): DriveOutcome {
        val input = FakeInput(TAIL_CUED_MKV)
        val output = FakeOutput()
        extractor.init(output)
        val sniffed = extractor.sniff(input)
        val holder = PositionHolder()
        var outcome = "loop-ended"
        for (i in 0 until 500) {
            val result = try {
                extractor.read(input, holder)
            } catch (e: Exception) {
                outcome = "threw ${e.javaClass.simpleName}"
                break
            }
            if (result == Extractor.RESULT_END_OF_INPUT) {
                outcome = "end-of-input"
                break
            }
            if (result == Extractor.RESULT_SEEK) input.seekTo(holder.position)
        }
        extractor.release()
        return DriveOutcome(sniffed, outcome, input.seeks.toList(), output.samples)
    }

    private fun matroskaFromFactory(factory: DefaultExtractorsFactory): Extractor {
        val extractors = factory.createExtractors(
            Uri.parse("https://example.invalid/salaar.mkv"),
            emptyMap(),
        )
        return extractors.first { it is MatroskaExtractor }
    }

    @Test
    fun `unflagged extractor seeks to the tail cues`() {
        val outcome = drive(MatroskaExtractor(0))

        assertTrue(outcome.sniffed)
        // Cues at 973,456,222 + the 52-byte segment offset.
        assertTrue(outcome.seeks.contains(advertisedCuesPosition + 52L))
        assertEquals(0, outcome.samples)
    }

    @Test
    fun `flagged extractor starts from the first cluster`() {
        val outcome = drive(MatroskaExtractor(playerMatroskaExtractorFlags))

        assertTrue(outcome.sniffed)
        assertTrue(outcome.seeks.none { it > 1_000_000L })
        assertTrue(outcome.samples >= 1)
    }

    @Test
    fun `player factory serves mkv through a matroska extractor`() {
        val extractors = buildPlayerExtractorsFactory().createExtractors(
            Uri.parse("https://example.invalid/salaar.mkv"),
            emptyMap(),
        )

        assertTrue(extractors.any { it is MatroskaExtractor })
    }

    @Test
    fun `extractor from the player factory does not seek for cues`() {
        val extractor = matroskaFromFactory(buildPlayerExtractorsFactory())
        val outcome = drive(extractor)

        assertTrue(outcome.sniffed)
        assertTrue(outcome.seeks.none { it > 1_000_000L })
        assertTrue(outcome.samples >= 1)
    }

    @Test
    fun `extractor from an unflagged factory seeks for cues`() {
        val extractor = matroskaFromFactory(DefaultExtractorsFactory())
        val outcome = drive(extractor)

        assertTrue(outcome.seeks.contains(advertisedCuesPosition + 52L))
        assertEquals(0, outcome.samples)
    }
}
