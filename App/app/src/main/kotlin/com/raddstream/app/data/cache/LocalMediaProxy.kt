package com.raddstream.app.data.cache

import android.net.Uri
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStream
import java.io.RandomAccessFile
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import kotlin.concurrent.thread

/**
 * App-only local media serving for a partially-downloaded (range-resumed) file.
 *
 * Why a loopback HTTP server instead of a `file://` Uri or a [androidx.core.content.FileProvider]
 * + `ACTION_VIEW`:
 *  - `file://` on a partial file cannot express "these middle bytes are not on disk yet" to
 *    Media3's progressive reader, and offers no Range handling of our own.
 *  - `FileProvider`/`ACTION_VIEW` would hand the media to *external* apps, which the spec forbids
 *    ("playable by this app's player and not handed to external apps").
 *
 * This server binds **only to the loopback interface** (`127.0.0.1`), speaks plain HTTP/1.1, and
 * answers `Range` requests from the private cache file, but never serves bytes beyond the
 * verified prefix reported by [prefixProvider] — so a range-resumed partial download plays
 * exactly the parts that exist and Media3 simply sees EOF at the frontier rather than reading
 * garbage holes. No token, no external exposure, no other app can consume it (and even if a
 * local process connected, the bytes are only ever files this app already owns).
 *
 * The player integrates by opening [uriFor] as a normal `MediaItem`; it works for both HLS
 * (`local.m3u8`) and progressive files.
 */
class LocalMediaProxy(
    private val file: java.io.File,
    private val prefixProvider: () -> Long,
    private val contentType: String = "application/octet-stream",
) : AutoCloseable {

    private val server: ServerSocket = ServerSocket(0, 8, InetAddress.getLoopbackAddress())
    private val port: Int = server.localPort
    @Volatile private var running = true
    private val worker: Thread = thread(name = "radd-local-proxy-$port", isDaemon = true) { acceptLoop() }

    /** A loopback `http://127.0.0.1:port/<fileid>` URI for the player. */
    fun uriFor(): Uri = Uri.parse("http://127.0.0.1:$port/${file.name}")

    val baseHttpUrl: String get() = "http://127.0.0.1:$port/${file.name}"

    private fun acceptLoop() {
        while (running) {
            val socket = try {
                server.accept()
            } catch (_: Exception) {
                break
            }
            thread(isDaemon = true) { handle(socket) }
        }
        runCatching { server.close() }
    }

    private fun handle(socket: Socket) {
        try {
            socket.use { s ->
                val reader = BufferedReader(InputStreamReader(s.getInputStream()))
                val requestLine = reader.readLine() ?: return
                val parts = requestLine.split(" ")
                if (parts.size < 2 || parts[0] != "GET") {
                    respond(s.getOutputStream(), 405, "text/plain", 0, null, "method not allowed".toByteArray())
                    return
                }
                var rangeHeader: String? = null
                while (true) {
                    val line = reader.readLine() ?: break
                    if (line.isEmpty()) break
                    val idx = line.indexOf(':')
                    if (idx > 0 && line.substring(0, idx).trim().equals("Range", ignoreCase = true)) {
                        rangeHeader = line.substring(idx + 1).trim()
                    }
                }

                val fileLen = file.length()
                val committed = minOf(prefixProvider(), fileLen).coerceAtLeast(0L)
                val total = if (fileLen > 0) fileLen else committed
                val range = parseRange(rangeHeader, total.coerceAtLeast(committed))
                val start = range?.first ?: 0L
                val end = range?.second ?: (committed - 1).coerceAtLeast(0L)

                if (committed <= 0 || start >= committed) {
                    // Nothing on disk at this offset yet: tell Media3 we're at the frontier.
                    respond(s.getOutputStream(), 416, contentType, 0, "bytes */$committed", ByteArray(0))
                    return
                }
                // Only the verified prefix is ever served; the tail of a pre-allocated file is
                // not on disk yet, and reading it would hand Media3 zeros as if they were media.
                val effectiveEnd = minOf(end, committed - 1)
                val len = (effectiveEnd - start + 1).coerceAtLeast(0L)
                val contentRange = "bytes $start-$effectiveEnd/$total"
                val status = if (range != null) 206 else 200
                respondStreaming(s.getOutputStream(), status, contentType, len, contentRange, start)
            }
        } catch (_: Exception) {
            /* a dropped player connection is normal; nothing to salvage */
        }
    }

    /**
     * Stream a byte range from the file rather than materialising it. A media file is routinely
     * hundreds of megabytes, so buffering the requested range — which an open-ended
     * `Range: bytes=0-` makes the whole file — would turn the first frame into an OOM. Chunks of
     * [STREAM_CHUNK_BYTES] are copied straight to the socket.
     */
    private fun respondStreaming(
        out: OutputStream,
        status: Int,
        type: String,
        contentLength: Long,
        contentRange: String?,
        start: Long,
    ) {
        val sb = StringBuilder()
        sb.append("HTTP/1.1 $status ${reasonOf(status)}\r\n")
        sb.append("Content-Type: $type\r\n")
        sb.append("Content-Length: $contentLength\r\n")
        sb.append("Accept-Ranges: bytes\r\n")
        if (contentRange != null) sb.append("Content-Range: $contentRange\r\n")
        sb.append("Connection: close\r\n\r\n")
        out.write(sb.toString().toByteArray())
        RandomAccessFile(file, "r").use { raf ->
            raf.seek(start)
            var remaining = contentLength
            val buffer = ByteArray(STREAM_CHUNK_BYTES)
            while (remaining > 0) {
                val want = minOf(remaining, buffer.size.toLong()).toInt()
                val read = raf.read(buffer, 0, want)
                if (read <= 0) break
                out.write(buffer, 0, read)
                remaining -= read
            }
        }
        out.flush()
    }

    private fun respond(
        out: OutputStream,
        status: Int,
        type: String,
        contentLength: Long,
        contentRange: String?,
        body: ByteArray,
    ) {
        val sb = StringBuilder()
        sb.append("HTTP/1.1 $status ${reasonOf(status)}\r\n")
        sb.append("Content-Type: $type\r\n")
        sb.append("Content-Length: $contentLength\r\n")
        sb.append("Accept-Ranges: bytes\r\n")
        if (contentRange != null) sb.append("Content-Range: $contentRange\r\n")
        sb.append("Connection: close\r\n\r\n")
        out.write(sb.toString().toByteArray())
        if (body.isNotEmpty()) out.write(body)
        out.flush()
    }

    private fun reasonOf(status: Int): String = when (status) {
        200 -> "OK"; 206 -> "Partial Content"; 405 -> "Method Not Allowed"; 416 -> "Range Not Satisfiable"
        else -> "OK"
    }

    override fun close() {
        running = false
        runCatching { server.close() }
        runCatching { worker.interrupt() }
    }

    companion object {
        /** Copy granularity: a socket buffer, not a media file. */
        const val STREAM_CHUNK_BYTES = 64 * 1024

        /** Parse `bytes=start-end` (either side optional) into an inclusive pair, or null. */
        fun parseRange(header: String?, total: Long): Pair<Long, Long>? {
            if (header.isNullOrBlank() || !header.startsWith("bytes=")) return null
            val value = header.removePrefix("bytes=").trim()
            val dash = value.indexOf('-')
            if (dash < 0) return null
            val startStr = value.substring(0, dash)
            val endStr = value.substring(dash + 1)
            val start = when {
                startStr.isEmpty() -> {
                    // suffix range "bytes=-N" → last N bytes
                    val n = endStr.toLongOrNull() ?: return null
                    (total - n).coerceAtLeast(0L)
                }
                else -> startStr.toLongOrNull() ?: return null
            }
            // HTTP byte ranges are inclusive: `bytes=0-99` is exactly one hundred bytes.
            // Subtracting one here would answer 99 bytes to a 100-byte request and leave a
            // one-byte hole at every seek Media3 performs by asking for an explicit window.
            val end = if (endStr.isEmpty() || startStr.isEmpty()) total - 1
            else endStr.toLongOrNull() ?: return null
            return if (end >= start) start to end else null
        }
    }
}
