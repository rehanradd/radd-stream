package com.raddstream.app.data.cache

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class HlsPlaylistTest {

    private val media = """
        #EXTM3U
        #EXT-X-TARGETDURATION:10
        #EXT-X-MEDIA-SEQUENCE:0
        #EXTINF:6.006,
        https://cdn.example/seg0.ts?token=A
        #EXTINF:6.006,
        https://cdn.example/seg1.ts?token=A
        #EXTINF:4.000,
        https://cdn.example/seg2.ts?token=A
        #EXT-X-ENDLIST
    """.trimIndent()

    @Test
    fun `parse reads segments in order with durations and original urls`() {
        val segs = HlsPlaylist.parseSegments(media)
        assertEquals(3, segs.size)
        assertEquals(0, segs[0].index)
        assertEquals("https://cdn.example/seg0.ts?token=A", segs[0].uri)
        assertEquals(6.006, segs[0].durationSeconds, 0.0001)
        assertEquals(4.0, segs[2].durationSeconds, 0.0001)
    }

    @Test
    fun `master playlist is detected and yields no media segments`() {
        val master = """
            #EXTM3U
            #EXT-X-STREAM-INF:BANDWIDTH=1280000,RESOLUTION=720x480
            http://example/low.m3u8
            #EXT-X-STREAM-INF:BANDWIDTH=2560000,RESOLUTION=1280x720
            http://example/hi.m3u8
        """.trimIndent()
        assertTrue(HlsPlaylist.isMaster(master))
        assertFalse(HlsPlaylist.isMaster(media))
    }

    @Test
    fun `covered duration sums only fetched segments`() {
        val segs = HlsPlaylist.parseSegments(media)
        assertEquals(12.012, HlsPlaylist.coveredDuration(segs, setOf(0, 1)), 0.001)
        assertEquals(0.0, HlsPlaylist.coveredDuration(segs, emptySet()), 0.001)
    }

    @Test
    fun `rewriteLocal points covered segments at local files and keeps remote for the rest`() {
        val segs = HlsPlaylist.parseSegments(media)
        val covered = setOf(0, 1) // seg2 not yet fetched
        val out = HlsPlaylist.rewriteLocal(
            segments = segs,
            coveredIndices = covered,
            localSegmentPath = { s -> "cache://seg${s.index}.ts" },
        )
        assertTrue(out.startsWith("#EXTM3U"))
        assertTrue(out.contains("cache://seg0.ts"))
        assertTrue(out.contains("cache://seg1.ts"))
        // seg2 still resolves to the remote URL
        assertTrue(out.contains("https://cdn.example/seg2.ts?token=A"))
        assertTrue(out.contains("#EXT-X-ENDLIST"))
        assertFalse(out.contains("cache://seg2.ts"))
        // it is a valid media playlist again (has TARGETDURATION + SEQUENCE)
        assertTrue(out.contains("#EXT-X-TARGETDURATION:"))
        assertTrue(out.contains("#EXT-X-MEDIA-SEQUENCE:0"))
    }

    @Test
    fun `rewriteLocal segment count matches source`() {
        val segs = HlsPlaylist.parseSegments(media)
        val out = HlsPlaylist.rewriteLocal(segs, segs.map { it.index }.toSet(), localSegmentPath = { "local/${it.index}" })
        // three EXTINF lines remain
        assertEquals(3, out.split("#EXTINF").size - 1)
    }

    @Test
    fun `target duration is rounded up from the longest segment`() {
        val segs = HlsPlaylist.parseSegments(media)
        val out = HlsPlaylist.rewriteLocal(segs, emptySet(), localSegmentPath = { it.uri })
        assertTrue(out.contains("#EXT-X-TARGETDURATION:7")) // ceil(6.006)
    }
}
