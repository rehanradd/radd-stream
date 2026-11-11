package com.raddstream.app.data.downloads

import java.util.Locale

/**
 * App-design audit (2026-11-12, issue #12): a download that feels alive
 * shows % + MB + speed + ETA. The estimate is pure — a rolling average
 * over the last few progress samples — so the Downloads row and the
 * notification can never disagree about it, and so it is unit-testable
 * without a network.
 *
 * Samples are (bytes downloaded, monotonic clock ms), oldest first.
 * Fewer than two samples, or no forward movement, means "calculating":
 * speed 0 and no ETA, never a guessed number.
 */
object DownloadSpeed {

    /** Rolling speed in bytes/second over [samples], or 0 while calculating. */
    fun estimateBytesPerSec(samples: List<Pair<Long, Long>>): Long {
        if (samples.size < 2) return 0L
        val first = samples.first()
        val last = samples.last()
        val bytes = last.first - first.first
        val millis = last.second - first.second
        if (bytes <= 0L || millis <= 0L) return 0L
        return bytes * 1000L / millis
    }

    /** Seconds until [remainingBytes] at [bytesPerSec], or null while calculating. */
    fun etaSeconds(remainingBytes: Long, bytesPerSec: Long): Long? {
        if (remainingBytes <= 0L) return 0L
        if (bytesPerSec <= 0L) return null
        return remainingBytes / bytesPerSec
    }

    /** "1.2 MB/s", "850 KB/s", "0 B/s" — the unit the viewer already reads. */
    fun formatSpeed(bytesPerSec: Long): String = when {
        bytesPerSec >= 1_000_000L -> String.format(Locale.US, "%.1f MB/s", bytesPerSec / 1_000_000.0)
        bytesPerSec >= 1_000L -> String.format(Locale.US, "%.0f KB/s", bytesPerSec / 1_000.0)
        else -> "$bytesPerSec B/s"
    }

    /** "about 4 min left", "about 30 sec left", or null while calculating. */
    fun formatEta(etaSeconds: Long?): String? = when {
        etaSeconds == null -> null
        etaSeconds <= 0L -> "almost done"
        etaSeconds < 60L -> "about $etaSeconds sec left"
        etaSeconds < 3600L -> "about ${etaSeconds / 60L} min left"
        else -> "about ${etaSeconds / 3600L} hr left"
    }
}
