package com.raddstream.app.ui.components

import java.util.Locale

/**
 * App-design audit (2026-11-12): the app spoke in server words and rendered
 * raw numbers it had never validated. These pure helpers are the one place
 * that translation happens, so a screen never invents its own wording for
 * the same fact — and every rule here is unit-tested, because a rendering
 * bug ("★ 100.0", a literal "/PLOT" line) is only ever caught by a test
 * that feeds the bad input in.
 *
 * Rules:
 * - Ratings are 0–10. A 0–100 value (the catalog's old scale) is divided
 *   by 10; anything else unparseable or out of range renders nothing.
 * - Synopsis text never shows a section marker: lines that are only a
 *   "/WORD" marker ("/PLOT", "/SYNOPSIS", ...) are dropped.
 * - Quality bands carry an honest per-hour data estimate, in the same
 *   words the player quality sheet already uses.
 * - A title shown twice on one screen is the same title twice: rails
 *   dedupe on the work identity, not the row id.
 */
object UserWords {

    /**
     * The rating to paint for a raw catalog value, or null when nothing
     * honest can be shown. "100.0" becomes "10.0" (the old 0–100 scale);
     * "8.6" stays "8.6"; "abc", "-1", "101" and blanks show no badge.
     */
    fun displayRating(raw: String?): String? {
        val value = raw?.trim()?.toDoubleOrNull() ?: return null
        val onTen = when {
            value < 0 -> return null
            value <= 10.0 -> value
            value <= 100.0 -> value / 10.0
            else -> return null
        }
        return String.format(Locale.US, "%.1f", onTen)
    }

    /**
     * Drop section-marker lines ("/PLOT", "/SYNOPSIS", ...) from synopsis
     * text. A marker is a line whose first non-blank characters are "/"
     * followed by letters only. Ordinary text — including a "/" inside a
     * sentence — is untouched.
     */
    fun stripSectionMarkers(text: String): String {
        val marker = Regex("""^/[A-Za-z][A-Za-z ]*$""")
        return text.lineSequence()
            .filterNot { marker.matches(it.trim()) }
            .joinToString("\n")
            .trim()
    }

    /**
     * Honest data use for one quality band, or null when the band names
     * no known quality. The numbers match the player quality sheet
     * ([com.raddstream.app.player.qualityCostPerHour]) — one table, two
     * readers, so the detail screen can never quote a different cost
     * than the picker the viewer is about to tap.
     */
    fun dataEstimateForQuality(band: String): String? = when (band.trim().lowercase()) {
        "2160p", "4k", "uhd" -> "≈ 7–11 GB/hour"
        "1080p", "fullhd", "fhd" -> "≈ 3 GB/hour"
        "720p", "hd" -> "≈ 1.5 GB/hour"
        "480p" -> "≈ 700 MB/hour"
        "360p", "sd" -> "≈ 300 MB/hour"
        else -> null
    }

    /**
     * Make a long unbroken title breakable on word boundaries only.
     * Compose breaks a token like "Kesariya@100" mid-token when the card
     * is too narrow ("Kesariya@1 / 00"). A zero-width space before "@"
     * and after "-", "/" and "_" gives the layout a boundary to use —
     * "@100" itself is never split — and the characters are invisible
     * and unheard (the spoken title is the raw string, elsewhere).
     */
    fun breakableTitle(title: String): String = title
        .replace("@", "\u200B@")
        .replace("-", "-\u200B")
        .replace("/", "/\u200B")
        .replace("_", "_\u200B")
     * is the work identity (work ref, or normalised title + year) — never
     * the row id, because the same film filed twice has two row ids.
     * Returns the kept items and the grown seen set, so rails filter in
     * order, first rail wins.
     */
    fun <T> dedupeAcrossRails(
        items: List<T>,
        seen: Set<String>,
        keyOf: (T) -> String,
    ): Pair<List<T>, Set<String>> {
        val kept = ArrayList<T>(items.size)
        val next = seen.toMutableSet()
        for (item in items) {
            val key = keyOf(item)
            if (key.isBlank() || next.add(key)) kept.add(item)
        }
        return kept to next
    }
}
