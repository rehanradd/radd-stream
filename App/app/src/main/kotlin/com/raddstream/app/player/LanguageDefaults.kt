package com.raddstream.app.player

import com.raddstream.app.data.RegionChoices
import com.raddstream.app.data.UserRegion

/**
 * The language defaults (user order 2026-11-06): Pakistan and India watch Bollywood and
 * Hollywood in Hindi dub, so the Desi region defaults to Hindi audio with English subtitles;
 * the app itself is English in every region, because there is no UI locale switch anywhere
 * in this build — one `res/values`, no locale code — and English is the language the whole
 * interface is written in. Every default here is a default, not a lock: the Region screen
 * and the Settings chips let the viewer pick anything else, and an explicit pick always wins
 * over the region.
 *
 * The gap this closes: the Region screen only writes its defaults when the viewer taps
 * Continue on it. A viewer who never reaches it — an install from before regions existed,
 * a setup that skipped the question — kept null preferences, and null meant "the player's
 * own pick": audio by device locale (English on an English phone, the exact bug
 * [AudioTrackMatcher] was written to fix) and subtitles off. The region's own card is the
 * honest fallback for "never set", so the default holds for every install, not just the
 * ones that answered the question.
 *
 * Null keeps one meaning, and it is not "off". An explicit Off is stored as the literal
 * "Off" and an explicit "Player default" as its literal, so neither can be mistaken for a
 * viewer who never chose: only a stored null falls back to the region. A region with no
 * stance on a row (East Asian audio, International subtitles) falls back to null, which is
 * the player's own pick for audio and off for subtitles — exactly what those cards promise.
 */
object LanguageDefaults {

    /** The audio language in force: the stored pick, or the region's default when never set. */
    fun effectiveAudioLanguage(stored: String?, regionId: String): String? {
        stored?.trim()?.takeIf { it.isNotEmpty() }?.let { return it }
        return RegionChoices.byId(regionId).audioLanguage
    }

    /** The subtitle language in force: the stored pick, or the region's default when never set. */
    fun effectiveSubtitleLanguage(stored: String?, regionId: String): String? {
        stored?.trim()?.takeIf { it.isNotEmpty() }?.let { return it }
        return RegionChoices.byId(regionId).subtitleLanguage
    }

    /**
     * The second audio language for a region whose first does not cover every file.
     *
     * Hindi and Urdu are one spoken language in the films this catalog carries — a
     * Bollywood print speaks Hindustani and a Pakistani print speaks Urdu — but the tracks
     * are tagged separately (`hin` vs `urd`), so a Hindi-first viewer on an Urdu-only file
     * would hear the player's own pick instead of the language they understand. The
     * fallback is tried only after Hindi misses, never instead of it.
     */
    fun effectiveAudioFallback(regionId: String): String? =
        if (UserRegion.normalize(regionId) == UserRegion.DESI_DUBS) "Urdu" else null
}
