package com.raddstream.app.repository

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.network.ApiProvider
import com.raddstream.app.network.RaddStreamApi
import com.raddstream.app.network.models.Post
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * Batch B: the detail error screen names the title it could not load — but
 * only because the list routes remember the rows they already fetched. The
 * cache is in-memory and capped; a miss is simply "no fallback", never an
 * error. The provider here never answers (the test never asks the network),
 * so what is pinned is the cache alone.
 */
@RunWith(RobolectricTestRunner::class)
class CatalogPostCacheTest {

    private class ThrowingApiProvider(
        settingsRepository: ServerSettingsRepository,
    ) : ApiProvider(settingsRepository) {
        override suspend fun current(): RaddStreamApi =
            throw IllegalStateException("the cache test never reaches the network")
    }

    private fun repository(): CatalogRepository {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val settings = ServerSettingsRepository(context)
        return CatalogRepository(ThrowingApiProvider(settings), settings)
    }

    @Test
    fun `a cached post answers the title a failed detail needs`() {
        val repository = repository()
        assertNull(repository.cachedPost(101))
        repository.cachePosts(
            listOf(
                Post(id = 101, title = "Jawan", cleanTitle = "Jawan", year = 2023, contentType = "movie"),
            ),
        )
        assertEquals("Jawan", repository.cachedPost(101)?.cleanTitle)
        assertNull("an id never cached is simply no fallback", repository.cachedPost(999))
    }

    @Test
    fun `a post with no id is never cached`() {
        val repository = repository()
        repository.cachePosts(
            listOf(
                Post(id = 0, title = "Nameless", cleanTitle = "Nameless", contentType = "movie"),
            ),
        )
        assertNull(repository.cachedPost(0))
    }
}
