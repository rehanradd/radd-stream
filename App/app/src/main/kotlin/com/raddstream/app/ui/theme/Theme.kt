package com.raddstream.app.ui.theme

import android.os.Build
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.raddstream.app.brand.Brand

// ═════════════════════════════════════════════════════════════════════════════
//  RADD STREAM THEME — "CURRENT & UNDERTOW"                           v2.0
//  Full M3 role mapping, deliberate dynamic-color policy, motion tokens,
//  and the artwork-driven accent hook (see ArtworkAccent.kt for extraction).
// ═════════════════════════════════════════════════════════════════════════════

// ── DARK (the flagship scheme — "undertow") ─────────────────────────────────
// Every role pairing used for text was WCAG-checked in Color.kt; the scheme
// only re-homes those same verified paints into M3 roles.
private val RaddDarkScheme = darkColorScheme(
    // Primary = the current. Note onPrimary is DARK INK, not white: current500
    // is a high-luminance brand color and white-on-it measures 2.2:1 (fail).
    primary = RaddCurrent500,
    onPrimary = RaddDeepCurrentInk,
    primaryContainer = RaddCurrentContainerDark,
    onPrimaryContainer = RaddOnCurrentContainer,

    secondary = RaddCoral400,
    onSecondary = RaddDeepCurrentInk, // coral is icon-first; ink labels stay ≥4.5
    secondaryContainer = RaddCoralContainerDark,
    onSecondaryContainer = RaddOnCoralContainer,

    tertiary = RaddTideIndigo,
    onTertiary = RaddInk950,
    tertiaryContainer = RaddTideContainerDark,
    onTertiaryContainer = RaddOnTideContainer,

    error = RaddDanger,
    onError = RaddInk950,
    errorContainer = RaddHealthDeadPill,
    onErrorContainer = RaddHealthDead,

    background = RaddInk950,
    onBackground = RaddPaperOnInk,
    surface = RaddInk900,
    onSurface = RaddPaperOnInk,
    surfaceVariant = RaddInk800,
    onSurfaceVariant = RaddMistOnInk,
    outline = RaddInk600,
    outlineVariant = RaddInk700,
    scrim = RaddScrim,

    // Tone-based container tiers (M3): low→high elevation without shadows.
    surfaceDim = RaddInkVoid,
    surfaceBright = RaddInk750,
    surfaceContainerLowest = RaddInkVoid,
    surfaceContainerLow = RaddInk900,
    surfaceContainer = RaddInk850,          // recommended default card fill
    surfaceContainerHigh = RaddInk800,      // chips, text fields, nav pills
    surfaceContainerHighest = RaddInk750,   // dialogs, FAB-on-ink
)

// ── LIGHT ("daybreak") — same water at noon ─────────────────────────────────
// Currently under-leveraged: several screens hard-paint dark tokens via legacy
// aliases (docs/HANDOFF_apptime.md tracks migration). Until migrated the app
// stays dark-forced (see RaddStreamTheme default) so light mode never half-
// applies and looks broken.
private val RaddLightScheme = lightColorScheme(
    primary = RaddCurrent700,               // 5.8:1 on paper; white label 6.2:1
    onPrimary = RaddLightOnPrimary,          // brand colors.light.on_primary
    primaryContainer = RaddCurrentContainerLight,
    onPrimaryContainer = RaddOnCurrentContainerLight,

    secondary = RaddCoral400,               // ink label on coral: 6.7:1
    onSecondary = RaddInkOnPaper,
    secondaryContainer = RaddCoralContainerDark,
    onSecondaryContainer = RaddOnCoralContainer,

    tertiary = RaddTideContainerDark,       // dark chip persists in light (badges rule)
    onTertiary = RaddOnTideContainer,       // 11.1:1
    tertiaryContainer = RaddTideContainerDark,
    onTertiaryContainer = RaddOnTideContainer,

    error = RaddDangerLight,                // 6.1:1 on paper
    onError = RaddLightOnPrimary,            // white label on the brand error red
    errorContainer = RaddDangerContainerLight,
    onErrorContainer = RaddOnDangerContainerLight,

    background = RaddPaperDay,
    onBackground = RaddInkOnPaper,          // 16.1:1
    surface = RaddPaperSurface,
    onSurface = RaddInkOnPaper,
    surfaceVariant = RaddPaperContainerHigh,
    onSurfaceVariant = RaddMistOnPaper,     // 5.4:1 vs its variant tier
    outline = RaddOutlineOnPaper,
    outlineVariant = RaddOutlineVarOnPaper,

    surfaceDim = RaddPaperContainerLow,
    surfaceBright = RaddLightSurfaceBright,
    surfaceContainerLowest = RaddLightSurfaceBright,
    surfaceContainerLow = RaddPaperContainerLow,
    surfaceContainer = RaddPaperContainer,
    surfaceContainerHigh = RaddPaperContainerHigh,
    surfaceContainerHighest = RaddPaperContainerHighest,
)

// ── SHAPES — "river stone" radii ────────────────────────────────────────────
// Geometry language: nothing is a hard rectangle and nothing is a circle.
// Posters share the medium radius so grid and hero read as one pebble family.
val RaddShapes = Shapes(
    extraSmall = RoundedCornerShape(4.dp),
    small = RoundedCornerShape(8.dp),
    medium = RoundedCornerShape(12.dp),   // posters, chips
    large = RoundedCornerShape(16.dp),    // cards, sheets top
    extraLarge = RoundedCornerShape(28.dp), // dialogs, hero container
)

// ── MOTION — timing & easing tokens (import once, use everywhere) ───────────
// M3 conventions: state changes 100–200ms, entrance/exit 250–400ms, brand/
// hero moves up to 600ms. Easing is asymmetric: exit accelerates, entrance
// decelerates on the "emphasized" curve so content settles like water.
@Immutable
object RaddMotion {
    /** Toggle/ripple/color crossfade. */
    const val DurationQuick = 120
    /** Chip selection, icon state, tab indicator. */
    const val DurationDefault = 250
    /** Screen-level entrance, sheet expand, poster→detail share. */
    const val DurationEmphasized = 400
    /** Hero/fanfare only — first frame of DetailScreen, brand splash mark. */
    const val DurationSlow = 600

    /** Paired tween for standard property animation. */
    fun <T> quick(millis: Int = DurationQuick) = tween<T>(millis, easing = Standard)
    fun <T> default(millis: Int = DurationDefault) = tween<T>(millis, easing = EmphasizedDecelerate)
    fun <T> emphasized(millis: Int = DurationEmphasized) = tween<T>(millis, easing = EmphasizedDecelerate)

    /** General purpose in/out. */
    val Standard = CubicBezierEasing(0.2f, 0f, 0f, 1f)
    /** Entrance: fast start, long graceful settle. */
    val EmphasizedDecelerate = CubicBezierEasing(0.05f, 0.7f, 0.1f, 1f)
    /** Exit: gentle lean-in, brisk finish. */
    val EmphasizedAccelerate = CubicBezierEasing(0.3f, 0f, 0.8f, 0.15f)
    /** Full-duration brand moves only; expressive overshoot in the middle. */
    val Emphasized = CubicBezierEasing(0.2f, 0f, 0f, 1f)
    /** Linear-ish for continuous things (shimmer sweep). */
    val Linearish = CubicBezierEasing(0f, 0f, 1f, 1f)

    /** Respect Reduce-Motion: screens wrap durations with this. */
    const val FadeWhenReduced = 30 // ms, pure alpha crossfade, no movement
}

// ── SPACING GRID (4dp base; values are dp ints, not a theme type) ───────────
object RaddSpacing {
    val xs = 4.dp
    val sm = 8.dp
    val md = 12.dp
    val lg = 16.dp   // standard page gutter
    val xl = 24.dp
    val xxl = 32.dp
    val gutter = 16.dp
    val railGap = 8.dp      // between poster cards in a row/grid
    val sectionGap = 24.dp  // between home rails
    val thumbBarClearance = 24.dp // content padding under edge-to-edge nav
}

// ── DYNAMIC COLOR POLICY — decided, not defaulted ───────────────────────────
// Brand-locked (dynamicColor = false) is ON BY DEFAULT, and it is deliberate:
//  1. This app speaks a COLOR LANGUAGE: jade=stream/watch/healthy, indigo=
//     download, amber=print quality, red-family=dead/deprecated. Material You
//     would repaint `primary` from the wallpaper and silently break "jade
//     means playable" — the semantic scale in Color.kt survives dynamic mode
//     but users can no longer trust the *scheme* roles to mean anything.
//  2. The dark scheme's neutrals are tuned to artwork (teal-shifted near-black
//     behind posters); a wallpaper-derived neutral palette destroys the scrim
//     contrast math (Color.kt §10) that keeps overlaid badges AA.
//  3. Award-grade brand apps (the owner's brief) pin their identity and give
//     dynamism *around* it (wallpaper-tinted launcher icon via <monochrome>,
//     artwork-derived accents via rememberArtworkAccent) rather than *inside*
//     it. The artwork accent hook already delivers personalization per-title,
//     which is more meaningful than per-wallpaper.
// Escape hatch honored anyway: callers may pass dynamicColor = true on
// Android 12+ (Settings toggle can expose it; it only remaps the generic M3
// roles — every semantic Radd* token stays constant).
@Composable
fun RaddStreamTheme(
    // Both defaults come from brand.properties ([scheme]); a re-skin can flip
    // the app to light-first or allow Material You without touching any screen.
    darkTheme: Boolean = Brand.schemeDefaultDark,
    dynamicColor: Boolean = Brand.schemeDynamicColorDefault,
    content: @Composable () -> Unit,
) {
    val context = LocalContext.current
    val colorScheme = when {
        dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S ->
            if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        darkTheme -> RaddDarkScheme
        else -> RaddLightScheme
    }
    MaterialTheme(
        colorScheme = colorScheme,
        typography = RaddTypography,
        shapes = RaddShapes,
        content = content,
    )
}
