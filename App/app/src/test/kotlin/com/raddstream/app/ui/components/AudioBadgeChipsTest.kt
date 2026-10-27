package com.raddstream.app.ui.components

import com.raddstream.app.network.models.Post
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The tile's four audio chips, and the cases where the row honestly says nothing.
 *
 * A dub badge is a claim about what a work was ORIGINALLY made in, so the rule is
 * "this listed audio language is not this industry's own" rather than "Hindi appears in
 * the language column". The cases below are the ones a viewer actually sees in the grid,
 * and the quiet ones matter as much as the loud ones: an unknown industry, or a server
 * that predates the `subtitled` key, must not be answered with a guess.
 */
class AudioBadgeChipsTest {

    private fun post(
        industry: String? = null,
        language: String? = null,
        subtitled: Boolean? = null,
    ) = Post(
        id = 1,
        title = "Work",
        industry = industry,
        language = language,
        subtitled = subtitled,
    )

    @Test
    fun `the four chip labels are the words the brief asked for`() {
        assertEquals(
            listOf("Hindi Dubbed", "Urdu Dubbed", "Dual Audio", "Subtitled"),
            TileAudioBadge.entries.map { it.label },
        )
    }

    @Test
    fun `a hindi track on a japanese work is called dubbed`() {
        assertEquals(
            listOf(TileAudioBadge.HINDI_DUBBED, TileAudioBadge.DUAL_AUDIO),
            TileAudioBadges.forPost(post(industry = "Anime", language = "Hindi + Japanese")),
        )
    }

    @Test
    fun `a hindi bollywood original earns no dub chip`() {
        assertEquals(emptyList<TileAudioBadge>(), TileAudioBadges.forPost(post(industry = "Bollywood", language = "Hindi")))
    }

    @Test
    fun `the dubbed-south-indian industry reads the way it is spelled`() {
        assertEquals(
            listOf(TileAudioBadge.HINDI_DUBBED, TileAudioBadge.DUAL_AUDIO),
            TileAudioBadges.forPost(
                post(industry = "South Indian (Hindi Dubbed)", language = "Hindi + Telugu"),
            ),
        )
    }

    @Test
    fun `the hindi track of a telugu original is the dub, the telugu one is not`() {
        assertEquals(
            listOf(TileAudioBadge.HINDI_DUBBED, TileAudioBadge.DUAL_AUDIO),
            TileAudioBadges.forPost(post(industry = "Tollywood (Telugu)", language = "Telugu + Hindi")),
        )
    }

    @Test
    fun `an urdu track on an english work is the urdu dub`() {
        assertEquals(
            listOf(TileAudioBadge.URDU_DUBBED, TileAudioBadge.DUAL_AUDIO),
            TileAudioBadges.forPost(post(industry = "Hollywood", language = "English + Urdu")),
        )
    }

    @Test
    fun `no industry means no guess about what was original`() {
        assertEquals(
            listOf(TileAudioBadge.DUAL_AUDIO, TileAudioBadge.SUBTITLED),
            TileAudioBadges.forPost(post(language = "Hindi + Japanese", subtitled = true)),
        )
    }

    @Test
    fun `single-language audio is not dual audio`() {
        assertEquals(emptyList<TileAudioBadge>(), TileAudioBadges.forPost(post(industry = "Hollywood", language = "English")))
    }

    @Test
    fun `three languages is still one dual-audio chip`() {
        assertEquals(
            listOf(TileAudioBadge.DUAL_AUDIO),
            TileAudioBadges.forPost(post(industry = "Bollywood", language = "Hindi + Tamil + Telugu")),
        )
    }

    @Test
    fun `the subtitle chip follows the server and silence is not a no`() {
        assertEquals(
            listOf(TileAudioBadge.SUBTITLED),
            TileAudioBadges.forPost(post(industry = "K-Drama", language = "Korean", subtitled = true)),
        )
        assertEquals(
            emptyList<TileAudioBadge>(),
            TileAudioBadges.forPost(post(industry = "K-Drama", language = "Korean", subtitled = false)),
        )
        assertEquals(
            emptyList<TileAudioBadge>(),
            TileAudioBadges.forPost(post(industry = "K-Drama", language = "Korean", subtitled = null)),
        )
    }

    @Test
    fun `two chips is the cap and dub status outranks the rest`() {
        assertEquals(
            listOf(TileAudioBadge.HINDI_DUBBED, TileAudioBadge.DUAL_AUDIO),
            TileAudioBadges.forPost(
                post(industry = "K-Drama", language = "Korean + Hindi", subtitled = true),
            ),
        )
        assertEquals(TileAudioBadges.MAX_ON_TILE, 2)
    }

    @Test
    fun `a language code on the wire counts as the same language`() {
        assertEquals(
            listOf(TileAudioBadge.HINDI_DUBBED, TileAudioBadge.DUAL_AUDIO),
            TileAudioBadges.forPost(post(industry = "Kollywood (Tamil)", language = "tam, hin")),
        )
    }
}
