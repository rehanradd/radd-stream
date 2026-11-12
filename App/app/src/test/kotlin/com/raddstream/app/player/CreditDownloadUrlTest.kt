package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Test

class CreditDownloadUrlTest {

    @Test
    fun baseWithoutTrailingSlashGetsDownloadEndpointWithCredit() {
        assertEquals(
            "http://92.4.95.252/api/v1/download?id=abc123&credit=cred-1",
            creditDownloadUrl("http://92.4.95.252", "abc123", "cred-1"),
        )
    }

    @Test
    fun baseWithTrailingSlashDoesNotDoubleIt() {
        assertEquals(
            "http://92.4.95.252/api/v1/download?id=abc123&credit=cred-1",
            creditDownloadUrl("http://92.4.95.252/", "abc123", "cred-1"),
        )
    }

    @Test
    fun handleAndTokenAreUrlEncoded() {
        assertEquals(
            "https://example.test/api/v1/download?id=a%2Bb%3Dc&credit=x%2By%3D",
            creditDownloadUrl("https://example.test", "a+b=c", "x+y="),
        )
    }

    @Test
    fun httpsBaseIsKeptVerbatim() {
        assertEquals(
            "https://raddstream.duckdns.org/api/v1/download?id=tok-1&credit=tok-2",
            creditDownloadUrl("https://raddstream.duckdns.org", "tok-1", "tok-2"),
        )
    }
}
