package com.raddstream.app.player

import androidx.media3.common.MimeTypes
import androidx.media3.common.util.UnstableApi
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Robo #4 (APK 504): both Live TV channels failed with
 * `UnrecognizedInputFormatException` through the progressive reader, while
 * the server served valid HLS playlists for both. The bare-handle bundle
 * ([PlaybackBundle.forStreamHandle]) had no way to know the bytes were a
 * manifest: the redirector URL carries no `.m3u8` and no MIME. The Live TV
 * tap now stages the manifest MIME ([PlayerSessionStore.stageManifestMime])
 * and [PlayerViewModel.startStreamHandle] hands it to the bundle — this is
 * the truth table for that handoff, plus the no-regression half: a bare
 * handle with no staged entry still builds progressive.
 */
@OptIn(UnstableApi::class)
class LiveTvHlsDeclareTest {

    private val handle = "/api/v1/stream?id=abc123"
    private val playUrl = "https://raddstream.duckdns.org$handle"

    @Test
    fun liveTvHandleDeclaresHls() {
        val bundle = PlaybackBundle.forStreamHandle(
            streamId = "abc123",
            playUrl = playUrl,
            title = "Aastha Gujarati",
            mimeType = MimeTypes.APPLICATION_M3U8,
        )
        val playback = bundle.renditions.first().playback
        assertTrue(playback.isHls())
        assertEquals("hls", playback.protocol)
        assertEquals(
            MimeTypes.APPLICATION_M3U8,
            PlaybackMediaItemFactory.manifestMimeType(playback),
        )
    }

    @Test
    fun stagedHlsMimeSurvivesTheAliasSpelling() {
        // The tap stages the Media3 constant; the vendor spelling a CDN
        // answers must reach the same declaration through the factory's
        // normalisation, or the fix depends on who wrote the MIME.
        val bundle = PlaybackBundle.forStreamHandle(
            streamId = "abc123",
            playUrl = playUrl,
            title = "Aaseervatham TV",
            mimeType = "application/vnd.apple.mpegurl",
        )
        val playback = bundle.renditions.first().playback
        assertTrue(playback.isHls())
        assertEquals(
            MimeTypes.APPLICATION_M3U8,
            PlaybackMediaItemFactory.manifestMimeType(playback),
        )
    }

    @Test
    fun bareHandleStaysProgressive() {
        val bundle = PlaybackBundle.forStreamHandle(
            streamId = "abc123",
            playUrl = playUrl,
            title = "Some Movie",
        )
        val playback = bundle.renditions.first().playback
        assertFalse(playback.isHls())
        assertEquals("progressive", playback.protocol)
        assertNull(PlaybackMediaItemFactory.manifestMimeType(playback))
    }

    @Test
    fun stagedMimeReadsBackUnderItsHandle() {
        val store = PlayerSessionStore()
        store.stageManifestMime("abc123", MimeTypes.APPLICATION_M3U8)
        assertEquals(MimeTypes.APPLICATION_M3U8, store.peekManifestMime("abc123"))
    }

    @Test
    fun peekDoesNotConsume() {
        val store = PlayerSessionStore()
        store.stageManifestMime("abc123", MimeTypes.APPLICATION_M3U8)
        store.peekManifestMime("abc123")
        assertEquals(MimeTypes.APPLICATION_M3U8, store.peekManifestMime("abc123"))
    }

    @Test
    fun blankHandleOrMimeStagesNothing() {
        val store = PlayerSessionStore()
        store.stageManifestMime("", MimeTypes.APPLICATION_M3U8)
        store.stageManifestMime("abc123", "   ")
        assertNull(store.peekManifestMime(""))
        assertNull(store.peekManifestMime("abc123"))
    }

    @Test
    fun unknownHandleReadsNull() {
        val store = PlayerSessionStore()
        assertNull(store.peekManifestMime("nope"))
    }
}
