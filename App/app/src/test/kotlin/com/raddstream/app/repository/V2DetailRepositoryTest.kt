package com.raddstream.app.repository

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.network.ApiProvider
import com.raddstream.app.network.RaddStreamApi
import com.raddstream.app.network.buildRaddGson
import com.raddstream.app.network.models.PostDetailResponse
import com.raddstream.app.network.models.PostsResponse
import com.raddstream.app.network.models.WireWorkDetailResponse
import java.lang.reflect.Proxy
import kotlin.coroutines.Continuation
import kotlin.coroutines.intrinsics.COROUTINE_SUSPENDED
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * Second probe for the Robo Batch B detail regression (works 7681/9048):
 * the mapping test ([V2DetailRegressionTest]) proves decode + `toPostDetail`
 * + layout do not throw on the exact live answers, so this test drives the
 * REAL `CatalogRepository.getWorkDetailV2` with a fake transport serving
 * those same answers — the `work_ref` bridge, the base-URL read and the
 * try/catch behaviour included. If this returns null or throws, the
 * repository is where the detail dies; if it passes, the fault is above the
 * repository (ViewModel) or in the answer the device received (not the one
 * replayed here).
 */
@RunWith(RobolectricTestRunner::class)
class V2DetailRepositoryTest {

    private fun loadResponse(name: String): WireWorkDetailResponse {
        val json = javaClass.classLoader!!.getResourceAsStream("v2detail/$name")!!
            .bufferedReader().readText()
        return buildRaddGson().fromJson(json, WireWorkDetailResponse::class.java)
    }

    private class FakeApiProvider(
        settingsRepository: ServerSettingsRepository,
        private val workDetail: WireWorkDetailResponse,
    ) : ApiProvider(settingsRepository) {
        var bridgePostsCalled = false

        override suspend fun current(): RaddStreamApi {
            @Suppress("UNCHECKED_CAST")
            return Proxy.newProxyInstance(
                javaClass.classLoader,
                arrayOf(RaddStreamApi::class.java),
            ) { _, method, args ->
                val continuation = args!!.last() as Continuation<Any?>
                when (method.name) {
                    "getWorkDetail" -> continuation.resume(workDetail)
                    "getPosts" -> {
                        bridgePostsCalled = true
                        continuation.resume(PostsResponse(results = emptyList()))
                    }
                    "getPostDetail" -> continuation.resume(PostDetailResponse(success = false, data = null))
                    else -> continuation.resumeWithException(
                        UnsupportedOperationException("unused in this test: ${method.name}"),
                    )
                }
                COROUTINE_SUSPENDED
            } as RaddStreamApi
        }
    }

    private fun repositoryFor(workDetail: WireWorkDetailResponse): Pair<CatalogRepository, FakeApiProvider> {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val settings = ServerSettingsRepository(context)
        runBlocking { settings.saveServerUrl("https://raddstream.duckdns.org") }
        val provider = FakeApiProvider(settings, workDetail)
        return CatalogRepository(provider, settings) to provider
    }

    @Test
    fun `Scarpetta resolves through the repository with all 82 prints`() = runBlocking {
        val (repository, provider) = repositoryFor(loadResponse("work-7681-scarpetta.json"))
        val detail = repository.getWorkDetailV2(7681)
        assertNotNull(detail)
        assertEquals("Scarpetta", detail!!.title)
        assertEquals(82, detail.releases.size)
        assertTrue(provider.bridgePostsCalled)
    }

    @Test
    fun `The Penguin resolves through the repository with all 126 prints`() = runBlocking {
        val (repository, provider) = repositoryFor(loadResponse("work-9048-penguin.json"))
        val detail = repository.getWorkDetailV2(9048)
        assertNotNull(detail)
        assertEquals("The Penguin", detail!!.title)
        assertEquals(126, detail.releases.size)
        assertTrue(provider.bridgePostsCalled)
    }
}
