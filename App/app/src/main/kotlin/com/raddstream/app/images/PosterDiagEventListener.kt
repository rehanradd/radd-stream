package com.raddstream.app.images

import android.os.SystemClock
import android.util.Log
import coil.request.ErrorResult
import coil.request.EventListener
import coil.request.ImageRequest
import coil.request.SuccessResult
import java.util.concurrent.ConcurrentHashMap

/**
 * DIAGNOSTIC ONLY (poster-diag build, 2026-11-13): observes every Coil request so a device
 * session can prove whether the image loader ever fired, and what it got back. It changes
 * NOTHING about loading — no timeout, no client, no cache, no retry is touched; the loader
 * this listener is attached to is built with Coil's own defaults (see
 * [com.raddstream.app.RaddStreamApplication.newImageLoader]).
 *
 * Read it on the device with `adb logcat -s PosterDiag` (or the `tag:PosterDiag` filter):
 * - COIL_START   — a request reached Coil (URL + nothing else yet).
 * - COIL_SUCCESS — it decoded, with the elapsed time in ms.
 * - COIL_ERROR   — it failed, with the exception class + message and elapsed ms.
 * - COIL_CANCEL  — it was cancelled before finishing (e.g. the tile left the screen).
 *
 * If a poster shows its fallback initials and there is NO COIL_START line for its URL, the
 * request never reached Coil — look at the CatalogImage DECISION line for the same URL
 * instead (metered gate / allowlist / missing URL). If COIL_START exists but no
 * COIL_SUCCESS/COIL_ERROR follows, the request was still in flight when the session ended.
 */
object PosterDiagEventListener : EventListener() {

    private val startedAtMs = ConcurrentHashMap<Int, Long>()

    override fun onStart(request: ImageRequest) {
        startedAtMs[System.identityHashCode(request)] = SystemClock.elapsedRealtime()
        Log.d("PosterDiag", "COIL_START url=${request.data}")
    }

    override fun onSuccess(request: ImageRequest, result: SuccessResult) {
        Log.d("PosterDiag", "COIL_SUCCESS url=${request.data} elapsedMs=${elapsedMs(request)}")
    }

    override fun onError(request: ImageRequest, result: ErrorResult) {
        val throwable = result.throwable
        Log.d(
            "PosterDiag",
            "COIL_ERROR url=${request.data} elapsedMs=${elapsedMs(request)} " +
                "error=${throwable.javaClass.simpleName}: ${throwable.message}",
        )
    }

    override fun onCancel(request: ImageRequest) {
        Log.d("PosterDiag", "COIL_CANCEL url=${request.data} elapsedMs=${elapsedMs(request)}")
    }

    private fun elapsedMs(request: ImageRequest): Long {
        val start = startedAtMs.remove(System.identityHashCode(request)) ?: return -1
        return SystemClock.elapsedRealtime() - start
    }
}
