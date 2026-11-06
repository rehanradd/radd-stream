package com.raddstream.app.data

/**
 * What each region card promises, and the only preferences it is allowed to write.
 *
 * A card is one short line, not a brochure: a title, a tagline, and the audio/subtitle
 * promise it writes. The wording is bounded by what this catalog actually ingests.
 * `classify_media()` can only ever answer Bollywood, the four southern industries,
 * Pollywood, Hollywood, WWE, K-Drama, C-Drama, Anime and Japanese Cinema — so no card
 * offers Pakistani drama serials, because no importer scrapes Hum, ARY or Geo and a
 * viewer who picked them would be shown an empty grid. The Urdu audio preference still
 * exists (the player has matched `urd` all along), it just is not sold as content the
 * server does not have.
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
    val tagline: String,
    val audioLanguage: String?,
    val subtitleLanguage: String?,
) {
    /** The sentence Settings can show about this choice, in the viewer's own words. */
    fun preferenceLine(): String = when {
        audioLanguage != null && subtitleLanguage != null ->
            "Prefers $audioLanguage audio with $subtitleLanguage subtitles"
        audioLanguage != null -> "Prefers $audioLanguage audio"
        subtitleLanguage != null -> "Keeps original audio, prefers $subtitleLanguage subtitles"
        else -> "Keeps whatever the file itself carries"
    }

    /** The one-line promise on the card: "Hindi audio · English subtitles". */
    fun preferencePill(): String = when {
        audioLanguage != null && subtitleLanguage != null ->
            "$audioLanguage audio · $subtitleLanguage subtitles"
        audioLanguage != null -> "$audioLanguage audio"
        subtitleLanguage != null -> "Original audio · $subtitleLanguage subtitles"
        else -> "Original audio"
    }
}

object RegionChoices {

    val ALL: List<RegionChoice> = listOf(
        RegionChoice(
            id = UserRegion.DESI_DUBS,
            title = "Desi",
            tagline = "Bollywood & Hindi dubs",
            audioLanguage = "Hindi",
            subtitleLanguage = "English",
        ),
        RegionChoice(
            id = UserRegion.EAST_ASIAN,
            title = "East Asian",
            tagline = "K-Drama, C-Drama & Anime",
            audioLanguage = null,
            subtitleLanguage = "English",
        ),
        RegionChoice(
            id = UserRegion.INTERNATIONAL,
            title = "International",
            tagline = "Hollywood & world cinema",
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
