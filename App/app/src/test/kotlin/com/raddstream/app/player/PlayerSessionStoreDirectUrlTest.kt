package com.raddstream.app.player

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class PlayerSessionStoreDirectUrlTest {

    @Test
    fun stagedUrlReadsBackUnderItsKey() {
        val store = PlayerSessionStore()
        val key = store.stageDirectUrl("https://cdn.example.com/movies/hero.mp4")
        assertTrue(key.startsWith("direct-"))
        assertEquals("https://cdn.example.com/movies/hero.mp4", store.peekDirectUrl(key))
    }

    @Test
    fun peekDoesNotConsume() {
        val store = PlayerSessionStore()
        val key = store.stageDirectUrl("https://cdn.example.com/movies/hero.mp4")
        store.peekDirectUrl(key)
        assertEquals("https://cdn.example.com/movies/hero.mp4", store.peekDirectUrl(key))
    }

    @Test
    fun twoStagesGetDifferentKeys() {
        val store = PlayerSessionStore()
        val first = store.stageDirectUrl("https://cdn.example.com/movies/a.mp4")
        val second = store.stageDirectUrl("https://cdn.example.com/movies/b.mp4")
        assertNotEquals(first, second)
        assertEquals("https://cdn.example.com/movies/b.mp4", store.peekDirectUrl(second))
    }

    @Test
    fun unknownKeyReadsNull() {
        val store = PlayerSessionStore()
        assertNull(store.peekDirectUrl("direct-nope"))
        assertNull(store.peekDirectUrl(null))
        assertNull(store.peekDirectUrl("   "))
    }

    @Test
    fun oldestEntryEvictedPastTheCap() {
        val store = PlayerSessionStore()
        val first = store.stageDirectUrl("https://cdn.example.com/movies/first.mp4")
        repeat(24) { i -> store.stageDirectUrl("https://cdn.example.com/movies/f$i.mp4") }
        assertNull(store.peekDirectUrl(first))
    }
}
