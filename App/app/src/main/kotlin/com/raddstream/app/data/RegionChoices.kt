package com.raddstream.app.data

/**
 * What each region card promises, and the only preferences it is allowed to write.
 *
 * The wording is bounded by what this catalog actually ingests. `classify_media()` can only
 * ever answer Bollywood, the four southern industries, Pollywood, Hollywood, WWE, K-Drama,
 * C-Drama, Anime and Japanese Cinema — so no card offers Pakistani drama serials, because no
 * importer scrapes Hum, ARY or Geo and a viewer who picked them would be shown an empty grid.
 * The Urdu audio preference still exists (the player has matched `urd` all along), it just is
 * not sold as content the server does not have.
 *
 * [audioLanguage] and [subtitleLanguage] are spelled exactly as the Settings chips spell
 * them, because they are written into the same two stored keys those chips own. A null means
 * "this region has no stance", which removes the preference instead of storing a word for it:
 * an East Asian viewer wants the original track, and naming some other language as preferred
 * would let the player demote the very track they asked for.
 */
data class RegionChoice(
    val id: String,
    val title: String,
    val summary: String,
    val contents: List<String>,
    val audioLanguage: String?,
    val subtitleLanguage: String?,
    val caveat: String? = null,
) {
    /** The sentence Settings can show about this choice, in the viewer's own words. */
    fun preferenceLine(): String = when {
        audioLanguage != null && subtitleLanguage != null ->
            "Prefers $audioLanguage audio with $subtitleLanguage subtitles"
        audioLanguage != null -> "Prefers $audioLanguage audio"
        subtitleLanguage != null -> "Keeps original audio, prefers $subtitleLanguage subtitles"
        else -> "Keeps whatever the file itself carries"
    }
}

object RegionChoices {

    val ALL: List<RegionChoice> = listOf(
        RegionChoice(
            id = UserRegion.DESI_DUBS,
            title = "Pakistan & India (Desi Cinema & Dubs)",
            summary = "Hindi-language prints and dual-audio files lead every list.",
            contents = listOf(
                "Bollywood",
                "South Indian films in Hindi dub",
                "Tamil, Telugu, Malayalam, Kannada originals",
                "Hollywood films in Hindi dub",
            ),
            audioLanguage = "Hindi",
            subtitleLanguage = "English",
            caveat = "Pakistani drama serials (Hum, ARY, Geo) are not in this catalog yet — " +
                "no source is scraped for them. Urdu audio is still available as a preference.",
        ),
        RegionChoice(
            id = UserRegion.EAST_ASIAN,
            title = "East Asian & Subtitle Lovers (C-Drama, K-Drama, Anime)",
            summary = "Original audio kept, subtitles preferred where a print carries them.",
            contents = listOf(
                "Korean and Chinese drama",
                "Anime and Japanese film",
                "External English subtitles",
            ),
            audioLanguage = null,
            subtitleLanguage = "English",
            caveat = "Subtitles are a property of a release, not of a show: a tile only claims " +
                "them when one of its prints actually says so.",
        ),
        RegionChoice(
            id = UserRegion.INTERNATIONAL,
            title = "International & Hollywood",
            summary = "English-original audio first, nothing re-ranked for a dub.",
            contents = listOf(
                "Hollywood and Western cinema",
                "English-language series",
                "WWE and live sport",
            ),
            audioLanguage = "English",
            subtitleLanguage = null,
        ),
    )

    /** The shipped default, resolved through [UserRegion] rather than repeated here. */
    val DEFAULT: RegionChoice = byId(UserRegion.DEFAULT)

    /** Never a guess: an unknown or unreadable value resolves to the default card. */
    fun byId(id: String?): RegionChoice =
        ALL.firstOrNull { it.id == UserRegion.normalize(id) } ?: ALL.first { it.id == UserRegion.DEFAULT }
}
