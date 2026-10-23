package com.raddstream.app.data.cache

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.IOException
import java.io.RandomAccessFile
import kotlin.coroutines.coroutineContext

/**
 * Outcome of one range read attempt. Classified so the engine can distinguish the three
 * hostile cases it must never confuse:
 *  - [SourceDead] — an ephemeral URL rotted (403/410/404 or a redirect we cannot follow); we
 *    keep every byte already on disk and re-resolve later, never silently restart.
 *  - [NoRangeSupport] — the server ignored our `Range` and returned the whole file from byte 0
 *    (HTTP 200, no `Content-Range`); we must NOT seek-write it into the middle of the file, so
 *    the engine falls back to sequential-prefix mode.
 *  - [HttpError] / [IoError] — retryable per [RetryPolicy].
 */
sealed class RangeFetchResult {
    data class Success(val bytesWritten: Long, val rangeHonored: Boolean, val totalSize: Long?) : RangeFetchResult()
    data class SourceDead(val httpStatus: Int) : RangeFetchResult()
    object NoRangeSupport : RangeFetchResult()
    data class HttpError(val httpStatus: Int) : RangeFetchResult()
    data class IoError(val message: String) : RangeFetchResult()
    object Cancelled : RangeFetchResult()
}

/**
 * Fetches one absolute byte range `[start, endInclusive)` (HTTP Range is inclusive on both ends)
 * and writes it at the matching offset of a pre-allocated file. This is the primitive behind
 * the interval ledger — every "gap" the ledger reports becomes exactly one call here, so the
 * bytes written map 1:1 to the intervals we later mark covered.
 */
class RangeByteFetcher(private val client: OkHttpClient) {

    /**
     * @param file the (private) destination file; pre-allocated to [totalSize] when known so
     *        out-of-order writes land at the right offset and the partial file stays a valid,
     *        sized, resumable artifact (not garbage).
     * @param start absolute first byte to fetch (0-based).
     * @param endExclusive one-past the last byte; if null the server range is open-ended.
     */
    suspend fun fetch(
        url: String,
        file: RandomAccessFile,
        start: Long,
        endExclusive: Long?,
        totalSize: Long?,
    ): RangeFetchResult = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url(url)
            .apply { if (start >= 0) header("Range", rangeHeader(start, endExclusive)) }
            .build()

        var response: okhttp3.Response? = null
        try {
            response = client.newCall(request).execute()
            val code = response.code

            if (code == 403 || code == 410 || code == 404) {
                return@withContext RangeFetchResult.SourceDead(code)
            }
            if (code == 416) {
                // Requested a range past EOF: treat as success with zero bytes, the caller
                // will see the ledger already covers the file.
                return@withContext RangeFetchResult.Success(0, true, totalSize)
            }
            if (!response.isSuccessful) {
                return@withContext RangeFetchResult.HttpError(code)
            }

            // Did the server honour our Range?
            val honored = code == 206 || response.header("Content-Range") != null
            if (start > 0 && !honored) {
                // It streamed the whole file despite our header — we cannot safely place it at
                // an offset. Hand control back to sequential-prefix mode.
                response.body?.close()
                return@withContext RangeFetchResult.NoRangeSupport
            }

            // Discover total size from Content-Range ("bytes 100-199/2000") when we lacked it.
            val discovered = totalSize ?: parseTotalFromContentRange(response.header("Content-Range"))
                ?: parseTotalFromContentLength(response.header("Content-Length"), start)

            // Pre-allocate so RandomAccessFile.seek() to an offset within the file is legal.
            if (discovered != null && discovered > 0) {
                if (file.length() < discovered) file.setLength(discovered)
            }

            val body = response.body ?: return@withContext RangeFetchResult.HttpError(code)
            val input = body.byteStream()
            var written = 0L
            val buffer = ByteArray(CHUNK_BYTES)
            file.seek(start)
            // Open-ended tail request (no endExclusive): stop at EOF rather than a computed limit.
            val openEnded = endExclusive == null
            while (openEnded || written < (endExclusive!! - start)) {
                coroutineContext.ensureActive() // cooperative cancel between chunks
                val want = if (openEnded) buffer.size
                    else minOf(buffer.size.toLong(), endExclusive - start - written).toInt()
                if (want <= 0) break
                val read = input.read(buffer, 0, want)
                if (read == -1) break
                file.write(buffer, 0, read)
                written += read
            }
            RangeFetchResult.Success(written, honored, discovered)
        } catch (ce: CancellationException) {
            throw ce // never swallow structured concurrency cancellation
        } catch (io: IOException) {
            RangeFetchResult.IoError(io.message ?: "io_error")
        } finally {
            try {
                response?.body?.close()
            } catch (_: IOException) {
                /* ignore close races */
            }
        }
    }

    private fun rangeHeader(start: Long, endExclusive: Long?): String =
        if (endExclusive != null) "bytes=$start-${endExclusive - 1}" else "bytes=$start-"

    companion object {
        const val CHUNK_BYTES = 64 * 1024

        fun parseTotalFromContentRange(header: String?): Long? {
            // "bytes 0-1023/2048" → 2048 ; "*" variant is unknown.
            if (header.isNullOrBlank()) return null
            val afterSlash = header.substringAfter('/', "")
            return afterSlash.toLongOrNull()?.takeIf { it > 0 }
        }

        fun parseTotalFromContentLength(header: String?, start: Long): Long? {
            val len = header?.toLongOrNull()?.takeIf { it > 0 } ?: return null
            return if (start == 0L) len else null
        }
    }
}
