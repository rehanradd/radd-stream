package com.raddstream.app.repository

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.network.ApiProvider
import com.raddstream.app.network.RaddStreamApi
import java.io.IOException
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * Session 157 (2026-11-13): the detail first tap must survive a provider
 * failure. Sauce Labs S4 showed Tarzan's first tap dying with no request
 * on the wire and the hard "Failed to load details" error, while the
 * manual Retry loaded the same title — a failure to ask, not a server
 * refusal. A provider or client-build failure on the detail path must
 * answer null, the shape the caller's null-retry already re-asks, and a
 * cancelled load must still abort at once instead of being swallowed
 * into that null.
 *
 * The provider is a fake subclass: the production [ApiProvider] throws
 * only through [ApiProvider.current], so the fake overrides that one
 * call and never touches the network. Robolectric (x86_64-only like
 * every Robolectric suite): the repository needs a real
 * [ServerSettingsRepository], which needs an application context.
 */
@RunWith(RobolectricTestRunner::class)
class CatalogDetailProviderFailureTest {

    private class ThrowingApiProvider(
        settingsRepository: ServerSettingsRepository,
        private val error: Throwable,
    ) : ApiProvider(settingsRepository) {
        override suspend fun current(): RaddStreamApi = throw error
    }

    private fun repository(error: Throwable): CatalogRepository {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val settings = ServerSettingsRepository(context)
        return CatalogRepository(ThrowingApiProvider(settings, error), settings)
    }

    @Test
    fun `v2 detail answers null when the provider throws a bad address`() = runBlocking {
        val repository = repository(IllegalArgumentException("Enter a valid server URL."))
        assertNull(repository.getWorkDetailV2(132312))
    }

    @Test
    fun `v1 detail answers null when the provider throws a bad address`() = runBlocking {
        val repository = repository(IllegalArgumentException("Enter a valid server URL."))
        assertNull(repository.getPostDetail(157747))
    }

    @Test
    fun `v2 detail rethrows a cancelled load instead of answering null`() {
        val repository = repository(CancellationException("StandaloneCoroutine was cancelled"))
        assertThrows(CancellationException::class.java) {
            runBlocking { repository.getWorkDetailV2(132312) }
        }
    }

    @Test
    fun `v2 detail rethrows the java util cancellation instead of answering null`() {
        val repository = repository(java.util.concurrent.CancellationException("cancelled"))
        assertThrows(java.util.concurrent.CancellationException::class.java) {
            runBlocking { repository.getWorkDetailV2(132312) }
        }
    }

    @Test
    fun `v2 detail still answers null for the provider not ready error`() = runBlocking {
        val repository = repository(IllegalStateException("Connect to a catalog server first."))
        assertNull(repository.getWorkDetailV2(132312))
    }

    /**
     * Session 158 (S5): the S5 Tarzan thrower was never identified from
     * code alone — every RuntimeException on the pre-network path is
     * already caught, so the remaining class is a CHECKED exception the
     * catches do not name (a TimeoutException, a CertificateException
     * from the TLS stack). Whatever its member, a failure to ask must
     * answer null so the caller's null-retry re-asks, not hard-fail the
     * first tap — and a dead socket must still propagate on the v1 path,
     * where the caller tells a refusal from a failure to ask by it.
     */
    @Test
    fun `v2 detail answers null when the provider throws a checked timeout`() = runBlocking {
        val repository = repository(java.util.concurrent.TimeoutException("timed out"))
        assertNull(repository.getWorkDetailV2(132312))
    }

    @Test
    fun `v1 detail answers null when the provider throws a checked timeout`() = runBlocking {
        val repository = repository(java.util.concurrent.TimeoutException("timed out"))
        assertNull(repository.getPostDetail(157747))
    }

    @Test
    fun `v1 detail still propagates a dead socket instead of answering null`() {
        val repository = repository(IOException("Connection reset"))
        assertThrows(IOException::class.java) {
            runBlocking { repository.getPostDetail(157747) }
        }
    }

    @Test
    fun `v2 detail still answers null for a dead socket`() = runBlocking {
        val repository = repository(IOException("Connection reset"))
        assertNull(repository.getWorkDetailV2(132312))
    }
}
