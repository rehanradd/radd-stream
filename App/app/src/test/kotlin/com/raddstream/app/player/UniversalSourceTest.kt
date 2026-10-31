package com.raddstream.app.player

import androidx.media3.common.MimeTypes
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * The one player has to build the *right MediaSource* for every protocol the resolver can name,
 * and at Media3 1.3.1 that choice is made from the `MediaItem`'s declared mime type or the URI's
 * path extension — never from the bytes. A playback address here is
 * `<server>/api/v1/stream?id=<handle>`, which has no extension, so an HLS or DASH link that is not
 * declared is handed to the progressive source and dies on `#EXTM3U` before the first frame.
 *
 * [PlaybackMediaItemFactory.manifestMimeType] is the pure rule that fixes that; these cases drive
 * it directly because building an actual `MediaItem` needs `android.net.Uri`, which this host
 * cannot supply (Robolectric has no aarch64 runtime — see `App/AGENTS.md` §1a).
 */
class UniversalSourceTest {

    private fun playback(
        protocol: String? = null,
        mimeType: String? = null,
        url: String? = "http://92.4.95.252/api/v1/stream?id=abc123",
    ) = PlaybackInfo(protocol = protocol, mimeType = mimeType, playUrl = url)

    // ── HLS: the three ways the wire can say it ──────────────────────────────────

    @Test
    fun `the wire protocol word alone routes an extensionless redirector to HLS`() {
        assertEquals(
            MimeTypes.APPLICATION_M3U8,
            PlaybackMediaItemFactory.manifestMimeType(playback(protocol = "hls")),
        )
    }

    @Test
    fun `an m3u8 in the address routes to HLS with no protocol word`() {
        assertEquals(
            MimeTypes.APPLICATION_M3U8,
            PlaybackMediaItemFactory.manifestMimeType(
                playback(url = "http://92.4.95.252/api/v1/stream?id=abc&file=master.m3u8"),
            ),
        )
    }

    @Test
    fun `the apple mime spellings route to HLS`() {
        listOf(
            "application/vnd.apple.mpegurl",
            "application/x-mpegURL",
            "APPLICATION/X-MPEGURL ",
        ).forEach { mime ->
            assertEquals(
                MimeTypes.APPLICATION_M3U8,
                PlaybackMediaItemFactory.manifestMimeType(playback(mimeType = mime)),
            )
        }
    }

    // ── DASH ─────────────────────────────────────────────────────────────────────

    @Test
    fun `a dash link is declared as an MPD manifest`() {
        assertEquals(
            MimeTypes.APPLICATION_MPD,
            PlaybackMediaItemFactory.manifestMimeType(playback(protocol = "dash")),
        )
        assertEquals(
            MimeTypes.APPLICATION_MPD,
            PlaybackMediaItemFactory.manifestMimeType(
                playback(url = "http://92.4.95.252/api/v1/stream?id=abc&p=stream.mpd"),
            ),
        )
        assertEquals(
            MimeTypes.APPLICATION_MPD,
            PlaybackMediaItemFactory.manifestMimeType(playback(mimeType = "application/dash+xml")),
        )
    }

    // ── Progressive: declared nothing, sniffed everything ────────────────────────

    @Test
    fun `mp4 and mkv stay undeclared so the extractors sniff them`() {
        listOf("mp4", "mkv", "avi", "mov", "ts").forEach { container ->
            assertNull(
                "$container is a container, not a manifest: a declared mime would override " +
                    "the sniffing that already recognises it",
                PlaybackMediaItemFactory.manifestMimeType(
                    playback(protocol = "progressive", mimeType = "video/$container"),
                ),
            )
        }
    }

    @Test
    fun `a coarse progressive word does not outrank manifest evidence`() {
        // Measured against `catalog_v2.py::_protocol_of()`: it writes "progressive" for any link
        // whose playability is stream/download/both and has no dash branch, so a manifest can
        // arrive wearing that word. The mime and the extension are the better evidence.
        assertEquals(
            MimeTypes.APPLICATION_M3U8,
            PlaybackMediaItemFactory.manifestMimeType(
                playback(protocol = "progressive", mimeType = "application/vnd.apple.mpegurl"),
            ),
        )
        assertEquals(
            MimeTypes.APPLICATION_MPD,
            PlaybackMediaItemFactory.manifestMimeType(
                playback(protocol = "progressive", url = "http://92.4.95.252/api/v1/stream?id=abc&mpd=manifest.mpd"),
            ),
        )
    }

    @Test
    fun `an extensionless progressive redirector with no mime stays sniffed`() {
        assertNull(PlaybackMediaItemFactory.manifestMimeType(playback(protocol = "progressive")))
        assertNull(PlaybackMediaItemFactory.manifestMimeType(playback()))
    }

    @Test
    fun `a mislabelled or unknown protocol is never guessed into a manifest source`() {
        listOf("html", "rtmp", "", "weird").forEach { protocol ->
            assertNull(
                "only the two manifest protocols may be declared; anything else keeps the " +
                    "progressive path it already worked on",
                PlaybackMediaItemFactory.manifestMimeType(playback(protocol = protocol)),
            )
        }
    }

    @Test
    fun `a null protocol and mime with a null address declares nothing`() {
        assertNull(PlaybackMediaItemFactory.manifestMimeType(PlaybackInfo()))
    }

    // ── The Media3 contract this rule leans on ───────────────────────────────────

    @Test
    fun `the declared strings are exactly the ones the Media3 matcher recognises`() {
        // `Util.inferContentTypeForUriAndMimeType` compares the declared mime against these two
        // literals and falls through to CONTENT_TYPE_OTHER for anything else. A "more accurate"
        // spelling here would therefore re-introduce the failure this function exists to remove.
        assertEquals("application/x-mpegURL", MimeTypes.APPLICATION_M3U8)
        assertEquals("application/dash+xml", MimeTypes.APPLICATION_MPD)
    }

    @Test
    fun `a kept hls copy served by the local proxy is still declared as a manifest`() {
        // The player swaps the address for the loopback proxy's own `local.m3u8` and keeps the
        // rendition's protocol, so offline playback must not silently become progressive.
        assertEquals(
            MimeTypes.APPLICATION_M3U8,
            PlaybackMediaItemFactory.manifestMimeType(
                playback(
                    protocol = "hls",
                    url = "http://127.0.0.1:41001/sessions/abc123/local.m3u8",
                ),
            ),
        )
    }
}
