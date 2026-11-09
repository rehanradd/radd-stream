package com.raddstream.app.network.models

/**
 * The cast list the server stores, as names a viewer can tap.
 *
 * The stored string is whatever the scraper found — usually comma-separated
 * ("Shah Rukh Khan, Kajol"), sometimes space-separated ("Mark Hamill
 * Harrison Ford Carrie Fisher"), sometimes a synopsis fragment a parser
 * misfiled as cast. Nothing here invents a name: the rules only ever drop
 * a chunk that cannot be a name.
 *
 *  - Split on commas. A chunk is one candidate name.
 *  - A string with no commas at all is one name only when it is short
 *    (1–3 words: "Shah Rukh Khan"). Longer comma-less strings are several
 *    names glued with spaces, and guessing the joints would invent names —
 *    so they read as no cast, not as one long "actor".
 *  - A candidate is dropped when it has more than 4 words, when any word
 *    does not start with an uppercase letter (kills "tvgard" and the
 *    sentence words "and"/"have"/"after"), or when it holds a character no
 *    name holds (digits, brackets). A small particle set ("de", "van",
 *    "von" ...) is allowed inside a name, so "Robert de Niro" survives.
 *  - Duplicates collapse; at most 12 names come back (the section shows 6
 *    and counts the rest).
 */
private val CAST_PARTICLES = setOf(
    "de", "van", "von", "der", "den", "ten", "ter",
    "le", "la", "di", "du", "bin", "bint", "al", "el", "ap", "ab", "af",
)

fun parseCastNames(raw: String?): List<String> {
    if (raw.isNullOrBlank()) return emptyList()
    val chunks = if (',' !in raw) {
        val words = raw.trim().split(Regex("\\s+"))
        if (words.size > 3) return emptyList()
        listOf(raw.trim())
    } else {
        raw.split(",")
    }
    return chunks.mapNotNull { chunk ->
        val name = chunk.trim().replace(Regex("\\s+"), " ")
        if (name.isEmpty()) return@mapNotNull null
        val words = name.split(" ")
        if (words.size > 4) return@mapNotNull null
        if (words.any { !isNameWord(it) }) return@mapNotNull null
        name
    }.distinct().take(12)
}

private fun isNameWord(word: String): Boolean {
    if (word.isEmpty()) return false
    if (word.lowercase() in CAST_PARTICLES) return true
    // A name word starts with an uppercase letter (Unicode-aware) and holds
    // only letters, hyphens, apostrophes and periods.
    if (!word[0].isUpperCase()) return false
    return word.all { it.isLetter() || it == '-' || it == '\'' || it == '.' }
}
