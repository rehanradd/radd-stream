package com.raddstream.app.network.models

import com.google.gson.Gson
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * GET /api/v2/browse, /api/v2/search and /api/v2/works/{id} wire shapes
 * (App/AGENTS.md §13.7): one JSON deserialization test per new data class.
 * Every fixture is the shape `Fast_Fetch/catalog_api.py` ACTUALLY sends —
 * a structured `poster` object, `images:{poster,backdrops}`, prints under
 * `prints[]` with nested `audio`/`subtitles`/`coverage` and `release_id`,
 * links keyed by `link_id` with no `play_url` — NOT the shapes `V2Wire.kt`
 * guessed at. The mappings are pinned too: the negative-id sentinel, the
 * anime → series + animated rule, and the client-built option groups.
 */
class V2CatalogWireTest {

    private val gson = Gson()
    private val baseUrl = "https://raddstream.duckdns.org"

    @Test
    fun `browse item decodes the structured poster and the negative-id sentinel`() {
        val json = """
            {"ok": true, "items": [
              {"id": 1234, "work_ref": "imdb:tt15398776", "title": "Oppenheimer",
               "year": 2023, "work_type": "movie", "animated": false,
               "poster": {"src": "https://raddstream.duckdns.org/api/v1/art?id=abc&k=poster&n=0",
                          "kind": "poster", "index": 0},
               "rating": "8.4", "genres": ["Drama", "History"], "languages": ["English"],
               "country": "US", "industry": "hollywood", "site_count": 3, "seasons": 0,
               "episodes": 0, "prints": 5, "quality_max": "1080p",
               "best_quality_score": 820,
               "available": {"stream": true, "download": true, "any": true, "state": "available"},
               "flags": [], "identity_suspect": false, "entitlement": {"model": "free"}}
            ], "next_cursor": "eyJpZCI6MTIzNH0=", "has_more": true, "total_estimate": 42, "count": 1}
        """.trimIndent()
        val resp = gson.fromJson(json, WireBrowseResponse::class.java)
        assertTrue(resp.ok)
        assertEquals(1, resp.items.size)
        assertEquals("eyJpZCI6MTIzNH0=", resp.nextCursor)
        assertTrue(resp.hasMore)
        assertEquals(42, resp.totalEstimate)
        val item = resp.items[0]
        assertEquals("https://raddstream.duckdns.org/api/v1/art?id=abc&k=poster&n=0", item.poster?.src)
        assertEquals("poster", item.poster?.kind)
        assertEquals("8.4", item.rating)
        val post = item.toPost()
        assertEquals(-1234, post.id)
        assertEquals(1234L, post.workId)
        assertEquals("Oppenheimer", post.title)
        assertEquals("movie", post.contentType)
        assertFalse(post.isAnimated == true)
        assertEquals("imdb:tt15398776", post.workRef)
        assertEquals(5, post.releaseCount)
    }

    @Test
    fun `anime becomes series plus animated, never the anime content type`() {
        val item = gson.fromJson(
            """{"id": 77, "title": "Naruto", "work_type": "anime", "animated": true}""",
            WireBrowseItem::class.java,
        )
        val post = item.toPost()
        assertEquals("series", post.contentType)
        assertTrue(post.isAnimated == true)
        assertEquals(-77, post.id)
        assertEquals(77L, post.workId)
    }

    @Test
    fun `a browse body without items decodes empty, never null`() {
        val resp = gson.fromJson("""{"ok": true}""", WireBrowseResponse::class.java)
        assertTrue(resp.items.isEmpty())
        assertFalse(resp.hasMore)
        assertNull(resp.nextCursor)
    }

    @Test
    fun `work detail decodes nested prints and builds releases plus option groups`() {
        val json = """
            {"ok": true,
             "work": {"id": 1234, "work_ref": "imdb:tt15398776", "title": "Oppenheimer",
                      "original_title": "Oppenheimer", "year": 2023, "work_type": "movie",
                      "animated": false, "synopsis": "The story of J. Robert Oppenheimer.",
                      "genres": ["Drama"], "languages": ["English"], "country": "US",
                      "industry": "hollywood", "rating": "8.4", "runtime_minutes": 180,
                      "images": {"poster": {"src": "https://image.tmdb.org/t/p/w500/abc.jpg", "kind": "poster", "index": 0},
                                 "backdrops": [{"src": "https://image.tmdb.org/t/p/w1280/def.jpg", "kind": "backdrop", "index": 0}]},
                      "site_count": 3, "print_count": 1, "episode_count": 0, "season_count": 0,
                      "quality_max": "1080p", "best_quality_score": 820},
             "identity": {"imdb_id": "tt15398776", "tmdb_id": 872585, "tvdb_id": null, "work_type": "movie"},
             "seasons": [],
             "prints": [{"release_id": 9001, "work_id": 1234, "print_label": "Oppenheimer 2023 1080p BluRay",
                         "label": "Oppenheimer 2023 1080p BluRay",
                         "coverage": {"type": "whole_work", "season_number": null, "part_number": null,
                                      "episode_range": null, "episode_first": null, "episode_last": null,
                                      "enumerated": false},
                         "resolution": "1080p", "quality_label": "1080p", "source_tag": "bluray",
                         "codec": "x264", "bit_depth": 8, "hdr": [], "container": "mkv",
                         "edition": null, "print_version": 1, "release_group": "YIFY",
                         "size_bytes": 2500000000, "size_per_episode_bytes": null,
                         "audio": {"languages": ["English", "Hindi"], "channels": "5.1",
                                   "codecs": ["aac"], "dual_audio": true},
                         "subtitles": {"mode": "soft", "languages": ["English"]},
                         "watermarked": false, "official_print": true, "quality_score": 820,
                         "flags": [], "counts": {"links": 2, "streamable": 2, "downloadable": 1},
                         "created_at": "2026-11-09T10:00:00",
                         "links": [{"link_id": 5001, "release_id": 9001, "work_id": 1234,
                                    "stream_id": "s.abcdef1234", "label": "1080p", "kind": "file",
                                    "playability": "stream", "playable": true, "group": 1,
                                    "state": "active", "dead": false, "tier": 1, "protocol": "https",
                                    "content_type": "video/x-matroska", "ephemeral": false,
                                    "expires_at": 1800000000.0, "resumable": true,
                                    "accepts_ranges": true, "size_bytes": 2500000000,
                                    "rank_score": 90, "http_status": 200, "latency_ms": 120,
                                    "speed_mbps": 12.5, "measured": true,
                                    "score_scale": "v2", "last_evidence_at": "2026-11-09T09:00:00"},
                                   {"link_id": 5002, "release_id": 9001, "work_id": 1234,
                                    "stream_id": "s.abcdef5678", "label": "1080p mirror", "kind": "file",
                                    "playability": "stream", "playable": true, "group": 1,
                                    "state": "active", "dead": false, "tier": 2, "protocol": "https",
                                    "content_type": "video/x-matroska", "ephemeral": false,
                                    "expires_at": null, "resumable": true, "accepts_ranges": true,
                                    "size_bytes": 2500000000, "rank_score": 70, "http_status": 200,
                                    "latency_ms": 300, "speed_mbps": 5.0, "measured": true,
                                    "score_scale": "v2", "last_evidence_at": "2026-11-09T09:00:00"}]}],
             "availability": {"stream": true, "download": true, "any": true, "state": "available"},
             "entitlements": [], "flags": [], "identity_suspect": false}
        """.trimIndent()
        val resp = gson.fromJson(json, WireWorkDetailResponse::class.java)
        assertTrue(resp.ok)
        assertEquals("tt15398776", resp.identity?.imdbId)
        assertEquals(872585, resp.identity?.tmdbId)
        val detail = resp.toPostDetail(baseUrl, v1PostId = 4242, castNames = "Cillian Murphy, Emily Blunt")
        assertNotNull(detail)
        detail!!
        assertEquals(4242, detail.id)
        assertEquals("Oppenheimer", detail.title)
        assertEquals("Cillian Murphy, Emily Blunt", detail.castNames)
        assertEquals("tt15398776", detail.imdbId)
        assertEquals("https://image.tmdb.org/t/p/w500/abc.jpg", detail.posterUrl)
        assertEquals(1, detail.releases.size)
        val release = detail.releases[0]
        assertEquals(9001, release.id)
        assertEquals("1080p", release.quality)
        assertEquals("English|Hindi", release.languages)
        assertEquals(2, release.sources.size)
        val source = release.sources[0]
        assertEquals("s.abcdef1234", source.streamId)
        assertEquals("$baseUrl/api/v1/stream?id=s.abcdef1234", source.playUrl)
        assertEquals(true, source.playable)
        assertEquals(true, source.resumable)
        assertEquals(1800000000.0, source.expiresAt ?: 0.0, 0.001)
        // The client-built ladder: one whole-work group, one 1080p tier, winner by rank.
        assertEquals(1, detail.optionGroups.size)
        val group = detail.optionGroups[0]
        assertNull(group.season)
        assertNull(group.episode)
        assertEquals(1, group.tiers.size)
        val tier = group.tiers[0]
        assertEquals("1080p", tier.band)
        assertEquals("Full HD", tier.label)
        assertEquals("play", tier.mode)
        assertTrue(tier.playable)
        assertEquals("s.abcdef1234", tier.link?.streamId)
        assertEquals(listOf("s.abcdef5678"), tier.backupHandles)
        assertNotNull(group.auto)
        assertEquals("s.abcdef1234", group.auto?.streamId)
    }

    @Test
    fun `a link with no ledger id is not playable even though it is not dead`() {
        val link = gson.fromJson(
            """{"link_id": 9, "stream_id": "s.deadbeef", "playability": "stream",
                "playable": false, "group": 1, "state": "unknown", "dead": false}""",
            WireDetailLink::class.java,
        )
        val source = link.toSourceDetail(baseUrl, releaseId = 1L)
        assertEquals(false, source.playable)
        // playability "stream" is not downloadable — and the wire verdict, not
        // `dead`, is what the ladder trusts.
        assertEquals(false, source.downloadable)
    }

    @Test
    fun `a detail without a work maps to null, and missing keys decode empty`() {
        val resp = gson.fromJson("""{"ok": true}""", WireWorkDetailResponse::class.java)
        assertNull(resp.toPostDetail(baseUrl))
        assertTrue(resp.prints.isEmpty())
        assertTrue(resp.seasons.isEmpty())
        val empty = gson.fromJson("""{}""", WireDetailPrint::class.java)
        assertTrue(empty.links.isEmpty())
        assertTrue(empty.hdr.isEmpty())
    }

    @Test
    fun `bandOf follows the server rule, bare HD is 720p never 1080p`() {
        assertEquals("2160p", bandOf("2160p", null, null))
        assertEquals("2160p", bandOf(null, "4K HDR", null))
        assertEquals("1080p", bandOf("1080p BluRay", null, null))
        assertEquals("720p", bandOf(null, null, "HD"))
        assertEquals("720p", bandOf("HDTV", null, null))
        assertEquals("480p", bandOf("480p", null, null))
        assertEquals("sd", bandOf("CAM", null, null))
        assertEquals("unspecified", bandOf(null, null, null))
    }

    @Test
    fun `resolve decodes the re-resolved link facts`() {
        val resp = gson.fromJson(
            """{"ok": true, "link_ref": "l.123", "stream_id": "s.abcdef1234",
                "kind": "file", "mime_type": "video/mp4", "file_size_bytes": 1500000000,
                "resumable": true, "expires_in": 3600, "refreshed": true}""",
            WireResolveResponse::class.java,
        )
        assertTrue(resp.ok)
        assertEquals("s.abcdef1234", resp.streamId)
        assertEquals(1500000000L, resp.fileSizeBytes)
        assertEquals(3600L, resp.expiresIn)
    }
}
