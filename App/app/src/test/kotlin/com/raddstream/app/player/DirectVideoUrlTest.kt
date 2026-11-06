package com.raddstream.app.player

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class DirectVideoUrlTest {

    @Test
    fun mp4UrlIsDirectVideoWithFileName() {
        val result = classifyPastedText("https://cdn.example.com/movies/hero-720p.mp4")
        assertTrue(result is PastedText.DirectVideo)
        assertEquals("https://cdn.example.com/movies/hero-720p.mp4", result.url)
        assertEquals("hero-720p.mp4", result.title)
        assertFalse(result.isHls)
    }

    @Test
    fun mp4UrlWithQueryStringKeepsTheFileName() {
        val result = classifyPastedText("https://cdn.example.com/movies/hero.mp4?token=abc&expires=1")
        assertTrue(result is PastedText.DirectVideo)
        assertEquals("hero.mp4", result.title)
        assertFalse(result.isHls)
    }

    @Test
    fun uppercaseExtensionStillCounts() {
        val result = classifyPastedText("https://cdn.example.com/movies/HERO.MP4")
        assertTrue(result is PastedText.DirectVideo)
        assertEquals("HERO.MP4", result.title)
    }

    @Test
    fun percentEncodedFileNameIsDecoded() {
        val result = classifyPastedText("https://cdn.example.com/movies/my%20movie%20720p.mp4")
        assertTrue(result is PastedText.DirectVideo)
        assertEquals("my movie 720p.mp4", result.title)
    }

    @Test
    fun m3u8UrlIsDirectVideoAndHls() {
        val result = classifyPastedText("https://cdn.example.com/stream/master.m3u8")
        assertTrue(result is PastedText.DirectVideo)
        assertEquals("master.m3u8", result.title)
        assertTrue(result.isHls)
    }

    @Test
    fun m3u8UrlWithQueryStringIsStillHls() {
        val result = classifyPastedText("https://cdn.example.com/stream/master.m3u8?token=abc")
        assertTrue(result is PastedText.DirectVideo)
        assertTrue(result.isHls)
    }

    @Test
    fun youtubeWatchLinkIsYouTube() {
        assertEquals(
            PastedText.YouTube,
            classifyPastedText("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        )
    }

    @Test
    fun youtubeShortLinkIsYouTube() {
        assertEquals(PastedText.YouTube, classifyPastedText("https://youtu.be/dQw4w9WgXcQ"))
    }

    @Test
    fun youtubeMusicAndMobileHostsAreYouTube() {
        assertEquals(
            PastedText.YouTube,
            classifyPastedText("https://music.youtube.com/watch?v=dQw4w9WgXcQ"),
        )
        assertEquals(
            PastedText.YouTube,
            classifyPastedText("https://m.youtube.com/watch?v=dQw4w9WgXcQ"),
        )
    }

    @Test
    fun plainTitleIsNotAUrl() {
        assertEquals(PastedText.NotAUrl, classifyPastedText("Avengers Endgame"))
        assertEquals(PastedText.NotAUrl, classifyPastedText(""))
        assertEquals(PastedText.NotAUrl, classifyPastedText("   "))
    }

    @Test
    fun pageUrlWithoutAVideoExtensionIsNotAUrl() {
        assertEquals(
            PastedText.NotAUrl,
            classifyPastedText("https://example.com/watch/movie/123"),
        )
        assertEquals(
            PastedText.NotAUrl,
            classifyPastedText("https://example.com/movies/hero.html"),
        )
    }

    @Test
    fun nonHttpSchemeIsNotAUrl() {
        assertEquals(PastedText.NotAUrl, classifyPastedText("ftp://example.com/movies/hero.mp4"))
        assertEquals(PastedText.NotAUrl, classifyPastedText("radd://detail/123"))
    }

    @Test
    fun urlWithNoFileNameIsNotAUrl() {
        assertEquals(
            PastedText.NotAUrl,
            classifyPastedText("https://example.com/movies/hero.mp4/"),
        )
        assertEquals(PastedText.NotAUrl, classifyPastedText("https://example.com"))
    }

    @Test
    fun directVideoMimeMatchesTheKind() {
        assertEquals("video/mp4", directVideoMime("https://cdn.example.com/movies/hero.mp4"))
        assertEquals(
            "application/vnd.apple.mpegurl",
            directVideoMime("https://cdn.example.com/stream/master.m3u8"),
        )
    }
}
