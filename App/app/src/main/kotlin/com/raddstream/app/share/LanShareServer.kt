package com.raddstream.app.share

import java.io.BufferedOutputStream
import java.io.File
import java.io.InputStream
import java.io.RandomAccessFile
import java.net.ServerSocket
import java.net.Socket
import java.nio.charset.StandardCharsets.UTF_8
import kotlin.concurrent.thread

/**
 * One catalog row: the pure protocol metadata plus the [File] to stream it from. The pairing
 * is made by the wiring code from the engine's committed-file listing — the server never
 * discovers files on its own, so the set of servable bytes is fixed by the catalog, not by
 * anything a client can say.
 */
data class ShareTarget(val entry: ShareEntry, val file: File)

/**
 * Thin socket shell around [LanShareProtocol]: binds, accepts, reads one capped request,
 * delegates every decision to the pure protocol, then streams bytes. Only `java.net` and
 * `java.io` — no NanoHTTPD or any other third-party server, per the project's dependency
 * rules.
 *
 * Why the split exists: the protocol holds all policy (which status, which byte span,
 * whether a token exists) and is JVM-testable without opening a port; this file holds only
 * framing and I/O, so a bug in one half never hides inside the other.
 *
 * Why the explicit opt-in: a server bound to all interfaces is reachable by every device on
 * the network — smart TVs, guest laptops, a neighbor. Serving downloaded media is exactly
 * what the user toggles, so [start] refuses to listen unless the constructor was given
 * `sharingEnabled = true`; default false means accidental wiring can never silently expose
 * a share.
 */
class LanShareServer(
    private val sharingEnabled: Boolean = false,
    private val port: Int = DEFAULT_PORT,
    /** Re-read per request so a title toggled off stops being served without a restart. */
    private val catalogProvider: () -> Map<String, ShareTarget>,
) : AutoCloseable {

    private var serverSocket: ServerSocket? = null
    private var acceptThread: Thread? = null
    @Volatile private var running = false

    /**
     * Starts listening when (and only when) the caller opted in. Returns the actual bound
     * port, or null when disabled or the port is taken — the UI must show "share failed to
     * start" rather than advertise a URL that nothing answers on.
     */
    @Synchronized
    fun start(): Int? {
        if (!sharingEnabled || running) return null
        return try {
            val srv = ServerSocket(port)
            serverSocket = srv
            running = true
            acceptThread = thread(name = "lan-share-${srv.localPort}", isDaemon = true) {
                acceptLoop(srv)
            }
            srv.localPort
        } catch (_: Exception) {
            runCatching { serverSocket?.close() }
            serverSocket = null
            running = false
            null
        }
    }

    /** Closes the listening socket (which unblocks `accept`) and joins the thread; idempotent. */
    @Synchronized
    fun stop() {
        running = false
        runCatching { serverSocket?.close() }
        acceptThread?.join(JOIN_MILLIS)
        acceptThread = null
        serverSocket = null
    }

    override fun close() = stop()

    private fun acceptLoop(srv: ServerSocket) {
        while (running) {
            val socket = try {
                srv.accept()
            } catch (_: Exception) {
                break
            }
            thread(isDaemon = true) { handle(socket) }
        }
        runCatching { srv.close() }
    }

    private fun handle(socket: Socket) {
        try {
            socket.use { s ->
                s.tcpNoDelay = true
                val request = readCappedRequest(s) ?: return
                val catalog = catalogProvider()
                val response = LanShareProtocol.respond(
                    method = request.method,
                    path = request.path,
                    headers = request.headers,
                    catalog = catalog.mapValues { it.value.entry },
                )
                val out = BufferedOutputStream(s.getOutputStream())
                try {
                    writeHead(out, response)
                    if (response.bodyLength > 0) {
                        // Resolve the file by TOKEN through the catalog — the request path
                        // itself is never used as a filesystem reference.
                        val token = tokenFromPath(request.path)
                        val target = if (token == null) null else catalog[token]
                        if (target != null) streamBody(out, target.file, response)
                    }
                    out.flush()
                } catch (_: Exception) {
                    // A player that vanishes mid-download is normal, not an error to chase.
                }
            }
        } catch (_: Exception) {
        }
    }

    private fun writeHead(out: BufferedOutputStream, response: ShareResponse) {
        val sb = StringBuilder("HTTP/1.1 ${response.status} ${reasonFor(response.status)}\r\n")
        sb.append("Server: ${LanShareProtocol.AGENT}\r\n")
        for ((k, v) in response.headers) sb.append("$k: $v\r\n")
        sb.append("\r\n")
        out.write(sb.toString().toByteArray(UTF_8))
    }

    /**
     * Seeks to the span the protocol chose and copies exactly [ShareResponse.bodyLength]
     * bytes. Clamping to the file's real length means a catalog entry that went stale (file
     * shrank or was TTL-swept) truncates the body honestly instead of throwing or padding.
     * Only ever opens a File the catalog supplied.
     */
    private fun streamBody(out: BufferedOutputStream, file: File, response: ShareResponse) {
        if (!file.isFile) return
        try {
            RandomAccessFile(file, "r").use { raf ->
                val available = (file.length() - response.bodyStart).coerceAtLeast(0)
                var remaining = response.bodyLength.coerceAtMost(available)
                raf.seek(response.bodyStart)
                val buf = ByteArray(COPY_BUFFER_BYTES)
                while (remaining > 0) {
                    val n = raf.read(buf, 0, minOf(remaining, buf.size.toLong()).toInt())
                    if (n <= 0) break
                    out.write(buf, 0, n)
                    remaining -= n
                }
            }
        } catch (_: Exception) {
        }
    }

    /**
     * Reads the request block byte-wise up to the blank line, refusing anything over
     * [LanShareProtocol.MAX_HEADER_BYTES] by answering 431 directly — this guard runs while
     * buffering, before parsing, because the protocol's own cap check can only see a
     * request we were willing to hold in memory at all.
     */
    private fun readCappedRequest(socket: Socket): ParsedRequest? {
        val input = socket.getInputStream()
        val bytes = ArrayList<Byte>(512)
        while (true) {
            val b = input.read()
            if (b < 0) break
            bytes.add(b.toByte())
            if (bytes.size > LanShareProtocol.MAX_HEADER_BYTES) {
                rejectOversized(socket)
                return null
            }
            if (bytes.size >= 4 && endsWithBlankLine(bytes)) break
        }
        return if (bytes.size >= 4 && endsWithBlankLine(bytes)) finish(bytes) else null
    }

    private fun endsWithBlankLine(bytes: ArrayList<Byte>): Boolean {
        val n = bytes.size
        return n >= 4 &&
            bytes[n - 4] == '\r'.code.toByte() && bytes[n - 3] == '\n'.code.toByte() &&
            bytes[n - 2] == '\r'.code.toByte() && bytes[n - 1] == '\n'.code.toByte()
    }

    private fun rejectOversized(socket: Socket) {
        try {
            val body = "Content-Length: 0\r\n\r\n"
            val head = "HTTP/1.1 431 Request Header Fields Too Large\r\n".toByteArray(UTF_8)
            socket.getOutputStream().use { it.write(head); it.write(body.toByteArray(UTF_8)); it.flush() }
        } catch (_: Exception) {
        }
    }

    private fun finish(bytes: ArrayList<Byte>): ParsedRequest? {
        val text = String(bytes.toByteArray(), UTF_8)
        val lines = text.split("\r\n").map { it.trimEnd('\r', '\n') }.filter { it.isNotBlank() }
        if (lines.isEmpty()) return null
        val parts = lines.first().split(" ")
        if (parts.size < 2) return null
        val headers = LinkedHashMap<String, String>()
        for (line in lines.drop(1)) {
            val idx = line.indexOf(':')
            if (idx > 0) headers[line.substring(0, idx).trim()] = line.substring(idx + 1).trim()
        }
        return ParsedRequest(parts[0], parts[1], headers)
    }

    private data class ParsedRequest(val method: String, val path: String, val headers: Map<String, String>)

    companion object {
        const val DEFAULT_PORT = 8990
        private const val JOIN_MILLIS = 2_000L
        private const val COPY_BUFFER_BYTES = 8_192

        /**
         * Applies the same token rules as the protocol: a path that is not one clean
         * segment yields null, so no filesystem name is ever assembled from hostile input.
         */
        fun tokenFromPath(path: String): String? {
            val clean = path.substringBefore('?').substringBefore('#')
            if (!clean.startsWith("/") || clean.length <= 1) return null
            val token = clean.substring(1)
            return if (token.any { it == '/' || it == '\\' } ||
                token.contains("..") ||
                token.contains('%')
            ) null else token
        }

        private fun reasonFor(status: Int): String = when (status) {
            200 -> "OK"
            206 -> "Partial Content"
            400 -> "Bad Request"
            403 -> "Forbidden"
            404 -> "Not Found"
            405 -> "Method Not Allowed"
            431 -> "Request Header Fields Too Large"
            else -> "Error"
        }
    }
}
