package com.raddstream.app.viewmodel

import com.raddstream.app.data.UserRegion
import com.raddstream.app.network.models.ReleaseDetail
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pins the regional-dub preference and the ordering it buys.
 *
 * The storage contract is the three wire names in [UserRegion]; the shipped default is
 * `desi_dubs`, so a fresh install already leads with the Hindi/Urdu print instead of
 * making a Pakistani or Indian viewer scroll past English originals. Ordering is applied
 * by [ReleaseLayoutBuilder] and must never lift a CAM above an official print.
 */
class RegionPreferenceTest {

    private fun release(
        id: Int,
        releaseTitle: String? = null,
        quality: String? = null,
        season: String? = null,
        episode: String? = null,
        languages: String? = null,
    ) = ReleaseDetail(
        id = id,
        releaseTitle = releaseTitle,
        quality = quality,
        season = season,
        episode = episode,
        languages = languages,
    )

    private fun moviePrints(vararg releases: ReleaseDetail, region: String) =
        ReleaseLayoutBuilder.build(
            contentType = "movie",
            releases = releases.toList(),
            artwork = emptyList(),
            region = region,
        ).workPrints

    // ── the stored preference ───────────────────────────────────────────────────

    @Test
    fun `the shipped default region is desi dubs`() {
        assertEquals("desi_dubs", UserRegion.DEFAULT)
        assertEquals(UserRegion.DESI_DUBS, UserRegion.normalize(null))
    }

    @Test
    fun `a known region round-trips and an unknown one falls back to the default`() {
        assertEquals(UserRegion.EAST_ASIAN, UserRegion.normalize("east_asian"))
        assertEquals(UserRegion.INTERNATIONAL, UserRegion.normalize(" International "))
        assertEquals(UserRegion.DESI_DUBS, UserRegion.normalize("Desi_Dubs"))
        assertEquals(UserRegion.DESI_DUBS, UserRegion.normalize("klingon"))
        assertEquals(UserRegion.DESI_DUBS, UserRegion.normalize(""))
    }

    // ── the ordering it buys ────────────────────────────────────────────────────

    @Test
    fun `hindi print leads a higher ranked english original for desi dubs`() {
        val english = release(
            id = 1,
            releaseTitle = "Film 1080p WEB-DL English",
            quality = "1080p",
            languages = "English",
        )
        val hindi = release(
            id = 2,
            releaseTitle = "Film 720p WEB-DL Hindi Dubbed",
            quality = "720p",
            languages = "Hindi",
        )

        val desi = moviePrints(english, hindi, region = UserRegion.DESI_DUBS)
        assertTrue(
            "the English print must outrank the Hindi one before region is applied",
            desi.first { it.releaseId == 1 }.rankKey > desi.first { it.releaseId == 2 }.rankKey,
        )
        assertEquals(2, desi.first().releaseId)
        assertEquals("Hindi", desi.first().languages.single())

        val international = moviePrints(english, hindi, region = UserRegion.INTERNATIONAL)
        assertEquals(1, international.first().releaseId)
    }

    @Test
    fun `urdu dub leads the english original for desi dubs`() {
        val english = release(
            id = 1,
            releaseTitle = "Film 1080p WEB-DL",
            quality = "1080p",
            languages = "English",
        )
        val urdu = release(
            id = 2,
            releaseTitle = "Film 720p WEB-DL Urdu Dubbed",
            quality = "720p",
        )

        val desi = moviePrints(english, urdu, region = UserRegion.DESI_DUBS)
        assertEquals(2, desi.first().releaseId)
        assertTrue("the Urdu label is parsed into an audio language", desi.first().languages.contains("Urdu"))
    }

    @Test
    fun `a dual audio label leads for desi dubs`() {
        val english = release(id = 1, releaseTitle = "Film 1080p WEB-DL", quality = "1080p", languages = "English")
        val dual = release(id = 2, releaseTitle = "Film 720p WEB-DL Dual Audio", quality = "720p")

        val desi = moviePrints(english, dual, region = UserRegion.DESI_DUBS)
        assertEquals(2, desi.first().releaseId)
        assertTrue(desi.first().dualAudio)
    }

    @Test
    fun `east asian keeps the pure quality order`() {
        val english = release(id = 1, releaseTitle = "Film 1080p WEB-DL", quality = "1080p", languages = "English")
        val hindi = release(id = 2, releaseTitle = "Film 720p WEB-DL Hindi", quality = "720p", languages = "Hindi")

        val eastAsian = moviePrints(english, hindi, region = UserRegion.EAST_ASIAN)
        assertEquals(1, eastAsian.first().releaseId)
    }

    @Test
    fun `language priority never lifts a cam above an official print`() {
        val englishOfficial = release(
            id = 1,
            releaseTitle = "Film 1080p WEB-DL English",
            quality = "1080p",
            languages = "English",
        )
        val hindiCam = release(
            id = 2,
            releaseTitle = "Film 720p HDTS Hindi",
            quality = "720p",
            languages = "Hindi",
        )

        val desi = moviePrints(englishOfficial, hindiCam, region = UserRegion.DESI_DUBS)
        assertEquals(1, desi.first().releaseId)
        assertTrue(desi.last().isCam)
    }

    @Test
    fun `episode prints follow the same regional order`() {
        val english = release(
            id = 1,
            releaseTitle = "Show 1080p WEB-DL English",
            quality = "1080p",
            season = "1",
            episode = "1",
            languages = "English",
        )
        val hindi = release(
            id = 2,
            releaseTitle = "Show 720p WEB-DL Hindi",
            quality = "720p",
            season = "1",
            episode = "1",
            languages = "Hindi",
        )

        val layout = ReleaseLayoutBuilder.build(
            contentType = "series",
            releases = listOf(english, hindi),
            artwork = emptyList(),
            region = UserRegion.DESI_DUBS,
        )
        val prints = layout.seasons.single().episodes.single().prints
        assertEquals(2, prints.first().releaseId)
    }
}
