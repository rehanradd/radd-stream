package com.raddstream.app.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.raddstream.app.network.models.Post
import com.raddstream.app.network.models.WireText
import com.raddstream.app.ui.theme.RaddCurrent500
import com.raddstream.app.ui.theme.RaddSuccess
import com.raddstream.app.ui.theme.RaddTideIndigo
import com.raddstream.app.ui.theme.RaddWarning

/**
 * The audio fact a browser needs before tapping: is this the Hindi or Urdu dub, or the
 * original? On a catalog this mixed the answer decides whether the title is watchable at
 * all, so it goes on the tile instead of being discovered on the detail screen.
 *
 * Every badge here is a claim the served row actually supports — see [TileAudioBadges] for
 * the rule and for the cases the tile deliberately stays quiet about.
 */
enum class TileAudioBadge(val label: String, val a11y: String) {
    HINDI_DUBBED("Hindi Dubbed", "Hindi dub of a work originally in another language"),
    URDU_DUBBED("Urdu Dubbed", "Urdu dub of a work originally in another language"),
    DUAL_AUDIO("Dual Audio", "More than one audio language on this work"),
    SUBTITLED("Subtitled", "At least one release of this work carries subtitles"),
}

/**
 * The tile-level rules, kept out of the composable so they can be argued with in a JVM test.
 *
 * Three sources of truth, all already on the row:
 *  - `language` — the work's audio languages. Two or more is the same test
 *    `release_descriptor._detect_audio` uses for a dual-audio print.
 *  - `industry` — which language this work was MADE in. A dub badge is only raised when a
 *    listed audio language is not that industry's own, so Bollywood-in-Hindi stays plain
 *    while an Anime or K-drama carrying Hindi is called dubbed. The ledger's own
 *    `South Indian (Hindi Dubbed)` industry maps to the southern originals, which is
 *    exactly how it reads: the Hindi track is the dub, the Telugu one is not.
 *  - `subtitled` — the server's per-work existence test over its prints.
 *
 * What is NOT guessed: an unknown or absent industry means we cannot know what was
 * original, so no dub chip appears rather than a coin flip; and a null `subtitled` (a
 * server that predates the key) earns no badge.
 */
object TileAudioBadges {

    /** Max chips on one tile: past two, the grid's rows stop lining up. */
    const val MAX_ON_TILE = 2

    private val HINDI = setOf("hindi", "hin")
    private val URDU = setOf("urdu", "urd")

    /** Languages a work of this industry was originally produced in. */
    private val originalsOf: List<Pair<List<String>, Set<String>>> = listOf(
        listOf("bollywood", "hindi movie", "hindi series") to setOf("hindi", "hin"),
        listOf("south indian", "dubbed") to setOf("tamil", "telugu", "malayalam", "kannada", "tam", "tel", "mal", "kan"),
        listOf("tollywood", "telugu") to setOf("telugu", "tel"),
        listOf("kollywood", "tamil") to setOf("tamil", "tam"),
        listOf("mollywood", "malayalam") to setOf("malayalam", "mal"),
        listOf("sandalwood", "kannada") to setOf("kannada", "kan"),
        listOf("pollywood", "punjabi") to setOf("punjabi", "pan"),
        listOf("bengali") to setOf("bengali", "ben"),
        listOf("marathi") to setOf("marathi", "mar"),
        listOf("gujarati") to setOf("gujarati", "guj"),
        listOf("hollywood", "wwe", "american") to setOf("english", "eng"),
        listOf("k-drama", "korean") to setOf("korean", "kor"),
        listOf("c-drama", "chinese", "mandarin") to setOf("chinese", "mandarin", "zho", "chi"),
        listOf("anime", "japanese") to setOf("japanese", "jpn"),
        listOf("pakistan") to setOf("urdu", "urd"),
    )

    /** The languages of this row's `language` column, normalised for comparison. */
    fun audioLanguages(post: Post): List<String> =
        WireText.listOf(post.language).map { it.trim().lowercase() }.filter { it.isNotEmpty() }

    /** The languages this industry produces natively; empty when the industry is unknown. */
    fun originalLanguages(post: Post): Set<String> {
        val industry = post.industry?.trim()?.lowercase()?.takeIf { it.isNotEmpty() } ?: return emptySet()
        return originalsOf.firstOrNull { (needles, _) -> needles.any { industry.contains(it) } }?.second
            ?: emptySet()
    }

    fun forPost(post: Post): List<TileAudioBadge> {
        val langs = audioLanguages(post)
        val originals = originalLanguages(post)
        // [originalLanguages] answers empty exactly when the row gives us no industry to read,
        // so an empty set IS the "we cannot know what was original" case.
        val canJudgeDub = originals.isNotEmpty()

        val present = buildSet {
            if (canJudgeDub && langs.any { it in HINDI } && HINDI.none { it in originals }) add(TileAudioBadge.HINDI_DUBBED)
            if (canJudgeDub && langs.any { it in URDU } && URDU.none { it in originals }) add(TileAudioBadge.URDU_DUBBED)
            if (langs.size >= 2) add(TileAudioBadge.DUAL_AUDIO)
            if (post.subtitled == true) add(TileAudioBadge.SUBTITLED)
        }
        return TileAudioBadge.entries.filter { it in present }.take(MAX_ON_TILE)
    }
}

/** The chip row itself — brand colours only, so a re-skin repaints these with everything else. */
@Composable
fun AudioBadgeChipRow(
    badges: List<TileAudioBadge>,
    modifier: Modifier = Modifier,
) {
    if (badges.isEmpty()) return
    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        badges.forEach { badge ->
            Pill(
                text = badge.label,
                backgroundColor = badge.tint(),
                contentColor = badge.accent(),
                contentDescription = badge.a11y,
            )
        }
    }
}

/** Emerald, teal, royal blue, amber — each one a brand ramp role, never a literal hex. */
private fun TileAudioBadge.accent(): Color = when (this) {
    TileAudioBadge.HINDI_DUBBED -> RaddSuccess
    TileAudioBadge.URDU_DUBBED -> RaddCurrent500
    TileAudioBadge.DUAL_AUDIO -> RaddTideIndigo
    TileAudioBadge.SUBTITLED -> RaddWarning
}

private fun TileAudioBadge.tint(): Color = accent().copy(alpha = 0.18f)
