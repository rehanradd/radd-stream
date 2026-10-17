package com.raddstream.app.network

import com.google.gson.Gson
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
    private val gson = Gson()

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
        assertEquals("2024", response.results.single().year)
        assertEquals("example title", response.results.single().cleanTitle)
    }

    @Test
    fun `post model accepts year ranges and optional metadata`() {
        val post = gson.fromJson(
            """{"id":1,"title":"Example series","year":"2017–2019","content_type":"series"}""",
            Post::class.java,
        )

        assertEquals("2017–2019", post.year)
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
                        "source_name": "⚡ Gofile",
                        "service": "gofile",
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
        assertEquals("⚡ Gofile", release.sources.first().sourceName)
    }

    @Test
    fun `stream response maps url and temporary status`() {
        val json = """
            {
              "success": true,
              "url": "https://stream.example/video.mp4",
              "service": "pixeldrain",
              "is_temporary": 0
            }
        """.trimIndent()

        val response = gson.fromJson(json, StreamResponse::class.java)

        assertTrue(response.success)
        assertEquals("https://stream.example/video.mp4", response.url)
        assertEquals("pixeldrain", response.service)
        assertEquals(0, response.isTemporary)
    }

    @Test
    fun `favorite post maps to and from post model correctly`() {
        val post = Post(
            id = 77,
            title = "Sample Movie",
            cleanTitle = "Sample",
            year = "2023",
            contentType = "movie",
            posterUrl = "https://example.com/poster.jpg",
            imdbRating = "8.1",
            sourceSite = "vegamovies",
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
