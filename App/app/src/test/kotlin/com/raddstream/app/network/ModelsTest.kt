package com.raddstream.app.network

import com.raddstream.app.data.local.FavoritePost
import com.raddstream.app.network.models.Codec
import com.raddstream.app.network.models.Container
import com.raddstream.app.network.models.CoverageType
import com.raddstream.app.network.models.EntitlementResponse
import com.raddstream.app.network.models.Edition
import com.raddstream.app.network.models.EntitlementModel
import com.raddstream.app.network.models.HdrFormat
import com.raddstream.app.network.models.LinkClassification
import com.raddstream.app.network.models.LinkKind
import com.raddstream.app.network.models.LinkState
import com.raddstream.app.network.models.Ownership
import com.raddstream.app.network.models.PaymentSubmitResponse
import com.raddstream.app.network.models.Playability
import com.raddstream.app.network.models.PlayProtocol
import com.raddstream.app.network.models.Post
import com.raddstream.app.network.models.PostDetail
import com.raddstream.app.network.models.PostDetailResponse
import com.raddstream.app.network.models.PostsResponse
import com.raddstream.app.network.models.PrintFlag
import com.raddstream.app.network.models.ProblemCode
import com.raddstream.app.network.models.Resolution
import com.raddstream.app.network.models.ScoreScale
import com.raddstream.app.network.models.SeasonArtwork
import com.raddstream.app.network.models.SeasonType
import com.raddstream.app.network.models.SourceTag
import com.raddstream.app.network.models.StatsResponse
import com.raddstream.app.network.models.StreamResponse
import com.raddstream.app.network.models.SubtitleMode
import com.raddstream.app.network.models.WorkFlag
import com.raddstream.app.network.models.WorkType
import com.raddstream.app.network.models.SourceDetail
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
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
    fun `season artwork decodes into distinct season and episode entries`() {
        val json = """
            {
              "success": true,
              "data": {
                "id": 202,
                "title": "Example Show",
                "content_type": "series",
                "season_artwork": [
                  {"kind": "season_poster", "season": 1, "episode": 0, "url": "https://image.tmdb.org/s1.jpg"},
                  {"kind": "season_poster", "season": 2, "episode": 0, "url": "https://image.tmdb.org/s2.jpg"},
                  {"kind": "episode_still", "season": 1, "episode": 1, "url": "https://image.tmdb.org/e1.jpg"}
                ]
              }
            }
        """.trimIndent()

        val data = gson.fromJson(json, PostDetailResponse::class.java).data!!

        assertEquals(3, data.seasonArtwork.size)
        val posters = data.seasonArtwork.filter { it.kind == "season_poster" }
        assertEquals(listOf(1, 2), posters.map { it.season })
        assertEquals(
            listOf("https://image.tmdb.org/s1.jpg", "https://image.tmdb.org/s2.jpg"),
            posters.map { it.url },
        )
        val still = data.seasonArtwork.single { it.kind == "episode_still" }
        assertEquals(1, still.season)
        assertEquals(1, still.episode)
        assertEquals("https://image.tmdb.org/e1.jpg", still.url)
    }

    @Test
    fun `a detail without season artwork defaults to an empty list`() {
        val data = gson.fromJson(
            """{"success":true,"data":{"id":203,"title":"Film","content_type":"movie"}}""",
            PostDetailResponse::class.java,
        ).data!!
        assertTrue(data.seasonArtwork.isEmpty())
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
    fun `a saved row carries the two facts a tile paints, and invents neither`() {
        val row = Post(
            id = 78,
            title = "Sample Series",
            contentType = "series",
            isAnimated = true,
            subtitled = true,
        )

        val saved = FavoritePost.fromPost(row)
        assertEquals(true, saved.isAnimated)
        assertEquals(true, saved.subtitled)

        val again = saved.toPost()
        assertEquals(true, again.isAnimated)
        assertEquals(true, again.subtitled)

        // A row saved by a build that stored neither column stays undetermined: `null` must
        // not silently become "not animated" or "no subtitles" in a table that cannot tell.
        val legacy = FavoritePost(id = 79, title = "Old save")
        assertNull(legacy.toPost().isAnimated)
        assertNull(legacy.toPost().subtitled)
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

    /*
     * ── C17: the field-modelling bugs the collapse had to leave fixed ─────────────
     * API_V2.md §15 / §16.6, and the two live spellings documented in AGENTS.md §5:
     *  - `is_temporary` is INTEGER 0/1 on `/api/v1/posts/{id}` and a real JSON boolean on
     *    `/api/v1/stream`. Modelling it as `Int?` (the old bug) makes one of the two endpoints
     *    throw; the surviving model is `Boolean?` behind `LenientBooleanAdapter`, so BOTH decode.
     *  - every enum-ish column arrives as a String and is turned into an enum only through
     *    `fromWire(...)`, which must answer UNKNOWN for a value the app has never seen rather
     *    than crash or guess. Gson never touches these fields, so a new server word cannot
     *    break decoding either.
     */

    @Test
    fun `is_temporary decodes as an integer flag and as a real boolean`() {
        val asInteger = gson.fromJson(
            """{"stream_id":"s1","play_url":"http://127.0.0.1:8080/api/v1/stream?id=s1","is_temporary":1,"is_resumable":0}""",
            SourceDetail::class.java,
        )
        assertEquals(true, asInteger.isTemporary)
        assertEquals(false, asInteger.isResumable)
        assertTrue(asInteger.isEphemeral)
        assertFalse(asInteger.isResumableLink)

        val asBoolean = gson.fromJson(
            """{"stream_id":"s2","play_url":"http://127.0.0.1:8080/api/v1/stream?id=s2","is_temporary":true,"is_resumable":true}""",
            SourceDetail::class.java,
        )
        assertEquals(true, asBoolean.isTemporary)
        assertTrue(asBoolean.isEphemeral)
        assertTrue(asBoolean.isResumableLink)

        // A value that is neither spelling is "no evidence", not a fabricated false.
        val asGarbage = gson.fromJson(
            """{"stream_id":"s3","play_url":"http://127.0.0.1:8080/api/v1/stream?id=s3","is_temporary":"maybe"}""",
            SourceDetail::class.java,
        )
        assertNull(asGarbage.isTemporary)
        assertFalse(asGarbage.isEphemeral)
    }

    @Test
    fun `a link status the app has never seen degrades to UNKNOWN and still decodes`() {
        val source = gson.fromJson(
            """
              {"stream_id":"s9","play_url":"http://127.0.0.1:8080/api/v1/stream?id=s9",
               "kind":"quantum_tunnel","status":"flapping","playability":"chromecast"}
            """.trimIndent(),
            SourceDetail::class.java,
        )
        assertEquals("quantum_tunnel", source.kind)
        assertEquals("flapping", source.status)

        // The enum conversion is ours, not Gson's, and it must never throw on an unseen word.
        assertEquals(LinkKind.UNKNOWN, LinkClassification.kindFromWire(source.kind, Playability.UNKNOWN))
        assertEquals(LinkState.UNKNOWN, LinkClassification.stateOf(source.status))
        assertEquals(Playability.UNKNOWN, Playability.fromWire(source.playability))
    }

    @Test
    fun `every fromWire table answers UNKNOWN for a value it has never seen`() {
        // API_V2.md §16.6: the server adds values and never renames them, so a new word must
        // land on UNKNOWN for every enum parsed from a server string.
        assertEquals(Resolution.UNKNOWN, Resolution.fromWire("8k"))
        assertEquals(SourceTag.UNKNOWN, SourceTag.fromWire("laserdisc"))
        assertEquals(Codec.UNKNOWN, Codec.fromWire("vvc"))
        assertEquals(HdrFormat.UNKNOWN, HdrFormat.fromWire("hdr20"))
        assertEquals(Edition.UNKNOWN, Edition.fromWire("cut_by_the_numbers"))
        assertEquals(CoverageType.UNKNOWN, CoverageType.fromWire("half_a_season"))
        assertEquals(LinkKind.UNKNOWN, LinkKind.fromWire("carrier_pigeon"))
        assertEquals(LinkState.UNKNOWN, LinkState.fromWire("flapping"))
        assertEquals(PlayProtocol.UNKNOWN, PlayProtocol.fromWire("srt"))
        assertEquals(WorkType.UNKNOWN, WorkType.fromWire("podcast"))
        assertEquals(SeasonType.UNKNOWN, SeasonType.fromWire("crossover"))
        assertEquals(Container.UNKNOWN, Container.fromWire("wmv"))
        assertEquals(SubtitleMode.UNKNOWN, SubtitleMode.fromWire("burned_to_disk"))
        assertEquals(EntitlementModel.UNKNOWN, EntitlementModel.fromWire("trade_barter"))
        assertEquals(Ownership.UNKNOWN, Ownership.fromWire("borrowed"))
        assertEquals(ScoreScale.UNKNOWN, ScoreScale.fromWire("vibes"))
        assertEquals(WorkFlag.UNKNOWN, WorkFlag.fromWire("shaky"))
        assertEquals(PrintFlag.UNKNOWN, PrintFlag.fromWire("suspiciously_short"))
        assertEquals(ProblemCode.UNKNOWN, ProblemCode.fromWire("teapot"))
    }

    @Test
    fun `a print column that arrives as text is still read as a number`() {
        // `file_size_bytes` is a 64-bit column but SQLite can hand back TEXT; the lenient long
        // adapter must take the digits and never crash a whole catalog row over one cell.
        val source = gson.fromJson(
            """{"stream_id":"s5","play_url":"http://127.0.0.1:8080/api/v1/stream?id=s5","file_size_bytes":"18253611008"}""",
            SourceDetail::class.java,
        )
        assertEquals(18_253_611_008L, source.fileSizeBytes)
    }

    @Test
    fun `the payment receipt the ledger answers is read whole`() {
        // Exactly the body `accounts_api` projects for `account_payment`: an int row id, the
        // server's own price, epoch REAL seconds, and no `tid` anywhere in it.
        val answered = gson.fromJson(
            """{"payment":{"payment_id":7,"status":"pending","plan":"vip_monthly",
               "amount_pkr":200,"method":"jazzcash","submitted_at":1700000000.5}}""",
            PaymentSubmitResponse::class.java,
        )
        val receipt = answered.payment!!
        assertEquals(7, receipt.paymentId)
        assertEquals("pending", receipt.status)
        assertEquals("vip_monthly", receipt.plan)
        assertEquals(200, receipt.amountPkr)
        assertEquals("jazzcash", receipt.method)
        assertEquals(1_700_000_000.5, receipt.submittedAt, 0.001)
    }

    @Test
    fun `an entitlement answer is read on the server's clock, not this device's`() {
        val earned = gson.fromJson(
            """{"entitlement":{"vip":true,"vip_until":1702591999.75,"pending":false}}""",
            EntitlementResponse::class.java,
        ).entitlement!!
        assertTrue(earned.vip)
        assertFalse(earned.pending)
        assertEquals(1_702_591_999.75, earned.vipUntil, 0.001)
    }

    @Test
    fun `a missing or junk entitlement is nothing read rather than a refusal`() {
        // Gson does not run Kotlin defaults for an absent key, so every field must survive both
        // an empty object and a body shaped by a different server build.
        listOf("""{"entitlement":{}}""", """{"entitlement":null}""", """{}""").forEach { raw ->
            val answered = gson.fromJson(raw, EntitlementResponse::class.java)
            assertFalse("$raw must not fabricate VIP", answered.entitlement?.vip == true)
            assertFalse(answered.entitlement?.pending == true)
        }
    }

    @Test
    fun `the live genres column never paints as a genre`() {
        // Sampled verbatim from `GET /api/v1/posts?limit=1` on the running service
        // (2026-10-28): the ledger stores a JSON ARRAY STRING, so an untitled work
        // arrives as "[]" and a titled one as "[\"Action\", \"Drama\"]". Splitting
        // that column on commas is what put a literal `[]` on the detail screen.
        val none = gson.fromJson(
            """{"id":1,"title":"X","clean_title":"X","genres":"[]"}""",
            Post::class.java,
        )
        assertEquals(emptyList<String>(), none.genreList)

        val two = gson.fromJson(
            """{"id":2,"title":"Y","clean_title":"Y","genres":"[\"Action\", \"Drama\"]"}""",
            Post::class.java,
        )
        assertEquals(listOf("Action", "Drama"), two.genreList)

        // The CSV spelling the same column uses in older staging rows still reads.
        val csv = gson.fromJson(
            """{"id":3,"title":"Z","clean_title":"Z","genres":"Action, Drama"}""",
            Post::class.java,
        )
        assertEquals(listOf("Action", "Drama"), csv.genreList)
    }
}
