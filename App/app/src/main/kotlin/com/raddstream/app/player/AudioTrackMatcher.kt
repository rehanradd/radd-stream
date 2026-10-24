package com.raddstream.app.player

/*
 * ─────────────────────────────────────────────────────────────────────────────
 *  DUAL AUDIO — deciding which sound the user actually asked for
 * ─────────────────────────────────────────────────────────────────────────────
 * Half of this catalog is dual audio: the same file carries a Hindi track and an
 * English track (anime carries Japanese and a dub). Media3 picks a track with its own
 * locale heuristics, which is wrong here in a specific, boring way — it reads the
 * device locale, not what the user set for this app, and it happily plays English on a
 * Hindi-first user whose phone is set to English.
 *
 * This file is the decision. It is deliberately plain Kotlin: NO android.* and NO
 * androidx.media3 import, because a rule nobody can run on a JVM is a rule nobody can
 * trust. The player layer maps its own `Tracks` into [AudioCandidate] rows, calls
 * [AudioTrackMatcher.match], and maps the returned id back into a
 * `TrackSelectionOverride`. Everything that is hard — BCP-47 sloppiness, tracks whose
 * only clue is a human label, the difference between "no preference matched" and
 * "preference already satisfied" — lives here where a unit test can reach it.
 */

/**
 * One audio track, reduced to what a language decision needs.
 *
 * [id] is opaque on purpose: it is whatever the caller can turn back into a selection
 * (Media3's `g<group>-t<index>` in the player), so this policy never has to know how a
 * track is addressed. [selected] is the player's own answer, not a guess — idempotence
 * depends on it. [supported] is kept because recommending a track the renderer cannot
 * decode would be a promise the caller cannot keep.
 */
data class AudioCandidate(
    val id: String,
    val language: String? = null,
    val label: String? = null,
    val selected: Boolean = false,
    val supported: Boolean = true,
)

/**
 * Pure audio-track policy: given what the stream offers and what the user prefers, say
 * which track to select — or say nothing.
 *
 * No side effects, no I/O, no Android: the whole class is safe to call from a JVM test
 * and from any thread.
 */
object AudioTrackMatcher {

    /**
     * Collapses any spelling of a language — a BCP-47 primary subtag, its ISO-639-1 or
     * ISO-639-2 form, a 639-2/B variant, or the English name a lazy muxer typed into the
     * atom — to one canonical 3-letter code. Region and variant subtags are dropped;
     * unknown text comes back lowercased so a caller can still compare it honestly.
     *
     * WHY THIS EXISTS: "hi" and "hin" are the same language written by two different
     * standards (ISO-639-1 and ISO-639-2/T), and which one a stream uses depends on who
     * muxed it, not on what it contains. MP4 `©lan` atoms ship 3-letter, HLS `CODECS`/
     * manifest `LANGUAGE=` attributes ship either, and Media3 hands the string through
     * untouched. Comparing the two literally would make a Hindi-first user's preference
     * silently miss every Hindi track that the packager happened to call "hi" — exactly
     * the bug this feature is here to fix. Only the languages this catalog actually
     * carries are tabled; guessing at the rest would invent mappings nobody can audit.
     */
    fun canonicalLanguageCode(tag: String?): String? {
        val primary = tag?.trim()?.lowercase()
            ?.substringBefore('-')
            ?.substringBefore('_')
            ?.takeWhile { it in 'a'..'z' }
            ?.takeIf { it.isNotEmpty() }
            ?: return null
        return TWO_TO_THREE[primary] ?: VARIANT_TO_CANONICAL[primary]
            ?: NAME_TO_CODE[primary] ?: primary
    }

    /**
     * Which track to select, or null meaning "leave the player's own default alone".
     *
     * WHY NULL IS A REAL ANSWER: two different situations both end with no candidate —
     * the stream has nothing in the user's language, and the user's language is already
     * playing. In both, forcing a selection would make the app worse than doing nothing:
     * the first would pick a track that is not what anybody asked for, the second would
     * rewrite a working override and re-initialise the audio renderer mid-playback. The
     * caller treats null as "no change", which is the honest reading of both.
     *
     * Precedence is the ladder a human would climb: an exact tag match on the preferred
     * language wins; then a track whose label merely says the name ("Hindi", "[EN]",
     * "Multi Audio (Japanese)"), because plenty of packs carry no language atom at all;
     * then the same two steps for the fallback language; then nothing.
     */
    fun match(
        tracks: List<AudioCandidate>,
        preferred: String?,
        fallback: String? = null,
    ): String? {
        if (tracks.isEmpty()) return null
        val requests = listOfNotNull(languageRequestFor(preferred), languageRequestFor(fallback))
            .distinctBy { it.code ?: it.name }
        for (request in requests) {
            when (val pick = pickFor(tracks, request)) {
                is Pick.One -> return pick.id
                // The preference is already playing: stopping here is the point, not a
                // failure, so a lower-ranked fallback must not steal the choice.
                Pick.Satisfied -> return null
                Pick.None -> Unit
            }
        }
        return null
    }

    /**
     * Next supported track after the current one, wrapping; null when cycling is not
     * worth offering (fewer than two playable tracks — swapping to the same sound is a
     * no-op the user reads as a broken button).
     *
     * [currentId] comes from the caller's UI state because after a manual pick the player
     * may not have reported the change back yet; without it the gesture would step on the
     * track already chosen. With neither a hint nor a flag, the player's own default is
     * its first track, which is the same assumption Media3 makes.
     */
    fun cycle(tracks: List<AudioCandidate>, currentId: String? = null): String? {
        val pool = tracks.filter { it.supported }
        if (pool.size < 2) return null
        val byId = pool.indexOfFirst { it.id == currentId }
        val byFlag = pool.indexOfFirst { it.selected }
        val index = when {
            byId >= 0 -> byId
            byFlag >= 0 -> byFlag
            else -> 0
        }
        return pool[(index + 1) % pool.size].id
    }

    /** The English name for one language, when this catalog knows it; null otherwise. */
    fun displayName(tag: String?): String? = canonicalLanguageCode(tag)?.let { CODE_TO_NAME[it] }

    // ── internals ────────────────────────────────────────────────────────────────

    private sealed interface Pick {
        data object None : Pick
        data object Satisfied : Pick
        data class One(val id: String) : Pick
    }

    /** A resolved preference: a canonical code when one is known, plus the text to hunt for. */
    private data class LanguageRequest(val code: String?, val name: String)

    private fun languageRequestFor(raw: String?): LanguageRequest? {
        val text = raw?.trim()?.lowercase()?.takeIf { it.isNotEmpty() } ?: return null
        val code = canonicalLanguageCode(text)?.takeIf { CODE_TO_NAME.containsKey(it) }
        return LanguageRequest(code = code, name = code?.let { CODE_TO_NAME[it] } ?: text)
    }

    private fun pickFor(tracks: List<AudioCandidate>, request: LanguageRequest): Pick {
        // Tag match first: a declared language outranks whatever a label happens to say.
        val byTag = if (request.code == null) emptyList() else
            tracks.filter { canonicalLanguageCode(it.language) == request.code }
        decide(byTag)?.let { return it }

        // Label match second, for tracks that never declared a language worth trusting, so
        // a track already judged by its own atom is never re-judged by its decoration.
        val byLabel = tracks.filter {
            !declaresLanguage(it.language) && mentionsLanguage(it.label, request)
        }
        decide(byLabel)?.let { return it }

        return Pick.None
    }

    /**
     * Turns a ranked candidate list into a decision. Already-selected wins over
     * available: a matching track that plays is the request being fulfilled, and there is
     * nothing left for the policy to do about it.
     */
    private fun decide(matches: List<AudioCandidate>): Pick? {
        if (matches.isEmpty()) return null
        if (matches.any { it.selected }) return Pick.Satisfied
        val usable = matches.firstOrNull { it.supported } ?: return null
        return Pick.One(usable.id)
    }

    /** True when the atom names a language this catalog is known to carry. */
    private fun declaresLanguage(tag: String?): Boolean {
        val code = canonicalLanguageCode(tag) ?: return false
        return CODE_TO_NAME.containsKey(code)
    }

    /**
     * Human-label fallback: packagers write "Hindi", " Hindi Dubbed", "[EN]" and
     * "(Hin/Eng)" interchangeably, so a known language is matched by its name and by the
     * code as a standalone token.
     *
     * An unknown preference string is matched by token only, never by substring: "und" as
     * free text must not light up "Surrounded by reverb". The code test can still fire on a
     * label where an abbreviation is a real coincidence, which is precisely why a declared
     * language atom always outranks it.
     */
    private fun mentionsLanguage(label: String?, request: LanguageRequest): Boolean {
        val text = label?.trim()?.takeIf { it.isNotEmpty() } ?: return false
        val code = request.code
        if (code == null) return matchesToken(text, request.name)
        if (text.contains(request.name, ignoreCase = true)) return true
        val short = TWO_TO_THREE.entries.firstOrNull { it.value == code }?.key
        return listOf(code, short).filterNotNull().any { matchesToken(text, it) }
    }

    private fun matchesToken(text: String, token: String): Boolean =
        Regex("""\b""" + Regex.escape(token) + """\b""", RegexOption.IGNORE_CASE).containsMatchIn(text)

    // ── language tables ──────────────────────────────────────────────────────

    /**
     * The catalog's language set, ISO-639-1 to ISO-639-2/T. Indian dubs are the reason
     * this table is not just "en/ja/es" — South Indian releases arrive as "ta"/"te" as
     * often as "tam"/"tel".
     */
    private val TWO_TO_THREE = mapOf(
        "hi" to "hin", "en" to "eng", "ja" to "jpn", "ta" to "tam", "te" to "tel",
        "ml" to "mal", "kn" to "kan", "bn" to "ben", "pa" to "pan", "mr" to "mar",
        "gu" to "guj", "ur" to "urd", "es" to "spa", "fr" to "fra", "ko" to "kor",
        "zh" to "zho",
    )

    /** 639-2/B and retired forms still emitted by old muxers. */
    private val VARIANT_TO_CANONICAL = mapOf(
        "jap" to "jpn", "fre" to "fra", "chi" to "zho",
    )

    /** Display names double as the label-matching vocabulary. */
    private val CODE_TO_NAME = mapOf(
        "hin" to "Hindi", "eng" to "English", "jpn" to "Japanese", "tam" to "Tamil",
        "tel" to "Telugu", "mal" to "Malayalam", "kan" to "Kannada", "ben" to "Bengali",
        "pan" to "Punjabi", "mar" to "Marathi", "guj" to "Gujarati", "urd" to "Urdu",
        "spa" to "Spanish", "fra" to "French", "kor" to "Korean", "zho" to "Chinese",
    )

    private val NAME_TO_CODE = CODE_TO_NAME.entries.associate { it.value.lowercase() to it.key }
}
