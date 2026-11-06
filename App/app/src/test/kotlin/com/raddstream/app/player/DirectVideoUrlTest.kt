package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class DirectVideoUrlTest {

    @Test
    fun mp4UrlIsDirectVideoWithFileName() {
        val result = classifyPastedText("https://cdn.example.com/movies/hero-720p.mp4")
        assertTrue(result is PastedText.DirectVideo)
        // JUnit's assertTrue carries no smart-cast contract (kotlin.test's
        // does), so the cast is explicit: without it `result.url` does not
        // resolve. Same shape in every DirectVideo test below.
        val video = result as PastedText.DirectVideo
        assertEquals("https://cdn.example.com/movies/hero-720p.mp4", video.url)
        assertEquals("hero-720p.mp4", video.title)
        assertFalse(video.isHls)
    }

    @Test
    fun mp4UrlWithQueryStringKeepsTheFileName() {
        val result = classifyPastedText("https://cdn.example.com/movies/hero.mp4?token=abc&expires=1")
        assertTrue(result is PastedText.DirectVideo)
        val video = result as PastedText.DirectVideo
        assertEquals("hero.mp4", video.title)
        assertFalse(video.isHls)
    }

    @Test
    fun uppercaseExtensionStillCounts() {
        val result = classifyPastedText("https://cdn.example.com/movies/HERO.MP4")
        assertTrue(result is PastedText.DirectVideo)
        val video = result as PastedText.DirectVideo
        assertEquals("HERO.MP4", video.title)
    }

    @Test
    fun percentEncodedFileNameIsDecoded() {
        val result = classifyPastedText("https://cdn.example.com/movies/my%20movie%20720p.mp4")
        assertTrue(result is PastedText.DirectVideo)
        val video = result as PastedText.DirectVideo
        assertEquals("my movie 720p.mp4", video.title)
    }

    @Test
    fun m3u8UrlIsDirectVideoAndHls() {
        val result = classifyPastedText("https://cdn.example.com/stream/master.m3u8")
        assertTrue(result is PastedText.DirectVideo)
        val video = result as PastedText.DirectVideo
        assertEquals("master.m3u8", video.title)
        assertTrue(video.isHls)
    }

    @Test
    fun m3u8UrlWithQueryStringIsStillHls() {
        val result = classifyPastedText("https://cdn.example.com/stream/master.m3u8?token=abc")
        assertTrue(result is PastedText.DirectVideo)
        val video = result as PastedText.DirectVideo
        assertTrue(video.isHls)
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
