package com.raddstream.app.network

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.raddstream.app.data.ServerSettingsRepository
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * Batch B detail regression (2026-11-14): `currentBaseUrl()` re-read DataStore and
 * re-normalized on every call, so a failure of that read AFTER a successful detail
 * response killed the whole load — the base-URL read sits after the network call in
 * `CatalogRepository.getWorkDetailV2`, and its narrow catch let the throw escape to
 * the detail error screen even though the API had answered 200. The Retrofit client
 * is already built from this same URL and cached, so a populated cache must answer
 * without touching storage.
 */
@RunWith(RobolectricTestRunner::class)
class ApiProviderBaseUrlTest {

    private fun provider(): Pair<ApiProvider, ServerSettingsRepository> {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val settings = ServerSettingsRepository(context)
        return ApiProvider(settings) to settings
    }

    @Test
    fun `a cached base URL answers without re-reading storage`() = runBlocking {
        val (apiProvider, settings) = provider()
        settings.saveServerUrl("https://raddstream.duckdns.org")
        // Builds the client; populates the cache. No network.
        apiProvider.current()
        // The stored value is now malformed — a fresh read would throw.
        settings.saveServerUrl("not a url")
        assertEquals("https://raddstream.duckdns.org/", apiProvider.currentBaseUrl())
    }

    @Test
    fun `a cold start still reads the stored URL`() = runBlocking {
        val (apiProvider, settings) = provider()
        settings.saveServerUrl("https://raddstream.duckdns.org")
        assertEquals("https://raddstream.duckdns.org/", apiProvider.currentBaseUrl())
    }

    @Test
    fun `a cold start with a malformed stored URL still throws`() {
        val (apiProvider, settings) = provider()
        runBlocking { settings.saveServerUrl("not a url") }
        assertThrows(IllegalArgumentException::class.java) {
            runBlocking { apiProvider.currentBaseUrl() }
        }
    }
}
