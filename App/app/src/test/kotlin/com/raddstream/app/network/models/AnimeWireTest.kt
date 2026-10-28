package com.raddstream.app.network.models

import com.raddstream.app.data.local.FavoritePost
import com.raddstream.app.network.buildRaddGson
import com.raddstream.app.viewmodel.normalizeTypeLabel
import com.raddstream.app.viewmodel.typeGroupKey
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/*
 * ANIMATION IS A FLAG, AND THE LIST ROW SENDS IT.
 *
 * Measured 2026-10-28 against the live server: `GET /api/v1/posts?type=anime&limit=2` answers
 * 5,307 works, and each row carries `"is_animated": 1` — a JSON NUMBER, because the ledger
 * column is INTEGER, while the detail route's `bool()`-wrapped siblings arrive as `true`. The
 * client used to throw that field away: `Post` decoded no `is_animated` at all, so
 * `V1CatalogMapper.animatedFromList` answered a hardcoded `null` and the three places that
 * paint a type word each capitalised `content_type` on the spot. An animated series was
 * therefore labelled "Series" on its own tile while the server's own filter called it anime.
 *
 * These tests pin the four things that are now true instead: the number and the boolean both
 * decode, an absent key is unknown rather than false, the label follows the [WorkType] the
 * mapper derived (one anime owner), and a legacy payload renders exactly what it used to.
 */
class AnimeWireTest {

    private val gson = buildRaddGson()

    private fun post(json: String): Post = gson.fromJson(json, Post::class.java)

    private fun listRow(extra: String): String =
        """{"id": 7, "title": "Raw · Title", "content_type": "series"$extra}"""

    @Test
    fun `the integer flag from the ledger decodes as a boolean on the list row`() {
        val row = post(listRow(""", "is_animated": 1"""))

        assertEquals(true, row.isAnimated)
        assertEquals("Anime", row.typeLabel)
    }

    @Test
    fun `a zero flag decodes as false and keeps the plain type word`() {
        val row = post(listRow(""", "is_animated": 0"""))

        assertEquals(false, row.isAnimated)
        assertEquals("Series", row.typeLabel)
    }

    @Test
    fun `a real JSON boolean is accepted too, because two endpoints spell it two ways`() {
        assertEquals(true, post(listRow(""", "is_animated": true""")).isAnimated)
        assertEquals(false, post(listRow(""", "is_animated": false""")).isAnimated)
    }

    @Test
    fun `a legacy row with no such key is unknown, never a guessed false`() {
        val row = post(listRow(""))

        // The distinction is the whole point: `null` must not become "not animated" in a
        // model that cannot tell, and it certainly must not crash the decode of the page.
        assertNull(row.isAnimated)
        assertEquals("Series", row.typeLabel)
    }

    @Test
    fun `junk in the flag column degrades to unknown instead of throwing`() {
        val junk = listRow(""", "is_animated": "yes-ish"""")

        assertNull(post(junk).isAnimated)
        assertEquals("Series", post(junk).typeLabel)
    }

    @Test
    fun `the detail header answers with the same word its tile used`() {
        val detail = gson.fromJson(
            """{"id": 7, "title": "Raw · Title", "content_type": "series", "is_animated": 1}""",
            PostDetail::class.java,
        )

        assertEquals("Anime", detail.typeLabel)
    }

    @Test
    fun `a movie the ledger flags as animated is still a movie`() {
        // `WorkType.fromContentType` promotes to ANIME only from a series family or UNKNOWN,
        // because that is the rule `catalog_v2.work_type_for()` runs. A feature film marked
        // animated is presented as a movie, which is what the server's own browse row says —
        // the client does not invent a second taxonomy on a tile.
        val row = post("""{"id": 8, "title": "Film", "content_type": "movie", "is_animated": 1}""")

        assertEquals("Movie", row.typeLabel)
    }

    @Test
    fun `a blank content type with the flag set reads as anime rather than an empty label`() {
        val row = post("""{"id": 9, "title": "NoType", "content_type": "  ", "is_animated": 1}""")

        assertEquals("Anime", row.typeLabel)
    }

    @Test
    fun `the mapper types a browse tile from the list row, not from its detail page`() {
        val animated = V1CatalogMapper.browseItem(post(listRow(""", "is_animated": 1""")))
        val plain = V1CatalogMapper.browseItem(post(listRow("")))

        assertEquals(WorkType.ANIME, animated.workType)
        assertEquals(WorkType.SERIES, plain.workType)
    }

    @Test
    fun `the label owner never paints an unknown type at a viewer`() {
        assertNull(WorkTypeLabel.of(null, null))
        assertNull(WorkTypeLabel.of("", null))
        assertEquals("Complete_season", WorkTypeLabel.of("complete_season", null))
        // Unchanged from before this rule existed: only an animated series-family row is
        // relabelled, so nothing else on screen moved.
        assertEquals("Ongoing_season", WorkTypeLabel.of("ongoing_season", false))
    }

    @Test
    fun `a flagged series leaves the series rail and its own rail is labelled anime`() {
        val animated = post(listRow(""", "is_animated": 1"""))
        val plain = post(listRow(""", "is_animated": 0"""))

        assertEquals("anime", typeGroupKey(animated))
        assertEquals("Anime", normalizeTypeLabel(typeGroupKey(animated)))
        // A non-animated series is untouched by the rule.
        assertEquals("series", typeGroupKey(plain))
        assertEquals("Series", normalizeTypeLabel(typeGroupKey(plain)))
    }

    @Test
    fun `grouping an animated movie or a legacy row moves nothing`() {
        // The server keeps a film a film (`work_type_for` only promotes the series family),
        // so a flagged movie stays in the Movies rail rather than joining anime rows.
        assertEquals("movie", typeGroupKey(post("""{"id": 1, "title": "T", "content_type": "movie", "is_animated": 1}""")))
        // No flag is not a flag of zero: the row keeps the content_type it always had.
        assertEquals("movie", typeGroupKey(post("""{"id": 1, "title": "T", "content_type": "movie"}""")))
        assertEquals("Other", normalizeTypeLabel(typeGroupKey(post("""{"id": 1, "title": "T"}"""))))
    }

    @Test
    fun `the flag survives a save to My List, so the saved tile says what the live one said`() {
        // My List rebuilds its tiles from the local row alone. Before `favorite_posts` carried
        // this column, an anime saved from an anime-filtered grid came back labelled "Series" —
        // the same work, two words, depending on which screen asked.
        val animated = post(listRow(""", "is_animated": 1, "subtitled": true"""))
        val saved = FavoritePost.fromPost(animated).toPost()

        assertEquals("Anime", animated.typeLabel)
        assertEquals("Anime", saved.typeLabel)
        assertEquals(true, saved.subtitled)
    }

    @Test
    fun `a favourite saved before the column existed keeps the word it always had`() {
        // NULL is not FALSE. A row this build never asked about must not be relabelled, or the
        // migration silently rewrites history the viewer already saw.
        val legacy = FavoritePost(id = 91, title = "Old save", contentType = "series").toPost()

        assertNull(legacy.isAnimated)
        assertEquals("Series", legacy.typeLabel)
    }
}
