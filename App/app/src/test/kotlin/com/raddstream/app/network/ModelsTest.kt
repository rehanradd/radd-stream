package com.raddstream.app.network

import com.raddstream.app.data.local.FavoritePost
import com.raddstream.app.network.models.Post
import com.raddstream.app.network.models.PostDetail
import com.raddstream.app.network.models.PostDetailResponse
import com.raddstream.app.network.models.PostsResponse
import com.raddstream.app.network.models.StatsResponse
import com.raddstream.app.network.models.StreamResponse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ModelsTest {
    // Decode with the app's real Gson configuration (lenient Int/Boolean adapters); a bare
    // Gson() does not match production and crashes on the 0/1-vs-boolean wire spellings.
    private val gson = buildRaddGson()

    @Test
    fun `posts response maps backend pagination and result names`() {
        val json = """
            {
              "page": 2,
              "limit": 20,
              "total": 31,
              "total_pages": 2,
              "results": [{
                "id": 42,
                "title": "Example title",
                "clean_title": "example title",
                "year": 2024,
                "content_type": "movie",
                "poster_url": "https://images.example/poster.jpg",
                "imdb_rating": "7.4",
                "source_site": "catalog"
              }]
            }
        """.trimIndent()

        val response = gson.fromJson(json, PostsResponse::class.java)

        assertEquals(2, response.page)
        assertEquals(31, response.total)
        assertEquals(2, response.totalPages)
        assertEquals(1, response.results.size)
        // year is numeric on the wire (INTEGER affinity), so it decodes to Int.
        assertEquals(2024, response.results.single().year)
        assertEquals("example title", response.results.single().cleanTitle)
    }

    @Test
    fun `post model accepts year ranges and optional metadata`() {
        val post = gson.fromJson(
            """{"id":1,"title":"Example series","year":"2017–2019","content_type":"series"}""",
            Post::class.java,
        )

        // A text year range must not crash decoding; LenientIntAdapter takes the first
        // digit run ("2017–2019" → 2017) and everything unparseable would be null.
        assertEquals(2017, post.year)
        assertNull(post.posterUrl)
        assertNull(post.imdbRating)
    }

    @Test
    fun `post detail response maps releases and sources properly`() {
        val json = """
            {
              "success": true,
              "data": {
                "id": 101,
                "title": "Inception (2010)",
                "clean_title": "Inception",
                "year": "2010",
                "content_type": "movie",
                "imdb_rating": "8.8",
                "releases": [
                  {
                    "id": 1,
                    "post_id": 101,
                    "quality": "1080p WEB-DL",
                    "sources": [
                      {
                        "id": 501,
                        "release_id": 1,
                        "stream_id": "s1.abcdef",
                        "play_url": "http://127.0.0.1:8080/api/v1/stream?id=s1.abcdef",
                        "label": "Fast direct",
                        "kind": "direct",
                        "status": "active"
                      }
                    ]
                  }
                ]
              }
            }
        """.trimIndent()

        val response = gson.fromJson(json, PostDetailResponse::class.java)

        assertTrue(response.success)
        assertNotNull(response.data)
        val data = response.data!!
        assertEquals(101, data.id)
        assertEquals("Inception", data.cleanTitle)
        assertEquals(1, data.releases.size)
        val release = data.releases.first()
        assertEquals("1080p WEB-DL", release.quality)
        assertEquals(1, release.sources.size)
        val source = release.sources.first()
        assertEquals("s1.abcdef", source.streamId)
        assertEquals("Fast direct", source.label)
        assertEquals("direct", source.kind)
    }

    @Test
    fun `stream response carries only our own handle and never a served address`() {
        val json = """
            {
              "success": true,
              "stream_id": "s1.abcdef",
              "kind": "direct",
              "mime_type": "video/mp4",
              "expires_in": 3600,
              "url": "https://upstream.example/video.mp4",
              "service": "pixeldrain"
            }
        """.trimIndent()

        val response = gson.fromJson(json, StreamResponse::class.java)

        assertTrue(response.success)
        assertEquals("s1.abcdef", response.streamId)
        assertEquals(3600L, response.expiresIn)
        // The model has no url/service field at all: a payload key the server no longer
        // sends must not be reachable through the wire type either.
        assertEquals(emptyList<String>(), StreamResponse::class.java.declaredFields
            .map { it.name }.filter { it in setOf("url", "service", "sourceName") })
    }

    @Test
    fun `favorite post maps to and from post model correctly`() {
        val post = Post(
            id = 77,
            title = "Sample Movie",
            cleanTitle = "Sample",
            year = 2023,
            contentType = "movie",
            posterUrl = "https://example.com/poster.jpg",
            imdbRating = "8.1",
        )

        val favorite = FavoritePost.fromPost(post)
        assertEquals(77, favorite.id)
        assertEquals("Sample", favorite.cleanTitle)

        val convertedBack = favorite.toPost()
        assertEquals(post.id, convertedBack.id)
        assertEquals(post.title, convertedBack.title)
        assertEquals(post.cleanTitle, convertedBack.cleanTitle)
        assertEquals(post.imdbRating, convertedBack.imdbRating)
    }

    @Test
    fun `empty posts response defaults to an empty result list`() {
        val response = gson.fromJson(
            """{"page":1,"limit":20,"total":0,"total_pages":1,"results":[]}""",
            PostsResponse::class.java,
        )

        assertTrue(response.results.isEmpty())
        assertEquals(0, response.total)
    }

    @Test
    fun `stats response maps snake case field names`() {
        val response = gson.fromJson(
            """{"posts":500,"releases":1200,"sources":3600,"active_sources":42,"resumable_sources":8,"temporary_sources":3}""",
            StatsResponse::class.java,
        )

        assertEquals(500, response.posts)
        assertEquals(42, response.activeSources)
        assertEquals(8, response.resumableSources)
        assertEquals(3, response.temporarySources)
    }
}
