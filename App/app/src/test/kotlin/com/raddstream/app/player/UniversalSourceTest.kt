package com.raddstream.app.player

import androidx.media3.common.MimeTypes
import androidx.media3.common.util.UnstableApi
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Every address this app plays is our own redirector — `/api/v1/stream?id=<handle>` — which has
 * no file extension, and the redirect happens after Media3 has already chosen which reader will
 * interpret the bytes. So the one piece of knowledge that decides whether a link plays at all
 * (manifest or file) has to travel with the link instead of being guessed from an address that
 * cannot carry it.
 *
 * [PlaybackMediaItemFactory.manifestMimeType] is where that guess becomes a declaration, and this
 * is the whole truth table for it: HLS, DASH, and everything else left to the readers that sniff
 * bytes themselves.
 */
@OptIn(UnstableApi::class)
class UniversalSourceTest {

    private fun playback(
        url: String?,
        protocol: String? = null,
        mimeType: String? = null,
    ) = PlaybackInfo(playUrl = url, protocol = protocol, mimeType = mimeType)

    @Test
    fun hlsIsDeclaredFromEitherHalfOfTheEvidence() {
        val expected = MimeTypes.APPLICATION_M3U8
        // The server's own word about the protocol.
        assertEquals(expected, PlaybackMediaItemFactory.manifestMimeType(playback(HANDLE, protocol = "hls")))
        assertEquals(expected, PlaybackMediaItemFactory.manifestMimeType(playback(HANDLE, protocol = "HLS")))
        // The address, when the protocol field is missing: a rank can carry one and not the other.
        assertEquals(expected, PlaybackMediaItemFactory.manifestMimeType(playback("$BASE/index.m3u8")))
        // Both halves at once is still one answer, and a contradictory container claim does not
        // outvote the protocol the server recorded for the bytes.
        assertEquals(expected, PlaybackMediaItemFactory.manifestMimeType(playback(HANDLE, protocol = "hls", mimeType = "video/mp4")))
    }

    @Test
    fun dashIsDeclaredTheSameWayHlsIs() {
        val expected = MimeTypes.APPLICATION_MPD
        assertEquals(expected, PlaybackMediaItemFactory.manifestMimeType(playback(HANDLE, protocol = "dash")))
        assertEquals(expected, PlaybackMediaItemFactory.manifestMimeType(playback("$BASE/manifest.mpd")))
        assertEquals(expected, PlaybackMediaItemFactory.manifestMimeType(playback(HANDLE, protocol = "DASH", mimeType = "application/mpd")))
    }

    /**
     * The point of normalising rather than forwarding: the stored MIME type is whatever the CDN
     * answered, and Media3 matches content types on exact text. An alias it does not know is the
     * silent progressive reader again — the failure this whole function exists to prevent.
     */
    @Test
    fun aWireSpellingMedia3DoesNotKnowIsRewrittenToOneItDoes() {
        val hlsAliases = listOf(
            "application/vnd.apple.mpegurl",
            "APPLICATION/VND.APPLE.MPEGURL",
            "application/vnd.mpegurl",
            "application/mpegurl",
            "audio/mpegurl",
            "application/x-mpegURL",
            "application/vnd.apple.mpegurl; charset=utf-8",
        )
        val dashAliases = listOf("application/dash+xml", "application/mpd", "Application/Dash+XML")
        val found = (hlsAliases + dashAliases).map { PlaybackMediaItemFactory.manifestMimeType(playback(HANDLE, mimeType = it)) }
        assertEquals(
            "every alias in the owner's set must reach a Media3 constant: $found",
            hlsAliases.map { MimeTypes.APPLICATION_M3U8 } + dashAliases.map { MimeTypes.APPLICATION_MPD },
            found,
        )
        // The rewritten value is the constant, not the caller's text: that is the whole
        // normalisation, and it is what an exact-match inference table can act on.
        assertTrue(
            "the answer is one of the two constants Media3 dispatches on, never an invented type",
            found.all { it == MimeTypes.APPLICATION_M3U8 || it == MimeTypes.APPLICATION_MPD },
        )
    }

    @Test
    fun progressiveFilesAreLeftToTheReadersThatSniff() {
        // Declaring a container here would be a second guess at something the bytes answer
        // better: the progressive extractors read the box structure, so an extensionless
        // address costs them nothing.
        listOf("video/mp4", "video/x-matroska", "video/webm", "video/quicktime", null).forEach { mime ->
            assertNull(
                "a progressive link must not have its container dictated: $mime",
                PlaybackMediaItemFactory.manifestMimeType(playback(HANDLE, protocol = "progressive", mimeType = mime)),
            )
        }
        assertNull(PlaybackMediaItemFactory.manifestMimeType(playback("$BASE/movie.mkv", mimeType = "video/x-matroska")))
        assertNull(PlaybackMediaItemFactory.manifestMimeType(playback(null, protocol = null, mimeType = null)))
    }

    @Test
    fun aTypeNobodyNamedIsNotGuessedAt() {
        assertNull(PlaybackMediaItemFactory.manifestMimeType(playback(HANDLE)))
        assertNull(PlaybackMediaItemFactory.manifestMimeType(playback(HANDLE, mimeType = "application/octet-stream")))
        assertNull(PlaybackMediaItemFactory.manifestMimeType(playback(HANDLE, protocol = "embed")))
        // An alias that merely looks close is not understood, and must not be smuggled through as
        // HLS by a prefix match — that would hand a manifest reader bytes that are not a manifest.
        assertNull(PlaybackMediaItemFactory.manifestMimeType(playback(HANDLE, mimeType = "application/x-mpegurls")))
        assertNull(PlaybackMediaItemFactory.manifestMimeType(playback(HANDLE, mimeType = "video/vnd.mpegurl")))
    }

    /** The declaration has to reach the item, not just exist as a pure answer. */
    @Test
    fun theFactoryBuildsTheTypeIntoTheItemItReturns() {
        val source = File(FACTORY_PATH).readText()
        assertTrue(
            "manifestMimeType must be applied to the builder on the way out, or the inference " +
                "path is unchanged and the fix is a function nobody calls",
            Regex("""manifestMimeType\(rendition\.playback\)\?\.let\s*\{\s*builder\.setMimeType\(it\)""")
                .containsMatchIn(source),
        )
        // toList() is not decoration: walkTopDown() hands back a Sequence, and assertEquals on a
        // Sequence compares an unbounded lazy view to a List and fails on the shape, not the
        // content — which is how this census read as a second composer when there is none.
        val census = File("src/main/kotlin").walkTopDown()
            .filter { it.isFile && it.extension == "kt" }
            .filter { Regex("""MediaItem\.Builder\(\)""").containsMatchIn(it.readText()) }
            .map { it.path }
            .toList()
        assertEquals(
            "a second MediaItem composer is a second answer to what a link contains: $census",
            listOf(FACTORY_PATH),
            census,
        )
    }

    /** The guard needs a guard: the scanner must separate an applied declaration from a stated one. */
    @Test
    fun `the application scan tells a wired declaration from a dead helper`() {
        val applied = "        manifestMimeType(rendition.playback)?.let { builder.setMimeType(it) }"
        val computedAndIgnored = "        val mime = manifestMimeType(rendition.playback)\n" +
            "        builder.setMediaId(\"x\")"
        assertTrue("the real call shape is found", Regex(APPLICATION_PATTERN).containsMatchIn(applied))
        assertTrue("a value computed and never installed is not", !Regex(APPLICATION_PATTERN).containsMatchIn(computedAndIgnored))
    }

    private companion object {
        const val APPLICATION_PATTERN = """manifestMimeType\(rendition\.playback\)\?\.let\s*\{\s*builder\.setMimeType\(it\)"""
        const val BASE = "https://cdn.invalid/stream/season-1"
        const val HANDLE = "/api/v1/stream?id=abc123"
        const val FACTORY_PATH = "src/main/kotlin/com/raddstream/app/player/PlaybackMediaItemFactory.kt"
    }
}
