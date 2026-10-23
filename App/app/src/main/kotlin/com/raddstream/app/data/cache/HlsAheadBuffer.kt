package com.raddstream.app.data.cache

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.IOException
import kotlin.coroutines.coroutineContext

/**
 * Segment-level ahead-of-playback buffer for `hls_manifest` sources (`cat_links.kind =
 * 'hls_manifest'`). Downloads media segments ahead of the playhead, then emits a local `.m3u8`
 * that Media3 can open: covered segments resolve to files already on disk, uncovered ones still
 * resolve to their remote URL so a hybrid online/offline playback works while we catch up.
 *
 * Mirrors [AheadFetcher]'s guarantees at the segment grain: never re-download a segment we
 * already hold (a covered segment is simply left in place and marked), an ephemeral manifest
 * that dies keeps every downloaded segment and asks to re-resolve, and every file lives in the
 * app's private directory (app-only playback).
 */
class HlsAheadBuffer(
    private val client: OkHttpClient,
    private val clock: UptimeClock,
) {

    data class Result(
        val segments: List<HlsSegment>,
        val coveredIndices: Set<Int>,
        val localPlaylist: File?,
        val sourceDead: Boolean,
        val error: String?,
    ) {
        val isComplete: Boolean get() = segments.isNotEmpty() && coveredIndices.size == segments.size
    }

    /**
     * @param workDir private directory holding this resource's segments + `local.m3u8`.
     * @param startSegmentIndex playhead segment; we buffer from here forward.
     * @param aheadSegments how many segments to keep ahead of the playhead.
     */
    suspend fun run(
        manifestUrl: String,
        workDir: File,
        startSegmentIndex: Int,
        aheadSegments: Int,
    ): Result = withContext(Dispatchers.IO) {
        if (!workDir.exists()) workDir.mkdirs()
        val mediaText = loadMediaPlaylist(manifestUrl)
            ?: return@withContext Result(emptyList(), emptySet(), null, sourceDead = true, error = "manifest_unreachable")

        val segments = HlsPlaylist.parseSegments(mediaText)
        if (segments.isEmpty()) {
            return@withContext Result(emptyList(), emptySet(), null, sourceDead = false, error = "no_segments")
        }

        val covered = HashSet<Int>()
        var lastError: String? = null
        val upper = minOf(segments.size - 1, startSegmentIndex + aheadSegments)
        for (i in startSegmentIndex..upper) {
            coroutineContext.ensureActive()
            val seg = segments[i]
            val localFile = File(workDir, "seg_${seg.index}.bin")
            if (localFile.exists() && localFile.length() > 0) {
                covered.add(seg.index) // already have it — never re-fetch
                continue
            }
            val url = resolveUrl(manifestUrl, seg.uri)
            when (val outcome = downloadSegment(url, localFile)) {
                SegmentOutcome.Saved -> covered.add(seg.index)
                SegmentOutcome.Dead -> {
                    lastError = "segment_404"
                    break
                }
                SegmentOutcome.Failed -> {
                    lastError = "segment_io"
                    break
                }
                SegmentOutcome.Cancelled -> throw kotlinx.coroutines.CancellationException("cancelled")
            }
        }

        val playlistFile = File(workDir, "local.m3u8")
        val text = HlsPlaylist.rewriteLocal(
            segments = segments,
            coveredIndices = covered,
            localSegmentPath = { s -> File(workDir, "seg_${s.index}.bin").absolutePath },
            originalHeaderText = headerOf(mediaText),
        )
        playlistFile.writeText(text)
        Result(
            segments = segments,
            coveredIndices = covered,
            localPlaylist = playlistFile,
            sourceDead = lastError == "segment_404",
            error = lastError,
        )
    }

    private enum class SegmentOutcome { Saved, Dead, Failed, Cancelled }

    private suspend fun downloadSegment(url: String, dest: File): SegmentOutcome {
        val tmp = File(dest.absolutePath + ".part")
        val request = Request.Builder().url(url).build()
        var response: okhttp3.Response? = null
        try {
            response = client.newCall(request).execute()
            if (response.code == 403 || response.code == 404 || response.code == 410) {
                return SegmentOutcome.Dead
            }
            if (!response.isSuccessful) return SegmentOutcome.Failed
            val input = response.body?.byteStream() ?: return SegmentOutcome.Failed
            tmp.outputStream().use { out ->
                val buf = ByteArray(RangeByteFetcher.CHUNK_BYTES)
                while (true) {
                    coroutineContext.ensureActive()
                    val n = input.read(buf)
                    if (n == -1) break
                    out.write(buf, 0, n)
                }
            }
            return if (tmp.renameTo(dest)) SegmentOutcome.Saved else SegmentOutcome.Failed
        } catch (ce: kotlinx.coroutines.CancellationException) {
            throw ce
        } catch (io: IOException) {
            return SegmentOutcome.Failed
        } finally {
            try {
                response?.close()
            } catch (_: IOException) {
            }
            if (tmp.exists() && !dest.exists()) tmp.delete()
        }
    }

    /** Fetch a media playlist; if the URL is a master, descend to the highest-bandwidth variant. */
    private suspend fun loadMediaPlaylist(url: String): String? {
        val first = fetchText(url) ?: return null
        if (!HlsPlaylist.isMaster(first)) return first
        val variant = pickVariantUrl(first, url) ?: return first
        return fetchText(variant) ?: first
    }

    private fun pickVariantUrl(master: String, masterUrl: String): String? {
        val lines = master.lines()
        var last: String? = null
        for (i in lines.indices) {
            if (lines[i].trim().startsWith("#EXT-X-STREAM-INF")) {
                val next = lines.getOrNull(i + 1)?.trim().orEmpty()
                if (next.isNotEmpty() && !next.startsWith("#")) last = next
            }
        }
        return last?.let { resolveUrl(masterUrl, it) }
    }

    private suspend fun fetchText(url: String): String? {
        val request = Request.Builder().url(url).build()
        var response: okhttp3.Response? = null
        return try {
            response = client.newCall(request).execute()
            if (response.isSuccessful) response.body?.string() else null
        } catch (_: IOException) {
            null
        } finally {
            try {
                response?.close()
            } catch (_: IOException) {
            }
        }
    }

    /** Keep the leading tag block of the original media playlist (EXTM3U + session tags). */
    private fun headerOf(text: String): String =
        text.lineSequence().takeWhile { it.startsWith("#") }.joinToString("\n").ifBlank { "#EXTM3U" }

    companion object {
        /**
         * Resolve a possibly-relative segment/variant URI against the manifest URL. Prefers
         * [java.net.URI] resolution (handles absolute-path and relative references correctly
         * against the full manifest URL), and falls back to a manual join if the manifest URL
         * is itself not a strict URI.
         */
        fun resolveUrl(manifestUrl: String, ref: String): String {
            if (ref.startsWith("http://") || ref.startsWith("https://")) return ref
            return try {
                java.net.URI(manifestUrl).resolve(ref).toString()
            } catch (_: Exception) {
                val dir = manifestUrl.substringBeforeLast('/', "")
                if (ref.startsWith("/")) {
                    val schemeHost = manifestUrl.substringBefore("//").ifEmpty { "https:" } +
                        "//" + manifestUrl.substringAfter("//").substringBefore("/")
                    "$schemeHost$ref"
                } else {
                    "$dir/$ref"
                }
            }
        }
    }
}
