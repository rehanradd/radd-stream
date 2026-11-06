package com.raddstream.app.ui.theme

import androidx.compose.ui.graphics.Color

/**
 * Pure theme resolution, kept out of MainActivity so a unit test can judge it
 * without an Activity: the operator's panel theme (`mode` + `accent`) plus
 * the system setting, in — a colour and a dark/light answer, out.
 *
 * `mode` is "dark", "light" or "system". Anything else (a typo on the panel,
 * an older body) resolves dark, because the app has always been dark and a
 * broken knob must never paint a half-light screen.
 */
fun resolveThemeDark(mode: String, systemDark: Boolean): Boolean = when (mode) {
    "light" -> false
    "system" -> systemDark
    else -> true
}

/**
 * The operator's accent as a [Color], or null when there is none to apply.
 * "" means "the brand default"; a #RRGGBB hex is the only other shape
 * accepted, so a typo paints nothing rather than a wrong colour.
 */
fun parseAccentHex(accent: String): Color? {
    if (accent.isEmpty()) return null
    if (accent.length != 7 || accent[0] != '#') return null
    if (!accent.substring(1).all { it in '0'..'9' || it in 'a'..'f' || it in 'A'..'F' }) {
        return null
    }
    return try {
        Color(accent.substring(1).toLong(16) or 0xFF000000L)
    } catch (_: NumberFormatException) {
        null
    }
}

/**
 * The ink that stays readable on an operator accent: a light accent gets the
 * brand's dark ink, a dark accent gets white — the same 0.5 luminance rule the
 * brand's own on-primary pair follows. Pure, so a unit test can judge it
 * without a composition.
 */
fun accentOnPrimary(accent: Color): Color =
    if (luminance(accent) > 0.5f) RaddDeepCurrentInk else Color.White
