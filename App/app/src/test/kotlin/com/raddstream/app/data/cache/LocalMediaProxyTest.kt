package com.raddstream.app.data.cache

import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test

/**
 * The loopback server the player opens a kept file through. These are real HTTP requests to a
 * real [LocalMediaProxy] over `127.0.0.1` — no Robolectric, no device — because the whole point
 * of the class is that a `DefaultHttpDataSource` can Range-request it exactly like a CDN.
 */
class LocalMediaProxyTest {

    private lateinit var file: File
    private lateinit var proxy: LocalMediaProxy
    private lateinit var content: ByteArray

    @Before
    fun setUp() {
        content = ByteArray(FILE_BYTES) { index -> (index % 251).toByte() }
        file = File.createTempFile("radd-proxy-", ".mp4").apply { writeBytes(content) }
        proxy = LocalMediaProxy(file = file, prefixProvider = { file.length() }, contentType = "video/mp4")
    }

    @After
    fun tearDown() {
        proxy.close()
        file.delete()
    }

    @Test
    fun noRangeHeaderServesTheWholeFile() {
        val answer = get()
        assertEquals(200, answer.status)
        assertArrayEquals(content, answer.body)
        assertEquals("bytes", answer.headers["accept-ranges"])
    }

    @Test
    fun explicitRangeServesExactlyThatWindow() {
        val answer = get(range = "bytes=1000-1999")
        assertEquals(206, answer.status)
        assertEquals(1000, answer.body.size)
        assertArrayEquals(content.copyOfRange(1000, 2000), answer.body)
        assertEquals("bytes 1000-1999/$FILE_BYTES", answer.headers["content-range"])
    }

    @Test
    fun openEndedRangeServesFromStartToTheLastByte() {
        val from = FILE_BYTES - 50_000
        val answer = get(range = "bytes=$from-")
        assertEquals(206, answer.status)
        assertEquals(50_000, answer.body.size)
        assertArrayEquals(content.copyOfRange(from, FILE_BYTES), answer.body)
    }

    @Test
    fun suffixRangeServesTheTail() {
        val answer = get(range = "bytes=-500")
        assertEquals(206, answer.status)
        assertEquals(500, answer.body.size)
        assertArrayEquals(content.copyOfRange(FILE_BYTES - 500, FILE_BYTES), answer.body)
    }

    @Test
    fun beyondTheVerifiedPrefixAnswers416NotZeros() {
        val partial = LocalMediaProxy(
            file = file,
            prefixProvider = { 1_000L },
            contentType = "video/mp4",
        )
        try {
            val atTail = get(proxy = partial, range = "bytes=1000-1200")
            assertEquals("nothing past the verified prefix may be served", 416, atTail.status)
            assertEquals("bytes */1000", atTail.headers["content-range"])
            assertEquals(0, atTail.body.size)

            val inside = get(proxy = partial, range = "bytes=900-1100")
            assertEquals("a window that starts inside the prefix is clipped to it", 206, inside.status)
            assertEquals(100, inside.body.size)
            assertArrayEquals(content.copyOfRange(900, 1000), inside.body)
        } finally {
            partial.close()
        }
    }

    @Test
    fun parseRangeAcceptsAndRejectsTheDocumentedShapes() {
        assertEquals(0L to 99L, LocalMediaProxy.parseRange("bytes=0-99", 1000))
        assertEquals(900L to 999L, LocalMediaProxy.parseRange("bytes=900-", 1000))
        assertEquals(900L to 999L, LocalMediaProxy.parseRange("bytes=-100", 1000))
        assertNull(LocalMediaProxy.parseRange(null, 1000))
        assertNull(LocalMediaProxy.parseRange("items=0-1", 1000))
        assertNull(LocalMediaProxy.parseRange("bytes=", 1000))
        assertNull(LocalMediaProxy.parseRange("bytes=abc-", 1000))
        assertNull(LocalMediaProxy.parseRange("bytes=500-100", 1000))
    }

    @Test
    fun nonGetRequestsAreRefused() {
        val connection = URL(proxy.baseHttpUrl).openConnection() as HttpURLConnection
        try {
            connection.requestMethod = "POST"
            connection.doOutput = true
            connection.outputStream.use { it.write(ByteArray(0)) }
            assertEquals(405, connection.responseCode)
        } finally {
            connection.disconnect()
        }
    }

    private class Answer(
        val status: Int,
        val body: ByteArray,
        val headers: Map<String, String>,
    )

    private fun get(proxy: LocalMediaProxy = this.proxy, range: String? = null): Answer {
        val connection = URL(proxy.baseHttpUrl).openConnection() as HttpURLConnection
        try {
            connection.connectTimeout = TIMEOUT_MS
            connection.readTimeout = TIMEOUT_MS
            range?.let { connection.setRequestProperty("Range", it) }
            val status = connection.responseCode
            val stream = if (status >= 400) connection.errorStream else connection.inputStream
            val body = stream?.use { it.readBytes() } ?: ByteArray(0)
            val headers = connection.headerFields
                .filterKeys { it != null }
                .mapKeys { (key, _) -> key.lowercase() }
                .mapValues { (_, values) -> values.joinToString(", ") }
            return Answer(status, body, headers)
        } finally {
            connection.disconnect()
        }
    }

    private companion object {
        const val FILE_BYTES = 300_000
        const val TIMEOUT_MS = 5_000
    }
}
