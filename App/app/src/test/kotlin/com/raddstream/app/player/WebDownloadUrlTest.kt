package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Test

class WebDownloadUrlTest {

    @Test
    fun baseWithoutTrailingSlashGetsDownloadEndpointWithWebMarker() {
        assertEquals(
            "http://92.4.95.252/api/v1/download?id=abc123&via=web",
            webDownloadUrl("http://92.4.95.252", "abc123"),
        )
    }

    @Test
    fun baseWithTrailingSlashDoesNotDoubleIt() {
        assertEquals(
            "http://92.4.95.252/api/v1/download?id=abc123&via=web",
            webDownloadUrl("http://92.4.95.252/", "abc123"),
        )
    }

    @Test
    fun handleIsUrlEncoded() {
        assertEquals(
            "https://example.test/api/v1/download?id=a%2Bb%3Dc&via=web",
            webDownloadUrl("https://example.test", "a+b=c"),
        )
    }

    @Test
    fun httpsBaseIsKeptVerbatim() {
        assertEquals(
            "https://raddstream.duckdns.org/api/v1/download?id=tok-1&via=web",
            webDownloadUrl("https://raddstream.duckdns.org", "tok-1"),
        )
    }
}
