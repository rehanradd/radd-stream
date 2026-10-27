package com.raddstream.app.viewmodel

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * `KeepPlayback.route` is the whole decision behind a Play tap on an in-app keep, and it is pure,
 * so the two ways it can go wrong are testable without a device: playing a keep over the network
 * while its bytes sit complete on the disk, or navigating to the local player on bytes the engine
 * cannot actually serve.
 */
class KeepPlaybackTest {

    @Test
    fun `complete local bytes win over the redirector handle`() {
        val route = KeepPlayback.route(
            localUri = "http://127.0.0.1:41531/file",
            streamHandle = "opaque-handle",
            playable = true,
        )
        assertEquals(KeepRoute.Local("http://127.0.0.1:41531/file"), route)
    }

    @Test
    fun `a keep with no local file still plays through its handle`() {
        val route = KeepPlayback.route(localUri = null, streamHandle = "opaque-handle", playable = true)
        assertEquals(KeepRoute.Stream("opaque-handle"), route)
    }

    @Test
    fun `an engine that returns an empty address is treated as no address at all`() {
        // The proxy could in principle hand back a blank string; a blank URL in the local player
        // would open a black screen, so routing must read it as "nothing local".
        val route = KeepPlayback.route(localUri = "", streamHandle = "opaque-handle", playable = true)
        assertEquals(KeepRoute.Stream("opaque-handle"), route)
    }

    @Test
    fun `local bytes play even when the row never got a handle`() {
        // A task written before the keep was resolved has no handle, so `playable` is false —
        // but the file is here, and that is what a tap should use.
        val route = KeepPlayback.route(localUri = "http://127.0.0.1:41531/file", streamHandle = null, playable = false)
        assertEquals(KeepRoute.Local("http://127.0.0.1:41531/file"), route)
    }

    @Test
    fun `nothing playable is its own answer, not a silent stream`() {
        assertEquals(KeepRoute.NothingPlayable, KeepPlayback.route(localUri = null, streamHandle = null, playable = false))
        assertEquals(KeepRoute.NothingPlayable, KeepPlayback.route(localUri = null, streamHandle = "opaque-handle", playable = false))
    }
}
