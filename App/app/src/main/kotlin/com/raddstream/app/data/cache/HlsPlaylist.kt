package com.raddstream.app.data.cache

/**
 * Pure HLS (`.m3u8`) parsing and local rewriting used by the ahead-of-playback fetcher.
 *
 * The progressive fetcher for `accepts_ranges=1` direct files works on byte ranges; for an
 * `hls_manifest` source (`cat_links.kind = 'hls_manifest'`) the unit of work is a media
 * segment, so the byte ledger's sibling here is a *segment* coverage set. We download
 * segments ahead of the playhead and then emit a local playlist that Media3 can open offline
 * for everything already fetched — the same "play AND keep downloading" contract, expressed
 * in segments.
 *
 * No networking and no Android here: parsing and rewriting are pure so they are unit-tested;
 * [HlsAheadBuffer] (Android source set) does the fetching around these functions.
 */
data class HlsSegment(
    val index: Int,
    val uri: String,
    val durationSeconds: Double,
)

object HlsPlaylist {

    /** True for a master playlist (it points at variants, not media segments). */
    fun isMaster(text: String): Boolean =
        text.lineSequence().any { it.trim().startsWith("#EXT-X-STREAM-INF") }

    /**
     * Extract the ordered media segments from a media playlist. EXTINF duration is read;
     * key/byte-range tags are preserved verbatim in [rewriteLocal] so DRM-less AES-128
     * playlists still resolve. Lines that are comments/tags are ignored for segmentation but
     * retained where needed.
     */
    fun parseSegments(text: String): List<HlsSegment> {
        val out = ArrayList<HlsSegment>()
        var pendingDuration: Double? = null
        var index = 0
        for (raw in text.lineSequence()) {
            val line = raw.trim()
            when {
                line.isEmpty() -> { /* skip blank */ }
                line.startsWith("#EXTINF") -> pendingDuration = parseExtInfDuration(line)
                line.startsWith("#") -> { /* other tags: not a segment */ }
                else -> {
                    val dur = pendingDuration ?: 0.0
                    out.add(HlsSegment(index, line, dur))
                    index++
                    pendingDuration = null
                }
            }
        }
        return out
    }

    private fun parseExtInfDuration(line: String): Double {
        // "#EXTINF:6.006000,Title" or "#EXTINF:6.006,"
        val afterColon = line.substringAfter(":")
        val numberPart = afterColon.substringBefore(",").trim()
        return numberPart.toDoubleOrNull() ?: 0.0
    }

    /** Total playtime of the segments we currently hold locally. */
    fun coveredDuration(segments: List<HlsSegment>, coveredIndices: Set<Int>): Double =
        segments.filter { it.index in coveredIndices }.sumOf { it.durationSeconds }

    /**
     * Produce a locally-playable media playlist: covered segments point at [localSegmentPath]
     * (a file already on disk); uncovered segments keep their original URI so a hybrid
     * online/offline playback works while the fetcher catches up. Preserves the `#EXTM3U`
     * header and any leading `#EXT-X-*` tags, and always emits `#EXT-X-ENDLIST`.
     *
     * @param targetDurationSeconds the `#EXT-X-TARGETDURATION` value; derived when null.
     */
    fun rewriteLocal(
        segments: List<HlsSegment>,
        coveredIndices: Set<Int>,
        localSegmentPath: (HlsSegment) -> String,
        originalHeaderText: String = "#EXTM3U",
        mediaSequence: Int = 0,
        targetDurationSeconds: Double? = null,
    ): String {
        val sb = StringBuilder()
        // Preserve caller-supplied header lines except a trailing ENDLIST we will re-add.
        for (l in originalHeaderText.lineSequence()) {
            val t = l.trim()
            if (t.isEmpty() || t == "#EXT-X-ENDLIST") continue
            if (t == "#EXTM3U") { sb.append("#EXTM3U\n"); continue }
            if (t.startsWith("#EXT-X-TARGETDURATION:") || t.startsWith("#EXT-X-MEDIA-SEQUENCE:")) continue
            if (t.startsWith("#")) sb.append(t).append('\n')
        }
        val maxDur = (targetDurationSeconds
            ?: segments.maxOfOrNull { it.durationSeconds }
            ?: 0.0).let { if (it < 1.0) 1.0 else kotlin.math.ceil(it) }
        sb.append("#EXT-X-TARGETDURATION:").append(maxDur.toLong()).append('\n')
        sb.append("#EXT-X-MEDIA-SEQUENCE:").append(mediaSequence).append('\n')
        for (seg in segments) {
            sb.append("#EXTINF:").append(fmt(seg.durationSeconds)).append(",\n")
            val path = if (seg.index in coveredIndices) localSegmentPath(seg) else seg.uri
            sb.append(path).append('\n')
        }
        sb.append("#EXT-X-ENDLIST\n")
        return sb.toString()
    }

    private fun fmt(seconds: Double): String {
        val r = kotlin.math.round(seconds * 1000.0) / 1000.0
        return if (r == r.toLong().toDouble()) r.toLong().toString() else r.toString()
    }
}
