package com.raddstream.app.network.models

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Audit Top-20 #1 — the client half: a manifest must reach Media3 as the manifest it is.
 *
 * `playUrl` is always our own `/api/v1/stream?id=<handle>` redirector, so the address can
 * never name the medium and Media3's extension inference has nothing to read. Two facts can
 * break the tie, in this order of trust: the protocol the server RECORDED (which, after the
 * backend half of this fix, comes from the probe that sniffed `#EXTM3U`/MPEG-DASH off the
 * bytes), and the measured `mime_type` the probe stored. A declared `progressive` contradicted
 * by a manifest MIME is the `UnrecognizedInputFormatException` this suite exists to prevent —
 * and `.mpd` is DASH, never a spelling of HLS.
 */
class ManifestProtocolTest {

    private val redirector = "http://92.4.95.252/api/v1/stream?id=lh-1"

    private fun link(
        protocol: String? = null,
        mimeType: String? = null,
        kind: String? = null,
        playability: String? = "stream",
        playUrl: String = redirector,
    ) = SourceDetail(
        streamId = "lh-1",
        playUrl = playUrl,
        kind = kind,
        playability = playability,
        protocol = protocol,
        mimeType = mimeType,
        status = "active",
    )

    @Test
    fun `a measured hls mime outranks a declared progressive`() {
        val a = LinkClassification.classify(
            link(protocol = "progressive", mimeType = "application/vnd.apple.mpegurl"),
        )
        assertEquals(PlayProtocol.HLS, a.protocol)
    }

    @Test
    fun `a measured dash mime outranks a declared progressive`() {
        val a = LinkClassification.classify(
            link(protocol = "progressive", mimeType = "application/dash+xml"),
        )
        assertEquals(PlayProtocol.DASH, a.protocol)
    }

    @Test
    fun `an absent protocol with no mime still falls to the projection rule`() {
        val a = LinkClassification.classify(link(kind = "dash_manifest"))
        assertEquals(LinkKind.DASH_MANIFEST, a.kind)
        assertEquals(PlayProtocol.DASH, a.protocol)
        val file = LinkClassification.classify(link(kind = "direct"))
        assertEquals(PlayProtocol.PROGRESSIVE, file.protocol)
    }

    @Test
    fun `a recorded manifest protocol survives a file-shaped claim`() {
        val a = LinkClassification.classify(link(protocol = "dash", mimeType = "video/mp4"))
        assertEquals(PlayProtocol.DASH, a.protocol)
    }

    @Test
    fun `mpd is dash and never hls`() {
        assertTrue(LinkClassification.isDash(null, "https://cdn.test/x/manifest.mpd"))
        assertFalse(LinkClassification.isHls(null, "https://cdn.test/x/manifest.mpd"))
        val a = LinkClassification.classify(
            link(protocol = "progressive", playUrl = "https://cdn.test/x/manifest.mpd"),
        )
        assertEquals(PlayProtocol.DASH, a.protocol)
    }

    @Test
    fun `protocolOf mirrors the projection including its dash branch`() {
        assertEquals(PlayProtocol.DASH, LinkClassification.protocolOf(LinkKind.DASH_MANIFEST, Playability.STREAM))
        assertEquals(PlayProtocol.HLS, LinkClassification.protocolOf(LinkKind.HLS_MANIFEST, Playability.STREAM))
        assertEquals(PlayProtocol.PROGRESSIVE, LinkClassification.protocolOf(LinkKind.CDN_DIRECT, Playability.BOTH))
    }
}
