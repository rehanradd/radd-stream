package com.raddstream.app.player

import androidx.annotation.OptIn
import androidx.media3.common.util.UnstableApi
import androidx.media3.extractor.DefaultExtractorsFactory
import androidx.media3.extractor.mkv.MatroskaExtractor

/**
 * The Matroska flags the app player runs with.
 *
 * Salaar (2026-11-13, Session 156): the winner file is a 973 MB MKV
 * muxed by mkvmerge v4.9.1 with its Cues element at the tail (offset
 * 973,456,222, found by reading the SeekHead). By default Media3's
 * MatroskaExtractor seeks to those cues while preparing, so on a host
 * that ignores Range the player must skip-by-read the whole file to get
 * there — minutes of downloading before the first frame — and the 20 s
 * start watchdog fires first. With [MatroskaExtractor.FLAG_DISABLE_SEEK_FOR_CUES]
 * the extractor never seeks for cues and starts from the first cluster at
 * once; the trade-off is that a tail-cued MKV becomes unseekable, which
 * the extractor reports in its seek map. Well-muxed MKVs (cues before
 * the first cluster) and every non-MKV container are unaffected: the
 * flag only disables the cue seek, it does not change what is decoded.
 * Proven by [PlayerExtractorsTest] driving the real extractor over a
 * synthetic tail-cued MKV: unflagged it seeks to 973,456,274 and emits
 * no sample; flagged it seeks nowhere and emits a sample.
 */
@OptIn(UnstableApi::class)
internal val playerMatroskaExtractorFlags: Int =
    MatroskaExtractor.FLAG_DISABLE_SEEK_FOR_CUES

/**
 * The extractors factory for the app player. One place, so the flag above
 * is the same object the player and the test both drive — [PlaybackService]
 * hands it to its media source factory at player build time.
 */
fun buildPlayerExtractorsFactory(): DefaultExtractorsFactory =
    DefaultExtractorsFactory()
        .setMatroskaExtractorFlags(playerMatroskaExtractorFlags)
