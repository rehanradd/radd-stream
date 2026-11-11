package com.raddstream.app.network

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.io.IOException

/**
 * friendlyNetworkError is the only place a transport failure becomes a sentence,
 * so every branch it claims is tested here — including the branch where it must
 * stay silent and hand back the caller's own fallback wording.
 */
class ClientErrorsTest {

    private val fallback = "Something went wrong."

    @Test
    fun `cleartext refusal names the address as the problem, not the network`() {
        val error = IOException(
            "CLEARTEXT communication to 92.4.95.252 not permitted by network security policy"
        )
        val message = friendlyNetworkError(error, fallback, debugBuild = false)
        assertTrue(message, message.contains("unsecured address"))
        assertTrue(message, !message.contains("CLEARTEXT"))
    }

    @Test
    fun `unresolved host points at the server address the viewer typed`() {
        val message = friendlyNetworkError(UnknownHostException("example.invalid"), fallback)
        assertTrue(message, message.contains("Check its address in Settings"))
    }

    @Test
    fun `refused connection says the server may be offline`() {
        val message = friendlyNetworkError(ConnectException("Failed to connect /1.2.3.4:80"), fallback)
        assertTrue(message, message.contains("didn't answer"))
    }

    @Test
    fun `timeout asks for a retry rather than blame`() {
        val message = friendlyNetworkError(SocketTimeoutException(), fallback)
        assertTrue(message, message.contains("too long"))
    }

    @Test
    fun `rate limit and server trouble are told apart by status code`() {
        assertTrue(
            friendlyNetworkError(IOException("HTTP 429 Too Many Requests"), fallback)
                .contains("Give it a minute")
        )
        assertTrue(
            friendlyNetworkError(IOException("HTTP 503 Server Error"), fallback)
                .contains("having trouble")
        )
        assertEquals(404, httpStatus("HTTP 404 Not Found"))
        assertEquals(503, httpStatus("HTTP 503 Server Error"))
        assertEquals(null, httpStatus("timeout"))
    }

    @Test
    fun `an unclassifiable failure keeps the fallback the caller supplied`() {
        assertEquals(fallback, friendlyNetworkError(IllegalStateException("weird"), fallback))
        assertEquals(fallback, friendlyNetworkError(null, fallback))
    }

    @Test
    fun `no raw text is ever appended, even in debug builds`() {
        // Audit #14: the shipped build is a debug build, and the old debug
        // suffix showed "(HTTP 503 Service Unavailable)" to the viewer.
        val error = IOException("HTTP 503 Service Unavailable")
        val debug = friendlyNetworkError(error, fallback, debugBuild = true)
        assertEquals("The catalog server is having trouble right now.", debug)
        assertTrue(debug, !debug.contains("503"))
    }

    @Test
    fun `the fallback is never doubled with raw text`() {
        val debug = friendlyNetworkError(IllegalStateException("weird"), fallback, debugBuild = true)
        assertEquals(fallback, debug)
    }
}
