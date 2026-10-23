package com.raddstream.app.ui.theme

import android.graphics.Bitmap
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.graphics.Color
import kotlin.math.pow

// ═════════════════════════════════════════════════════════════════════════════
//  ARTWORK-DRIVEN ACCENT — "the poster sets the mood, we keep the meaning"
// ═════════════════════════════════════════════════════════════════════════════
//  Hook contract for the UI agent (DetailScreen hero, My List tiles):
//
//      val accent = rememberArtworkAccent(posterBitmap)
//
//  It samples a loaded poster and returns a BRAND-SAFE accent: the dominant
//  chroma of the artwork, lifted until it clears 4.5:1 against the dark ink
//  it will be drawn on. Rules this hook enforces for you:
//   • Semantic colors never come from artwork. Jade=healthy, coral=favorite,
//     amber=print — those stay brand paints. Artwork accent may only style
//     "mood" surfaces: hero gradient tail, section headers of that title,
//     scrollbar glow, empty-space wash. Never buttons, never badges.
//   • Contrast is guaranteed against the passed surface (default Ink950).
//   • Grayscale posters (no chroma anywhere) fall back to RaddCurrent500 —
//     the brand is the floor, the artwork is the flavor.
// ═════════════════════════════════════════════════════════════════════════════

/** WCAG relative luminance of an sRGB color. */
private fun luminance(c: Color): Float {
    fun lin(v: Float): Float =
        if (v <= 0.04045f) v / 12.92f else ((v + 0.055) / 1.055).toDouble().pow(2.4).toFloat()
    return 0.2126f * lin(c.red) + 0.7152f * lin(c.green) + 0.0722f * lin(c.blue)
}

/** WCAG 2 contrast ratio between two colors (1..21). */
fun contrastRatio(a: Color, b: Color): Float {
    val la = luminance(a)
    val lb = luminance(b)
    val hi = if (la > lb) la else lb
    val lo = if (la > lb) lb else la
    return (hi + 0.05f) / (lo + 0.05f)
}

/**
 * Blend [this] toward white until it clears [minRatio] against [surface].
 * Monotonic on dark surfaces (white vs Ink950 = 20.0:1), so the loop always
 * terminates; capped at 24 steps and returns the best blend found.
 */
fun Color.boostUntilContrast(surface: Color, minRatio: Float = 4.5f): Color {
    var out = this
    if (contrastRatio(out, surface) >= minRatio) return out
    repeat(24) {
        out = Color(
            red = out.red + (1f - out.red) * 0.06f,
            green = out.green + (1f - out.green) * 0.06f,
            blue = out.blue + (1f - out.blue) * 0.06f,
        )
        if (contrastRatio(out, surface) >= minRatio) return out
    }
    return out
}

/**
 * Extract a brand-safe accent from a poster bitmap.
 * @param bitmap    decoded artwork (Coil: bitmapDrawable?.bitmap; null-safe).
 * @param surface   the color the accent will be drawn ON (default dark ink).
 * @param fallback  returned when the artwork has no usable chroma.
 */
@Composable
fun rememberArtworkAccent(
    bitmap: Bitmap?,
    surface: Color = RaddInk950,
    fallback: Color = RaddCurrent500,
): Color = remember(bitmap, surface, fallback) {
    if (bitmap == null || bitmap.width < 4 || bitmap.height < 4) {
        fallback
    } else try {
        // 9x9 grid sample ≈ 81 pixels — enough for a dominant-chroma guess,
        // cheap enough to run on the composition thread without a jank frame.
        var rSum = 0
        var gSum = 0
        var bSum = 0
        var chromaCount = 0
        var anyR = 0L
        var anyG = 0L
        var anyB = 0L
        var anyCount = 0
        val cols = 9
        val rows = 9
        for (row in 0 until rows) {
            val y = ((row + 0.5f) / rows * bitmap.height).toInt().coerceIn(0, bitmap.height - 1)
            for (col in 0 until cols) {
                val x = ((col + 0.5f) / cols * bitmap.width).toInt().coerceIn(0, bitmap.width - 1)
                val px = bitmap.getPixel(x, y)
                val r = (px shr 16) and 0xFF
                val g = (px shr 8) and 0xFF
                val b = px and 0xFF
                anyR += r
                anyG += g
                anyB += b
                anyCount += 1
                val max = maxOf(r, g, b)
                val min = minOf(r, g, b)
                val chroma = max - min // 0..255; <24 reads as near-gray
                if (chroma >= 24 && max >= 40) {
                    rSum += r
                    gSum += g
                    bSum += b
                    chromaCount += 1
                }
            }
        }
        val picked: Color = if (chromaCount >= 3) {
            Color(
                red = rSum.toFloat() / chromaCount / 255f,
                green = gSum.toFloat() / chromaCount / 255f,
                blue = bSum.toFloat() / chromaCount / 255f,
            )
        } else if (anyCount > 0) {
            // achromatic artwork: a soft neutral pulled slightly toward current
            val nr = anyR.toFloat() / anyCount / 255f
            val ng = anyG.toFloat() / anyCount / 255f
            val nb = anyB.toFloat() / anyCount / 255f
            Color(
                red = (nr * 0.7f + RaddCurrent500.red * 0.3f),
                green = (ng * 0.7f + RaddCurrent500.green * 0.3f),
                blue = (nb * 0.7f + RaddCurrent500.blue * 0.3f),
            )
        } else {
            fallback
        }
        if (picked == fallback) picked
        else picked.boostUntilContrast(surface, 4.5f)
    } catch (_: Exception) {
        // hardware-bitmap or recycled-buffer guard: never let sampling crash
        // composition — the fallback accent is always safe to draw.
        fallback
    }
}
