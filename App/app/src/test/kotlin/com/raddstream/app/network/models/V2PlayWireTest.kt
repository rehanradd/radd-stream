package com.raddstream.app.network.models

import com.google.gson.Gson
import com.raddstream.app.player.CoverageType
import com.raddstream.app.player.toPlayerCoverage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * POST /api/v2/play wire shapes (plan §5 step 13, App/AGENTS.md §13.7): one JSON
 * deserialization test per new data class. The fixture is the shape the server
 * ACTUALLY sends (`catalog_api.play_bundle`) — tiers/candidates/coverage, no
 * `renditions` — verified against the live server code, not the §8.1 spec shape.
 */
class V2PlayWireTest {

    private val gson = Gson()
    private val baseUrl = "http://92.4.95.252"

    private val responseJson = """
        {
          "target": {"kind": "episode", "episode_id": 42, "work_id": 1234, "release_id": 555,
                     "work_type": "series", "season": 1, "episode": 2, "absolute": 2},
          "work_id": 1234,
          "release_id": 555,
          "print_label": "1080p WEB-DL",
          "tiers": [{"band": "1080p", "quality": "1080p", "label": "Full HD · H265",
                     "mode": "play", "playable": true,
                     "link": {"link_id": 11, "stream_id": "tok1", "label": "Fast direct",
                              "kind": "direct", "playability": "stream", "playable": true,
                              "group": 0, "state": "active", "dead": false, "tier": 1,
                              "protocol": "hls", "content_type": "application/vnd.apple.mpegurl",
                              "ephemeral": true, "resumable": true, "accepts_ranges": true,
                              "size_bytes": 2405181686, "rank_score": 830, "http_status": 200,
                              "latency_ms": 120, "speed_mbps": 42.5, "measured": true,
                              "score_scale": "measured"},
                     "copies": 3, "backup_handles": ["tok2", "tok3"]}],
          "auto": {"band": "1080p", "playable": true},
          "coverage": {"type": "season_pack", "season_number": 1, "episode_first": 1,
                       "episode_last": 2,
                       "enumerated_episodes": [
                         {"episode_id": 41, "number": 1, "absolute_number": 1, "season_number": 1,
                          "ordinal": 1, "offset_seconds": 0, "chapter_title": "Pilot"},
                         {"episode_id": 42, "number": 2, "absolute_number": 2, "season_number": 1,
                          "ordinal": 2, "offset_seconds": 1800, "chapter_title": "Second"}],
                       "offset_seconds": 1800, "chapter_title": "Second", "ordinal": 2,
                       "source": "cat_release_episodes", "needs_offset_calibration": false,
                       "pack_warning": null},
          "stream_candidates": [
            {"link_id": 11, "stream_id": "tok1", "label": "Fast direct", "kind": "direct",
             "playability": "stream", "playable": true, "group": 0, "state": "active",
             "dead": false, "tier": 1, "protocol": "hls",
             "content_type": "application/vnd.apple.mpegurl", "ephemeral": true,
             "resumable": true, "accepts_ranges": true, "size_bytes": 2405181686,
             "rank_score": 830, "http_status": 200, "latency_ms": 120, "speed_mbps": 42.5,
             "measured": true, "score_scale": "measured"},
            {"link_id": 12, "stream_id": "tok2", "label": "Standard", "kind": "direct",
             "playability": "stream", "playable": true, "group": 0, "state": "active",
             "dead": false, "tier": 1, "protocol": "progressive",
             "content_type": "video/mp4", "ephemeral": false,
             "resumable": false, "accepts_ranges": false, "size_bytes": 1800000000,
             "rank_score": 700, "http_status": 200, "latency_ms": 200, "speed_mbps": 20.0,
             "measured": true, "score_scale": "measured"}],
          "candidates": [],
          "download_options": [],
          "playable": true, "available": true, "reason": null, "protocol": "hls",
          "ephemeral": true, "candidate_count": 2, "dead_candidate_count": 0,
          "prefer": "quality", "device": null
        }
        """.trimIndent()

    @Test
    fun `decodes the servers real play response`() {
        val response = gson.fromJson(responseJson, WirePlayResponse::class.java)

        assertTrue(response.playable)
        assertEquals(555L, response.releaseId)
        assertEquals("1080p", response.tiers.firstOrNull()?.band)
        assertEquals(listOf("tok2", "tok3"), response.tiers.firstOrNull()?.backupHandles)
        assertEquals(2, response.streamCandidates.size)
        assertEquals("tok1", response.streamCandidates.firstOrNull()?.streamId)
        assertEquals(830, response.streamCandidates.firstOrNull()?.rankScore)
        assertEquals(2, response.target?.episode)
        assertEquals(1, response.target?.season)
    }

    @Test
    fun `maps to the domain bundle in server order with our own redirector`() {
        val response = gson.fromJson(responseJson, WirePlayResponse::class.java)
        val bundle = response.toDomain(baseUrl)

        assertEquals(555L, bundle.printId)
        assertEquals(2, bundle.renditions.size)
        val winner = bundle.renditions[0]
        assertEquals("tok1", winner.streamId)
        assertEquals("http://92.4.95.252/api/v1/stream?id=tok1", winner.playUrl)
        assertEquals(830, winner.linkScore)
        assertEquals(PlayProtocol.HLS, winner.protocol)
        assertEquals(Playability.STREAM, winner.playability)
        assertEquals("Full HD · H265", winner.qualityLabel)
        assertTrue(winner.resumable)
        assertTrue(winner.ephemeral)
        val runnerUp = bundle.renditions[1]
        assertEquals("tok2", runnerUp.streamId)
        assertEquals(PlayProtocol.PROGRESSIVE, runnerUp.protocol)
        assertFalse(runnerUp.resumable)
    }

    @Test
    fun `maps the coverage block to chapter data`() {
        val response = gson.fromJson(responseJson, WirePlayResponse::class.java)
        val coverage = response.coverage!!.toPlayerCoverage()

        assertEquals(CoverageType.SEASON_PACK, coverage.type())
        assertTrue(coverage.isPacked())
        assertEquals(1, coverage.firstEpisode)
        assertEquals(2, coverage.lastEpisode)
        assertEquals(1800, coverage.offsetSeconds)
        assertEquals(2, coverage.episodes.size)
        assertEquals(1800, coverage.episodes[1].offsetSeconds)
        assertEquals("Second", coverage.episodes[1].chapterTitle)
        assertEquals(1800, coverage.serverOffsetFor(2))
        assertEquals(0, coverage.serverOffsetFor(1))
    }

    @Test
    fun `a non-playable print decodes with an empty ladder`() {
        val response = gson.fromJson(
            """{"release_id": 555, "playable": false, "available": false,
                "reason": "no_playable_source", "stream_candidates": [],
                "candidates": [], "download_options": [], "tiers": []}""".trimIndent(),
            WirePlayResponse::class.java,
        )
        assertFalse(response.playable)
        assertTrue(response.toDomain(baseUrl).renditions.isEmpty())
    }

    @Test
    fun `the request names the print, not the work`() {
        val json = gson.toJson(WirePlayRequest(releaseId = 555, prefer = "quality"))
        assertTrue(json.contains("\"release_id\":555"))
        assertTrue(json.contains("\"prefer\":\"quality\""))
        assertFalse(json.contains("episode_id"))
    }
}
