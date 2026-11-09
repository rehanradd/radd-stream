package com.raddstream.app.network

import com.raddstream.app.data.local.FavoritePost
import com.raddstream.app.network.models.Codec
import com.raddstream.app.network.models.AccountOverviewResponse
import com.raddstream.app.network.models.CoinBalanceResponse
import com.raddstream.app.network.models.CoinCapsResponse
import com.raddstream.app.network.models.CoinHistoryResponse
import com.raddstream.app.network.models.CoinDownloadCreditRequest
import com.raddstream.app.network.models.CoinDownloadCreditResponse
import com.raddstream.app.network.models.CoinEarnRequest
import com.raddstream.app.network.models.CoinEarnResponse
import com.raddstream.app.network.models.CoinRedeemRequest
import com.raddstream.app.network.models.CoinRedeemResponse
import com.raddstream.app.network.models.CoinRedeemThemeRequest
import com.raddstream.app.network.models.CoinRedeemThemeResponse
import com.raddstream.app.network.models.CoinRequestMovieRequest
import com.raddstream.app.network.models.CoinRequestMovieResponse
import com.raddstream.app.network.models.CoinShareRequest
import com.raddstream.app.network.models.CoinShareResponse
import com.raddstream.app.network.models.CoinThemesResponse
import com.raddstream.app.network.models.Container
import com.raddstream.app.network.models.CoverageType
import com.raddstream.app.network.models.EntitlementResponse
import com.raddstream.app.network.models.Edition
import com.raddstream.app.network.models.EntitlementModel
import com.raddstream.app.network.models.HdrFormat
import com.raddstream.app.network.models.LinkClassification
import com.raddstream.app.network.models.LinkKind
import com.raddstream.app.network.models.LinkState
import com.raddstream.app.network.models.LiveTvChannel
import com.raddstream.app.network.models.LiveTvChannelsResponse
import com.raddstream.app.network.models.Ownership
import com.raddstream.app.network.models.PaymentSubmitResponse
import com.raddstream.app.network.models.Playability
import com.raddstream.app.network.models.PlayProtocol
import com.raddstream.app.network.models.Post
import com.raddstream.app.network.models.PostDetail
import com.raddstream.app.network.models.PostDetailResponse
import com.raddstream.app.network.models.PostsResponse
import com.raddstream.app.network.models.ProgressWriteResponse
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
import com.raddstream.app.network.models.VipPassResponse
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
    fun `detail runtime minutes decode from the work row`() {
        // The server attaches runtime_minutes from cat_works when a work row
        // exists; a title with no work row carries no key at all (asserted
        // server-side in test_database.py). The field is nullable, so a
        // missing key decodes to null and the header simply shows nothing.
        val json = """
            {
              "success": true,
              "data": {
                "id": 303,
                "title": "Example Film",
                "runtime_minutes": 142
              }
            }
        """.trimIndent()

        val data = gson.fromJson(json, PostDetailResponse::class.java).data!!

        assertEquals(142, data.runtimeMinutes)
    }

    @Test
    fun `detail cast names decode from the post row and default to null`() {
        // The server publishes posts.cast_names on the detail only. A missing
        // key decodes to null — no cast section, never an invented name.
        val withCast = gson.fromJson(
            """{"success":true,"data":{"id":304,"title":"Film","cast_names":"Shah Rukh Khan, Kajol"}}""",
            PostDetailResponse::class.java,
        ).data!!
        assertEquals("Shah Rukh Khan, Kajol", withCast.castNames)
        val withoutCast = gson.fromJson(
            """{"success":true,"data":{"id":305,"title":"Film"}}""",
            PostDetailResponse::class.java,
        ).data!!
        assertNull(withoutCast.castNames)
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
    fun `live tv channels response maps snake case names and the signed handle`() {
        val json = """
            {
              "success": true,
              "channels": [
                {
                  "id": 1,
                  "name": "Dunya News",
                  "category": "news",
                  "country": "PK",
                  "language": "ur",
                  "logo_url": "https://i.imgur.com/1PbtW0y.png",
                  "stream_id": "BQAAAAAAAAAHAAAAAAAQk8DD-uITf2IC7Q"
                },
                {
                  "id": 22,
                  "name": "DD Sports",
                  "category": "sports",
                  "country": "IN",
                  "language": "hi",
                  "logo_url": "https://example.test/dd-sports.png",
                  "stream_id": "BQAAAAAAABYAAAAAAAQk8DD-uITf2IC7Q"
                }
              ],
              "categories": ["news", "sports"]
            }
        """.trimIndent()

        val response = gson.fromJson(json, LiveTvChannelsResponse::class.java)

        assertTrue(response.success)
        assertEquals(listOf("news", "sports"), response.categories)
        assertEquals(2, response.channels.size)
        val first = response.channels[0]
        assertEquals(1, first.id)
        assertEquals("Dunya News", first.name)
        assertEquals("news", first.category)
        assertEquals("PK", first.country)
        assertEquals("ur", first.language)
        assertEquals("https://i.imgur.com/1PbtW0y.png", first.logoUrl)
        assertEquals("BQAAAAAAAAAHAAAAAAAQk8DD-uITf2IC7Q", first.streamId)
        assertEquals("sports", response.channels[1].category)
        // The model has no stream_url/source field at all: the upstream HLS
        // address must not be reachable through the wire type either.
        assertEquals(emptyList<String>(), LiveTvChannel::class.java.declaredFields
            .map { it.name }.filter { it in setOf("streamUrl", "source", "url") })
    }

    @Test
    fun `live tv channels response defaults to empty when the server sends nothing`() {
        val response = gson.fromJson("{}", LiveTvChannelsResponse::class.java)

        assertTrue(response.success)
        assertEquals(emptyList<LiveTvChannel>(), response.channels)
        assertEquals(emptyList<String>(), response.categories)
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

    @Test
    fun `coin earn request carries reason only`() {
        val json = gson.toJson(CoinEarnRequest())

        assertEquals("""{"reason":"daily_login"}""", json)
    }

    @Test
    fun `coin earn response decodes the server's claim answer`() {
        val response = gson.fromJson(
            """{"earned":{"status":"advanced","current_streak":2,"best_streak":5,"day":"2026-11-07","coins_granted":20}}""",
            CoinEarnResponse::class.java,
        )

        val earned = response.earned
        assertNotNull(earned)
        assertEquals("advanced", earned?.status)
        assertEquals(2, earned?.currentStreak)
        assertEquals(5, earned?.bestStreak)
        assertEquals(20, earned?.coinsGranted)
        assertNull(earned?.pass)
    }

    @Test
    fun `coin balance response decodes the ledger's own number`() {
        val response = gson.fromJson(
            """{"balance":370,"rewarded_grants_today":0}""",
            CoinBalanceResponse::class.java,
        )

        assertEquals(370, response.balance)
        assertEquals(0, response.rewardedGrantsToday)
    }

    @Test
    fun `coin caps response decodes the pass tiers by plan`() {
        val response = gson.fromJson(
            """{"streak":{"coins":{"1":10},"pass_seconds":86400},"passes":{"day":{"coins":500,"pkr":20},"weekend":{"coins":70,"pkr":50},"monthly_vip":{"coins":200,"pkr":250}}}""",
            CoinCapsResponse::class.java,
        )

        assertEquals(500, response.passes["day"]?.coins)
        assertEquals(20, response.passes["day"]?.pkr)
        assertEquals(70, response.passes["weekend"]?.coins)
        assertEquals(200, response.passes["monthly_vip"]?.coins)
    }

    @Test
    fun `coin history response decodes the ledger rows newest first`() {
        val response = gson.fromJson(
            """{"entries":[{"id":7,"delta":-500,"reason":"redeem_pass","source":"server","ref":"day","created_at":1790000000.0},{"id":6,"delta":20,"reason":"streak_day","source":"server","ref":"day2","created_at":1789913600.0}],"count":2}""",
            CoinHistoryResponse::class.java,
        )

        assertEquals(2, response.count)
        assertEquals(2, response.entries.size)
        assertEquals(7, response.entries[0].id)
        assertEquals(-500, response.entries[0].delta)
        assertEquals("redeem_pass", response.entries[0].reason)
        assertEquals("day", response.entries[0].ref)
        assertEquals(1790000000.0, response.entries[0].createdAt)
        assertEquals(20, response.entries[1].delta)
        assertEquals("streak_day", response.entries[1].reason)
    }

    @Test
    fun `account overview response decodes the balance streak and cadence`() {
        val response = gson.fromJson(
            """{"balance":370,"streak":{"current_streak":3,"best_streak":5,"last_counted_day":"2026-11-09","tz":"Asia/Karachi","day_boundary_hour":4},"cadence":{"last_preroll_at":0.0,"last_app_open_at":1790000000.0,"native_poster_cursor":2}}""",
            AccountOverviewResponse::class.java,
        )

        assertEquals(370, response.balance)
        assertEquals(3, response.streak.currentStreak)
        assertEquals(5, response.streak.bestStreak)
        assertEquals("2026-11-09", response.streak.lastCountedDay)
        assertEquals("Asia/Karachi", response.streak.tz)
        assertEquals(4, response.streak.dayBoundaryHour)
        assertEquals(1790000000.0, response.cadence.lastAppOpenAt)
        assertEquals(2, response.cadence.nativePosterCursor)
    }

    @Test
    fun `coin redeem request carries plan only`() {
        val json = gson.toJson(CoinRedeemRequest("day"))

        assertEquals("""{"plan":"day"}""", json)
    }

    @Test
    fun `coin redeem response decodes the server's receipt`() {
        val response = gson.fromJson(
            """{"redeemed":{"reward":"day","cost":500,"balance":0,"already_applied":false,"expires_at":1790000000.0,"pass":"token"}}""",
            CoinRedeemResponse::class.java,
        )

        val redeemed = response.redeemed
        assertNotNull(redeemed)
        assertEquals("day", redeemed?.reward)
        assertEquals(500, redeemed?.cost)
        assertEquals(0, redeemed?.balance)
        assertEquals(false, redeemed?.alreadyApplied)
        assertEquals(1790000000.0, redeemed?.expiresAt)
        assertEquals("token", redeemed?.pass)
    }

    @Test
    fun `coin caps response decodes the direct download price`() {
        val response = gson.fromJson(
            """{"streak":{"coins":{"1":10},"pass_seconds":86400},"passes":{},"download":{"coins":100}}""",
            CoinCapsResponse::class.java,
        )

        assertEquals(100, response.download.coins)
    }

    @Test
    fun `coin caps response without a download block offers no direct link`() {
        val response = gson.fromJson(
            """{"streak":{"coins":{"1":10},"pass_seconds":86400},"passes":{}}""",
            CoinCapsResponse::class.java,
        )

        assertEquals(0, response.download.coins)
    }

    @Test
    fun `coin download credit request carries handle only`() {
        val json = gson.toJson(CoinDownloadCreditRequest("abc123"))

        assertEquals("""{"handle":"abc123"}""", json)
    }

    @Test
    fun `coin download credit response decodes the server's receipt`() {
        val response = gson.fromJson(
            """{"credit":{"token":"cred-token","handle":"abc123","cost":100,"balance":270,"already_applied":false,"expires_at":1790000000.0}}""",
            CoinDownloadCreditResponse::class.java,
        )

        val credit = response.credit
        assertNotNull(credit)
        assertEquals("cred-token", credit?.token)
        assertEquals("abc123", credit?.handle)
        assertEquals(100, credit?.cost)
        assertEquals(270, credit?.balance)
        assertEquals(false, credit?.alreadyApplied)
        assertEquals(1790000000.0, credit?.expiresAt)
    }

    @Test
    fun `coin share request carries work_ref only`() {
        val json = gson.toJson(CoinShareRequest("handle-abc"))

        assertEquals("""{"work_ref":"handle-abc"}""", json)
    }

    @Test
    fun `coin share response decodes the server's grant`() {
        val response = gson.fromJson(
            """{"share":{"granted":true,"coins":25,"balance":25}}""",
            CoinShareResponse::class.java,
        )

        val share = response.share
        assertNotNull(share)
        assertEquals(true, share?.granted)
        assertEquals(25, share?.coins)
        assertEquals(25, share?.balance)
    }

    @Test
    fun `coin share response decodes a second share the same day as no grant`() {
        val response = gson.fromJson(
            """{"share":{"granted":false,"coins":25,"balance":25}}""",
            CoinShareResponse::class.java,
        )

        assertEquals(false, response.share?.granted)
        assertEquals(25, response.share?.balance)
    }

    @Test
    fun `coin request-movie request carries title and notes`() {
        val json = gson.toJson(CoinRequestMovieRequest("Dune: Part Three", "please"))

        assertEquals("""{"title":"Dune: Part Three","notes":"please"}""", json)
    }

    @Test
    fun `coin request-movie response decodes the queued request`() {
        val response = gson.fromJson(
            """{"request":{"id":7,"title":"Dune: Part Three","cost":300,"balance":0,"already_applied":false}}""",
            CoinRequestMovieResponse::class.java,
        )

        val request = response.request
        assertNotNull(request)
        assertEquals(7, request?.id)
        assertEquals("Dune: Part Three", request?.title)
        assertEquals(300, request?.cost)
        assertEquals(0, request?.balance)
        assertEquals(false, request?.alreadyApplied)
    }

    @Test
    fun `coin redeem-theme request carries theme only`() {
        val json = gson.toJson(CoinRedeemThemeRequest("midnight"))

        assertEquals("""{"theme":"midnight"}""", json)
    }

    @Test
    fun `coin redeem-theme response decodes the theme and the ownership`() {
        val response = gson.fromJson(
            """{"theme":{"theme":"midnight","cost":250,"balance":0,"already_applied":false,"owned":["jade","midnight"]}}""",
            CoinRedeemThemeResponse::class.java,
        )

        val theme = response.theme
        assertNotNull(theme)
        assertEquals("midnight", theme?.theme)
        assertEquals(250, theme?.cost)
        assertEquals(0, theme?.balance)
        assertEquals(false, theme?.alreadyApplied)
        assertEquals(listOf("jade", "midnight"), theme?.owned)
    }

    @Test
    fun `coin themes response decodes owned themes and prices`() {
        val response = gson.fromJson(
            """{"themes":["jade"],"prices":{"midnight":{"coins":250},"ember":{"coins":250}}}""",
            CoinThemesResponse::class.java,
        )

        assertEquals(listOf("jade"), response.themes)
        assertEquals(250, response.prices["midnight"]?.coins)
        assertEquals(250, response.prices["ember"]?.coins)
    }

    @Test
    fun `coin caps response decodes the request price and the theme prices`() {
        val response = gson.fromJson(
            """{"streak":{"coins":{"1":10},"pass_seconds":86400},"passes":{},"download":{"coins":100},"request":{"coins":300},"themes":{"midnight":{"coins":250},"ember":{"coins":250}}}""",
            CoinCapsResponse::class.java,
        )

        assertEquals(300, response.request.coins)
        assertEquals(250, response.themes["midnight"]?.coins)
        assertEquals(250, response.themes["ember"]?.coins)
    }

    @Test
    fun `progress write response decodes coins earned by a finish`() {
        val response = gson.fromJson(
            """{"progress":{"work_ref":"handle-abc","position_seconds":950.0,"duration_seconds":1000.0},"coins_earned":15}""",
            ProgressWriteResponse::class.java,
        )

        assertEquals(15, response.coinsEarned)
    }

    @Test
    fun `progress write response without coins earned pays nothing`() {
        val response = gson.fromJson(
            """{"progress":{"work_ref":"handle-abc","position_seconds":500.0,"duration_seconds":1000.0}}""",
            ProgressWriteResponse::class.java,
        )

        assertEquals(0, response.coinsEarned)
    }

    @Test
    fun `vip pass response decodes the pass and its expiry`() {
        val response = gson.fromJson(
            """{"pass":"AQIDBAUGBwg","expires_at":1794195742.0,"membership_until":1796790142.0}""",
            VipPassResponse::class.java,
        )

        assertEquals("AQIDBAUGBwg", response.pass)
        assertEquals(1794195742.0, response.expiresAt, 0.001)
        assertEquals(1796790142.0, response.membershipUntil, 0.001)
    }

    @Test
    fun `vip pass response without a pass carries nothing to append`() {
        val response = gson.fromJson(
            """{"pass":null,"expires_at":0.0,"membership_until":0.0}""",
            VipPassResponse::class.java,
        )

        assertNull(response.pass)
    }
}
