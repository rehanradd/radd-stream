package com.raddstream.app.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Session 155 (S2): the last Media3 start error is kept on the store so
 * the give-up report can name the cause. The device test returns no logcat,
 * so this is the only copy of the error that leaves the phone — the
 * `failed` report carries it, and a first frame or a new load clears it.
 */
class PlayerSessionStoreStartErrorTest {

    @Test
    fun `no start error at rest`() {
        assertNull(PlayerSessionStore().lastStartError.value)
    }

    @Test
    fun `a recorded start error reads back`() {
        val store = PlayerSessionStore()
        store.recordStartError("ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT ...")

        assertEquals(
            "ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT ...",
            store.lastStartError.value,
        )
    }

    @Test
    fun `clearing the start error returns null`() {
        val store = PlayerSessionStore()
        store.recordStartError("ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT ...")
        store.clearStartError()

        assertNull(store.lastStartError.value)
    }

    @Test
    fun `a blank or null start error records nothing`() {
        val store = PlayerSessionStore()
        store.recordStartError("   ")
        assertNull(store.lastStartError.value)
        store.recordStartError(null)
        assertNull(store.lastStartError.value)
    }

    @Test
    fun `a new start error replaces the old one`() {
        val store = PlayerSessionStore()
        store.recordStartError("ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT ...")
        store.recordStartError("ERROR_CODE_IO_BAD_HTTP_STATUS ...")

        assertEquals("ERROR_CODE_IO_BAD_HTTP_STATUS ...", store.lastStartError.value)
    }
}
