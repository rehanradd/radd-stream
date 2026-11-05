package com.raddstream.app.data.cache

import java.io.File
import java.nio.file.Files
import kotlinx.coroutines.runBlocking
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The full-download contract for HLS keeps (P0 download fix, 2026-11-06): one pass with
 * an unbounded window must cover a whole playlist — the old 20-segment window from a
 * never-moving playhead re-covered segments 0..20 forever and never reached segment 21.
 * Segments also resolve against the playlist they actually came from, not the redirector
 * address we asked for, because our redirector 302s to the playlist host.
 *
 * The HTTP layer is an OkHttp application interceptor answering from memory — no socket,
 * no MockWebServer — following the AheadFetcherFinalizeTest pattern.
 */
class HlsAheadBufferTest {

    private val segmentBytes = ByteArray(1024) { (it % 251).toByte() }

    private fun mediaPlaylist(segmentCount: Int, segmentUri: (Int) -> String): String {
        val sb = StringBuilder("#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXT-X-MEDIA-SEQUENCE:0\n")
        for (i in 0 until segmentCount) {
            sb.append("#EXTINF:6.0,\n").append(segmentUri(i)).append('\n')
        }
        sb.append("#EXT-X-ENDLIST\n")
        return sb.toString()
    }

    /** Interceptor serving fixed playlist bodies and segment bytes, recording every URL. */
    private inner class ScriptedClient(
        private val playlists: Map<String, String>,
        /** The URL the playlist body actually came from (after a redirect), per asked URL. */
        private val finalUrlFor: Map<String, String> = emptyMap(),
    ) {
        val requestedUrls = ArrayList<String>()

        val client: OkHttpClient = OkHttpClient.Builder()
            .addInterceptor { chain ->
                val request = chain.request()
                val url = request.url.toString()
                requestedUrls.add(url)
                val playlist = playlists[url]
                if (playlist != null) {
                    val finalUrl = finalUrlFor[url] ?: url
                    Response.Builder()
                        .request(request.newBuilder().url(finalUrl).build())
                        .protocol(Protocol.HTTP_1_1).code(200).message("OK")
                        .body(playlist.toResponseBody("application/vnd.apple.mpegurl".toMediaType()))
                        .build()
                } else if (url.endsWith(".ts")) {
                    Response.Builder()
                        .request(request).protocol(Protocol.HTTP_1_1)
                        .code(200).message("OK")
                        .body(segmentBytes.toResponseBody("video/mp2t".toMediaType()))
                        .build()
                } else {
                    Response.Builder()
                        .request(request).protocol(Protocol.HTTP_1_1)
                        .code(404).message("Not Found")
                        .body("".toResponseBody("text/plain".toMediaType()))
                        .build()
                }
            }.build()
    }

    private fun newWorkDir(): File =
        Files.createTempDirectory("hls-ahead-test").toFile().also { it.deleteOnExit() }

    private fun buffer(scripted: ScriptedClient) =
        HlsAheadBuffer(scripted.client, FixedUptimeClock())

    @Test
    fun `full download covers a 50-segment playlist in one pass`() = runBlocking {
        val manifestUrl = "https://radd.test/api/v1/stream?id=H"
        val playlist = mediaPlaylist(50) { i -> "https://cdn.example/seg$i.ts" }
        val scripted = ScriptedClient(mapOf(manifestUrl to playlist))
        val workDir = newWorkDir()

        val result = buffer(scripted).run(manifestUrl, workDir, startSegmentIndex = 0, aheadSegments = Int.MAX_VALUE)

        assertTrue(result.isComplete)
        assertEquals(50, result.coveredIndices.size)
        assertEquals(50, result.segments.size)
        val local = File(workDir, "local.m3u8")
        assertTrue(local.exists())
        assertEquals(50, scripted.requestedUrls.count { it.endsWith(".ts") })
        for (i in 0 until 50) assertTrue(File(workDir, "seg_$i.bin").exists())
    }

    @Test
    fun `preview window still takes only 20 ahead`() = runBlocking {
        val manifestUrl = "https://radd.test/api/v1/stream?id=H"
        val playlist = mediaPlaylist(50) { i -> "https://cdn.example/seg$i.ts" }
        val scripted = ScriptedClient(mapOf(manifestUrl to playlist))
        val workDir = newWorkDir()

        val result = buffer(scripted).run(manifestUrl, workDir, startSegmentIndex = 0, aheadSegments = 20)

        assertFalse(result.isComplete)
        assertEquals(21, result.coveredIndices.size)
        assertEquals(21, scripted.requestedUrls.count { it.endsWith(".ts") })
    }

    @Test
    fun `relative segments resolve against the final playlist url`() = runBlocking {
        val manifestUrl = "https://radd.test/api/v1/stream?id=H"
        val finalUrl = "https://cdn.example.com/v/abc/media.m3u8"
        val playlist = mediaPlaylist(5) { i -> "seg$i.ts" }
        val scripted = ScriptedClient(
            playlists = mapOf(manifestUrl to playlist),
            finalUrlFor = mapOf(manifestUrl to finalUrl),
        )
        val workDir = newWorkDir()

        val result = buffer(scripted).run(manifestUrl, workDir, startSegmentIndex = 0, aheadSegments = Int.MAX_VALUE)

        assertTrue(result.isComplete)
        val segmentUrls = scripted.requestedUrls.filter { it.endsWith(".ts") }
        assertEquals(5, segmentUrls.size)
        assertTrue(segmentUrls.all { it.startsWith("https://cdn.example.com/v/abc/seg") })
    }

    @Test
    fun `master descends to the variant and resolves its relative segments`() = runBlocking {
        val manifestUrl = "https://radd.test/api/v1/stream?id=H"
        val masterFinal = "https://cdn.example.com/hls/master.m3u8"
        val master = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=2560000,RESOLUTION=1280x720\nv1080.m3u8\n"
        val variantUrl = "https://cdn.example.com/hls/v1080.m3u8"
        val variant = mediaPlaylist(4) { i -> "seg$i.ts" }
        val scripted = ScriptedClient(
            playlists = mapOf(manifestUrl to master, variantUrl to variant),
            finalUrlFor = mapOf(manifestUrl to masterFinal),
        )
        val workDir = newWorkDir()

        val result = buffer(scripted).run(manifestUrl, workDir, startSegmentIndex = 0, aheadSegments = Int.MAX_VALUE)

        assertTrue(result.isComplete)
        assertTrue(scripted.requestedUrls.contains(variantUrl))
        val segmentUrls = scripted.requestedUrls.filter { it.endsWith(".ts") }
        assertEquals(4, segmentUrls.size)
        assertTrue(segmentUrls.all { it.startsWith("https://cdn.example.com/hls/seg") })
    }

    @Test
    fun `a second pass never re-fetches held segments`() = runBlocking {
        val manifestUrl = "https://radd.test/api/v1/stream?id=H"
        val playlist = mediaPlaylist(30) { i -> "https://cdn.example/seg$i.ts" }
        val scripted = ScriptedClient(mapOf(manifestUrl to playlist))
        val workDir = newWorkDir()
        val buf = buffer(scripted)

        val first = buf.run(manifestUrl, workDir, startSegmentIndex = 0, aheadSegments = Int.MAX_VALUE)
        assertTrue(first.isComplete)
        scripted.requestedUrls.clear()

        val second = buf.run(manifestUrl, workDir, startSegmentIndex = 0, aheadSegments = Int.MAX_VALUE)
        assertTrue(second.isComplete)
        assertEquals(0, scripted.requestedUrls.count { it.endsWith(".ts") })
    }
}
