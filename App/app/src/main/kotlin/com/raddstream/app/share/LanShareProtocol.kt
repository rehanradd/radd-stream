package com.raddstream.app.share

/**
 * PURE request/response logic for the on-device LAN share server — no android.* imports, no
 * sockets, so the whole HTTP contract is JVM-testable (see LanShareProtocolTest).
 *
 * Why token-resolved instead of path-resolved: the wire format looks like a file path, but a
 * request never selects a file. It selects a [ShareEntry] from the opaque catalog the caller
 * built in advance, and only that entry's own stored name is ever surfaced. A client typing
 * traversal segments (`..`, encoded slashes, backslashes) simply produces a token that is not
 * in the map — a 404 with no filesystem lookup attempted at all. That makes the traversal
 * class of bugs structurally impossible rather than filtered-for.
 *
 * Why the URL carries a token and not the filename: [shareUrl] output is shown to other
 * people on the network (and pasted into chat). A filename is user data; the media's upstream
 * source URL is provenance that must never reach a presentation surface (root AGENTS.md
 * provenance rule). An opaque random token is the only identifier that leaks nothing.
 */

/** One shareable local file, keyed by its opaque token in the catalog handed to [respond]. */
data class ShareEntry(
    /** Our own on-device filename, for Content-Disposition-style display only, never resolved. */
    val fileName: String,
    val sizeBytes: Long,
    val contentType: String,
    /** The per-title share toggle; false answers 403 so a disabled share is provably dead. */
    val enabled: Boolean = true,
)

/**
 * A fully-formed response the socket layer can serialize verbatim: status line, headers, and
 * exactly which slice of the file to write. [bodyLength] is 0 for HEAD and for every error,
 * which is what makes "HEAD returns headers with no body" a property of the data, not of the
 * server's discipline.
 */
data class ShareResponse(
    val status: Int,
    val headers: Map<String, String>,
    /** File offset to seek to before writing; meaningless when [bodyLength] is 0. */
    val bodyStart: Long,
    /** Bytes the server must write; equals the declared Content-Length for a GET body. */
    val bodyLength: Long,
) {
    val isOk: Boolean get() = status == 200 || status == 206
}

/** Inclusive byte span requested and satisfiable; null means absent, malformed, or unsatisfiable. */
typealias ByteSpan = LongRange

object LanShareProtocol {

    /** What the LAN peer sees in `Server:`. Names the component, not the product. */
    const val AGENT: String = "lan-share/1"

    /**
     * Hard ceiling on the request block (request line + headers). Media clients legitimately
     * send a few hundred bytes; an unbounded read turns the accept loop into a memory DoS
     * vector for anything that can reach the port, and the port is open to the whole LAN.
     * 8 KB rejects abuse while staying far above any real player's headers.
     */
    const val MAX_HEADER_BYTES: Int = 8 * 1024

    /**
     * Parses one `Range: bytes=...` header against a known file size. Supports the three
     * forms players actually send: explicit `a-b`, open-ended `a-`, and suffix `-N`
     * (last N bytes). Multi-ranges are deliberately unsupported — every consumer here
     * (ExoPlayer, browsers) requests a single span, and honoring only the first of several
     * would silently serve wrong bytes.
     *
     * Returns null for an absent header (caller answers 200), and also null for malformed
     * or unsatisfiable ones; the caller distinguishes those only against the header being
     * absent, and answers 400 with `Content-Range: * / size` per RFC 9110 either way.
     */
    fun parseRange(header: String?, sizeBytes: Long): ByteSpan? {
        val trimmed = header?.trim() ?: return null
        if (!trimmed.startsWith("bytes=", ignoreCase = true)) return null
        val value = trimmed.substring("bytes=".length).trim()
        if (value.isEmpty() || value.contains(',')) return null
        if (sizeBytes <= 0) return null
        val dash = value.indexOf('-')
        if (dash < 0) return null
        val startText = value.substring(0, dash).trim()
        val endText = value.substring(dash + 1).trim()
        if (startText.isEmpty() && endText.isEmpty()) return null
        return if (startText.isEmpty()) {
            // Suffix form: last N bytes. N = 0 is unsatisfiable by definition.
            val n = endText.toLongOrNull() ?: return null
            if (n <= 0) null else (sizeBytes - n).coerceAtLeast(0)..sizeBytes - 1
        } else {
            val start = startText.toLongOrNull() ?: return null
            if (start < 0 || start >= sizeBytes) return null
            if (endText.isEmpty()) {
                start..sizeBytes - 1
            } else {
                val end = endText.toLongOrNull() ?: return null
                if (end < start) return null
                start..end.coerceAtMost(sizeBytes - 1)
            }
        }
    }

    /**
     * The whole protocol: given the request line split into [method] + [path], the parsed
     * header map, and the pre-built [catalog], decide the complete response. No I/O occurs,
     * so every branch is reachable from a unit test.
     *
     * Check order matters and is deliberate: header budget first (before any other work, so
     * an oversized flood does the least), then method (405 before revealing token existence),
     * then token lookup (404), then the enable toggle (403), then Range validity (400),
     * then 200/206.
     */
    fun respond(
        method: String,
        path: String,
        headers: Map<String, String>,
        catalog: Map<String, ShareEntry>,
    ): ShareResponse {
        if (headerBlockBytes(method, path, headers) > MAX_HEADER_BYTES) {
            return error(431, "Request Header Fields Too Large")
        }
        val upper = method.uppercase()
        if (upper != "GET" && upper != "HEAD") {
            return error(405, "Method Not Allowed").let { resp ->
                resp.copy(headers = resp.headers + ("Allow" to "GET, HEAD"))
            }
        }
        val entry = catalog[tokenOf(path)] ?: return error(404, "Not Found")
        if (!entry.enabled) return error(403, "Forbidden")

        val size = entry.sizeBytes
        val rangeHeader = headers.entries
            .firstOrNull { it.key.equals("Range", ignoreCase = true) }
            ?.value
        val span = if (rangeHeader == null) null else parseRange(rangeHeader, size)

        val baseHeaders = mapOf(
            "Content-Type" to entry.contentType,
            "Accept-Ranges" to "bytes",
        )
        val sendBody = upper == "GET"
        return if (rangeHeader != null && span == null) {
            ShareResponse(
                status = 400,
                headers = baseHeaders + ("Content-Range" to "*/$size") +
                    ("Content-Length" to "0"),
                bodyStart = 0,
                bodyLength = 0,
            )
        } else if (span != null) {
            val len = span.last - span.first + 1
            ShareResponse(
                status = 206,
                headers = baseHeaders +
                    ("Content-Range" to "bytes ${span.first}-${span.last}/$size") +
                    ("Content-Length" to len.toString()),
                bodyStart = span.first,
                bodyLength = if (sendBody) len else 0,
            )
        } else {
            ShareResponse(
                status = 200,
                headers = baseHeaders + ("Content-Length" to size.toString()),
                bodyStart = 0,
                bodyLength = if (sendBody) size else 0,
            )
        }
    }

    /**
     * Builds the URL another device pastes into a player. Emits only our own LAN address,
     * port, and opaque token: never the media's upstream source, and not even the filename,
     * because anything embedded here is visible to every device on the network.
     *
     * Throws if [hostAddress] is not a bare address — a caller that passes something holding
     * a path, userinfo, or a scheme has almost certainly mixed an upstream URL into the
     * host field, and silently producing a bogus-but-leaking URL would defeat the point.
     */
    fun shareUrl(hostAddress: String, port: Int, token: String): String {
        require(hostAddress.none { it == '/' || it == '@' || it == ':' || it.isWhitespace() }) {
            "hostAddress must be a bare local-network address"
        }
        require(port in 1..65535) { "port out of range" }
        require(token.isNotBlank() && token.none { it == '/' || it.isWhitespace() }) {
            "token must be a single opaque path segment"
        }
        return "http://$hostAddress:$port/$token"
    }

    /** Total wire bytes of the request block, counted with CRLF framing like the real thing. */
    fun headerBlockBytes(method: String, path: String, headers: Map<String, String>): Int {
        var total = method.length + 1 + path.length + 1 + 2
        for ((k, v) in headers) total += k.length + 2 + v.length + 2
        return total
    }

    /**
     * Reduces a requested path to its candidate token. Anything that is not exactly one
     * leading slash plus a single clean segment (traversal, nested paths, query, fragment,
     * encoded separators) becomes a token guaranteed to miss the catalog, yielding 404
     * without any filesystem being consulted.
     */
    internal fun tokenOf(path: String): String {
        val clean = path.substringBefore('?').substringBefore('#')
        if (!clean.startsWith("/") || clean.length <= 1) return ""
        val token = clean.substring(1)
        return if (token.any { it == '/' || it == '\\' } ||
            token.contains("..") ||
            token.contains('%')
        ) "" else token
    }

    private fun error(status: Int, reason: String): ShareResponse = ShareResponse(
        status = status,
        headers = mapOf("Content-Length" to "0", "X-Share-Reason" to reason),
        bodyStart = 0,
        bodyLength = 0,
    )
}
