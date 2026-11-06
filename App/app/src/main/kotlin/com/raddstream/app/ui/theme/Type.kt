package com.raddstream.app.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.sp
import com.raddstream.app.R
import com.raddstream.app.brand.Brand
import kotlin.math.round

// ═════════════════════════════════════════════════════════════════════════════
//  RADD STREAM TYPOGRAPHY — "CURRENT" TYPE SYSTEM                     v2.0
// ═════════════════════════════════════════════════════════════════════════════
//  TYPEFACE DIRECTION
//  Two roles, one voice:
//   • DISPLAY (posters' titles, screen titles, hero text): "Outfit" (SIL OFL
//     1.1), bundled at res/font/outfit_variable.ttf. Cinematic at 57sp,
//     still clear at 14sp.
//   • TEXT/UI (body, buttons, metadata): "Inter" (SIL OFL 1.1), bundled at
//     res/font/inter_variable.ttf — the reference screen-grotesque; excellent
//     small-size hinting on low-dpi phones.
//  The two vals below point at the bundled files. The brand keys
//  `typography.display_family` / `typography.text_family` no longer select a
//  face (they used to pick a platform family before the fonts were bundled);
//  the scale key still works — see RaddTypeScale below.
//
//  SMALL-PHONE RULES (min ~360×640dp, 1080p LCD, finger-smudged):
//   • Minimum rendered text on any surface: 11sp (labelSmall), used only for
//     badges/pills, never for more than one short line.
//   • Line heights are ≥1.4× font size for every body role — tighter lines
//     collapse on cheap panels when text wraps over poster-pilled metadata.
//   • Positive letter-spacing on anything ≤14sp (0.2–0.5sp), negative only
//     ≥26sp. This is the opposite of print convention and is deliberate:
//     small screens need air between glyphs, big screens need rhythm.
//   • Weights do the hierarchy work, not tiny size deltas: 400 body,
//     500 emphasis, 600 titles, 700 hero — a 200-weight range that survives
//     fallback-to-Roboto and still holds up with the bundled pair later.
// ═════════════════════════════════════════════════════════════════════════════

/** The bundled display face: Outfit (variable, SIL OFL 1.1), res/font/outfit_variable.ttf. */
val RaddDisplayFamily: FontFamily = FontFamily(Font(R.font.outfit_variable))

/** The bundled text face: Inter (variable, SIL OFL 1.1), res/font/inter_variable.ttf. */
val RaddTextFamily: FontFamily = FontFamily(Font(R.font.inter_variable))

/**
 * Brand text multiplier from `typography.scale` — one number in brand.properties
 * grows or shrinks the whole type ramp for the target device class.
 */
val RaddTypeScale: Float = Brand.typeScale

/** Brand-scaled font size: the only sanctioned way to write an sp size here. */
fun brandSp(value: Number): TextUnit {
    val scaled = value.toFloat() * RaddTypeScale
    val rounded = if (scaled % 1f == 0f) scaled else round(scaled * 100f) / 100f
    return rounded.sp
}

// ── Numeric / tabular styles ────────────────────────────────────────────────
// File sizes, bitrates, page counts, latency ms — anything a user compares
// row-to-row. tnum pins digit widths so "1.4 GB" and "9.7 GB" share a column;
// letterSpacing 0 and a slightly heavier weight keep table rows scannable.

/** Sizes, bitrates, timestamps in tables and release rows. */
val RaddNumeric = TextStyle(
    fontFamily = RaddTextFamily,
    fontWeight = FontWeight.Medium,
    fontSize = brandSp(13),
    lineHeight = brandSp(18),
    letterSpacing = brandSp(0),
    fontFeatureSettings = "tnum",
)

/** Larger stat readouts (server diagnostics card). */
val RaddStatNumeric = TextStyle(
    fontFamily = RaddTextFamily,
    fontWeight = FontWeight.SemiBold,
    fontSize = brandSp(20),
    lineHeight = brandSp(26),
    letterSpacing = brandSp(-0.2),
    fontFeatureSettings = "tnum",
)

// ── The scale ───────────────────────────────────────────────────────────────
// M3 role names, brand metrics. Display/Hero roles lean 30sp+ but stay below
// full M3 sizes so one-line titles never ellipsize on 360dp-wide phones.

val RaddTypography = Typography(
    // Display — hero/detail titles only, always on a scrim or solid ink.
    displayLarge = TextStyle(
        fontFamily = RaddDisplayFamily, fontWeight = FontWeight.Bold,
        fontSize = brandSp(40), lineHeight = brandSp(48), letterSpacing = brandSp(-0.5),
    ),
    displayMedium = TextStyle(
        fontFamily = RaddDisplayFamily, fontWeight = FontWeight.Bold,
        fontSize = brandSp(34), lineHeight = brandSp(42), letterSpacing = brandSp(-0.4),
    ),
    displaySmall = TextStyle(
        fontFamily = RaddDisplayFamily, fontWeight = FontWeight.SemiBold,
        fontSize = brandSp(28), lineHeight = brandSp(36), letterSpacing = brandSp(-0.2),
    ),

    // Headline — screen titles, section heads.
    headlineLarge = TextStyle(
        fontFamily = RaddDisplayFamily, fontWeight = FontWeight.SemiBold,
        fontSize = brandSp(24), lineHeight = brandSp(32), letterSpacing = brandSp(0),
    ),
    headlineMedium = TextStyle(
        fontFamily = RaddDisplayFamily, fontWeight = FontWeight.SemiBold,
        fontSize = brandSp(20), lineHeight = brandSp(28), letterSpacing = brandSp(0.1),
    ),
    headlineSmall = TextStyle(
        fontFamily = RaddDisplayFamily, fontWeight = FontWeight.Medium,
        fontSize = brandSp(18), lineHeight = brandSp(26), letterSpacing = brandSp(0.1),
    ),

    // Title — card titles, nav labels, list primaries.
    titleLarge = TextStyle(
        fontFamily = RaddTextFamily, fontWeight = FontWeight.Medium,
        fontSize = brandSp(17), lineHeight = brandSp(24), letterSpacing = brandSp(0.1),
    ),
    titleMedium = TextStyle(
        fontFamily = RaddTextFamily, fontWeight = FontWeight.Medium,
        fontSize = brandSp(15), lineHeight = brandSp(22), letterSpacing = brandSp(0.15),
    ),
    titleSmall = TextStyle(
        fontFamily = RaddTextFamily, fontWeight = FontWeight.Medium,
        fontSize = brandSp(14), lineHeight = brandSp(20), letterSpacing = brandSp(0.15),
    ),

    // Body — synopsis, messages, list secundaries.
    bodyLarge = TextStyle(
        fontFamily = RaddTextFamily, fontWeight = FontWeight.Normal,
        fontSize = brandSp(16), lineHeight = brandSp(24), letterSpacing = brandSp(0.3),
    ),
    bodyMedium = TextStyle(
        fontFamily = RaddTextFamily, fontWeight = FontWeight.Normal,
        fontSize = brandSp(14), lineHeight = brandSp(20), letterSpacing = brandSp(0.25),
    ),
    bodySmall = TextStyle(
        fontFamily = RaddTextFamily, fontWeight = FontWeight.Normal,
        fontSize = brandSp(12), lineHeight = brandSp(17), letterSpacing = brandSp(0.3),
    ),

    // Label — chips, badges, buttons, metadata. All ≥4.5:1 by role pairing.
    labelLarge = TextStyle(
        fontFamily = RaddTextFamily, fontWeight = FontWeight.Medium,
        fontSize = brandSp(14), lineHeight = brandSp(20), letterSpacing = brandSp(0.1),
    ),
    labelMedium = TextStyle(
        fontFamily = RaddTextFamily, fontWeight = FontWeight.Medium,
        fontSize = brandSp(12), lineHeight = brandSp(16), letterSpacing = brandSp(0.4),
    ),
    labelSmall = TextStyle(
        fontFamily = RaddTextFamily, fontWeight = FontWeight.Medium,
        fontSize = brandSp(11), lineHeight = brandSp(15), letterSpacing = brandSp(0.5),
    ),
)
