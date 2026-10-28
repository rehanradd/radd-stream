package com.raddstream.app.ui.theme

import androidx.compose.ui.graphics.Color
import com.raddstream.app.BuildConfig
import com.raddstream.app.player.SubtitleColor

// ═════════════════════════════════════════════════════════════════════════════
//  RADD STREAM — "CURRENT & UNDERTOW" BRAND SYSTEM                    v3.0
// ═════════════════════════════════════════════════════════════════════════════
//  BRAND HEXES ARE NOT AUTHORED HERE ANYMORE. Every paint below is read from
//  BuildConfig constants that app/build.gradle.kts generates from
//  <repo root>/brand.properties ([colors.dark] / [colors.light]). Re-skinning
//  the palette is a one-file edit + rebuild; BrandDriftTest fails the build if
//  a raw hex creeps back into a non-theme file, and the ramp keys themselves are
//  validated at configuration time (bad hex = build error, not a grey app).
//  Extended semantic roles that are NOT part of the brand ramps (link-health
//  pills, print badges, scrims) keep their literal values here, documented as
//  app-local paint in design/DESIGN_SYSTEM.md.
//
//  [brandColor] is a pure-Kotlin hex parser (no android.graphics.Color, no
//  Compose string overload) so these vals also initialise safely on the JVM.
//  Identity concept: the interface is deep water at night (teal-shifted ink
//  neutrals = "Undertow"); the single action color is an electric jade current
//  (#2BC79A) that reads as motion, not as a red "buy" button. Warm coral is
//  reserved for affection (favorites), amber-signal for quality/print badges,
//  and a full semantic scale encodes LINK STATE — because in a source-link
//  aggregator, link health is a first-class citizen, not an afterthought.
//
//  Every text pair below was computed against its stated background using the
//  WCAG 2.x relative-luminance formula; ratios are noted inline. AA body text
//  needs ≥4.5:1, large text / UI graphics need ≥3:1. AAA body = ≥7:1.
//
//  Token naming: `Radd*` values are BRAND ROLES (raw paint).
//  MaterialTheme.colorScheme maps them to M3 ROLES in Theme.kt — screens should
//  prefer `MaterialTheme.colorScheme.<role>` over importing these vals directly.
//  The `Legacy alias` section at the bottom keeps every name that existed in
//  Color.kt v1 so files outside ui/theme keep compiling while they migrate.
// ═════════════════════════════════════════════════════════════════════════════


// ── 0. BRAND HEX PARSER (single source: brand.properties -> BuildConfig) ─────
/** Accepts the brand file format only: '#RRGGBB' or '#AARRGGBB'. */
internal fun brandColor(hex: String): Color {
    val body = hex.trim().removePrefix("#")
    val digits = when (body.length) {
        6 -> "FF$body"
        8 -> body
        else -> error("brand.properties colour '$hex' must be #RRGGBB or #AARRGGBB")
    }
    val value = digits.toLongOrNull(16)
        ?: error("brand.properties colour '$hex' is not hexadecimal")
    val alpha = ((value shr 24) and 0xFF).toFloat() / 255f
    val red = ((value shr 16) and 0xFF).toFloat() / 255f
    val green = ((value shr 8) and 0xFF).toFloat() / 255f
    val blue = (value and 0xFF).toFloat() / 255f
    return Color(red = red, green = green, blue = blue, alpha = alpha)
}

// ── 0b. CAPTION PAINT — app-local, not a brand ramp ──────────────────────────
/**
 * The subtitle colour a viewer picked, as Compose paint. This is the only place the choice
 * becomes a [Color]: the SRT/VTT overlay and the sheet's own swatches both read it, so no
 * screen paints a caption value of its own and the native path keeps its separate int.
 *
 * These four are functional caption colours, not identity, which is why they are not brand
 * ramp keys — the same reason the print badges and scrims below are literals here.
 */
internal fun SubtitleColor.paint(): Color = Color(
    red = red / 255f,
    green = green / 255f,
    blue = blue / 255f,
)

// ── 1. UNDERTOW neutrals — dark scheme ──────────────────────────────────────
// Hue ≈ 195° (teal-shifted), never pure grey, never blue-black "Netflix ink".

/** surfaceContainerLowest — the absolute floor under raised cards. */
val RaddInkVoid          = brandColor(BuildConfig.BRAND_COLORS_DARK_SURFACE_FLOOR)
/** background — the app canvas. Near-black with a teal undertow. */
val RaddInk950           = brandColor(BuildConfig.BRAND_COLORS_DARK_BACKGROUND)
/** surface — sheets, bottom bars, elevated base tone. */
val RaddInk900           = brandColor(BuildConfig.BRAND_COLORS_DARK_SURFACE)
/** surfaceContainer — cards, list rows, poster metadata blocks. */
val RaddInk850           = brandColor(BuildConfig.BRAND_COLORS_DARK_SURFACE_CONTAINER)
/** surfaceContainerHigh — chips, inputs, hovered/pressed resting fills. */
val RaddInk800           = brandColor(BuildConfig.BRAND_COLORS_DARK_SURFACE_CONTAINER_HIGH)
/** surfaceContainerHighest — the brightest raised tier (dialogs, FABs on ink). */
val RaddInk750           = brandColor(BuildConfig.BRAND_COLORS_DARK_SURFACE_CONTAINER_HIGHEST)
/** outlineVariant — 1dp dividers, poster borders. Graphics: 3:1 not required. */
val RaddInk700           = brandColor(BuildConfig.BRAND_COLORS_DARK_OUTLINE_VARIANT)
/** outline — borders that must stay visible but never compete with content. */
val RaddInk600           = brandColor(BuildConfig.BRAND_COLORS_DARK_OUTLINE)

/** onSurface — primary text on any Ink tier. 16.7:1 vs 950, 14.4:1 vs 850. */
val RaddPaperOnInk       = brandColor(BuildConfig.BRAND_COLORS_DARK_TEXT)
/** onSurfaceVariant — secondary text, unfilled icons. 8.6:1 vs 850, 10.1:1 vs 950. */
val RaddMistOnInk        = brandColor(BuildConfig.BRAND_COLORS_DARK_TEXT_SECONDARY)
/** Muted metadata (year, source_site, timestamps). 6.4:1 vs 800, 7.2:1 vs 850 — AA. */
val RaddWhisperOnInk     = brandColor(BuildConfig.BRAND_COLORS_DARK_TEXT_MUTED)

// ── 2. CURRENT — primary action ramp ────────────────────────────────────────
// The signature. ONE color for "do this now". It is deliberately bright, so
// text ON it must be dark ink (never white — white on current is 2.2:1, FAIL).

/** current100 — lightest tint, used only inside light-mode containers. */
val RaddCurrent100       = brandColor(BuildConfig.BRAND_COLORS_LIGHT_PRIMARY_CONTAINER)
/** current200 — light-mode onCurrentContainer text support / dark chips text. */
val RaddCurrent200       = Color(0xFFA9EFD4)
/** current400 — hover/active icon glow state, progress halo. 12.1:1 vs 950. */
val RaddCurrent400       = brandColor(BuildConfig.BRAND_COLORS_DARK_PRIMARY_HOVER)
/** current500 — BRAND PRIMARY. Icons, selected tabs, text accents. 9.3:1 vs 950 (AAA), 7.0:1 vs 800 (AAA). */
val RaddCurrent500       = brandColor(BuildConfig.BRAND_COLORS_DARK_PRIMARY)
/** current600 — pressed state on dark surfaces. 5.8:1 vs 950 — passes AA body text too. */
val RaddCurrent600       = brandColor(BuildConfig.BRAND_COLORS_DARK_PRIMARY_PRESSED)
/** current700 — LIGHT-MODE primary. 5.8:1 on PaperDay bg; white label on it = 6.2:1 AA. */
val RaddCurrent700       = brandColor(BuildConfig.BRAND_COLORS_LIGHT_PRIMARY)
/** primaryContainer (dark). Pair with onPrimaryContainer below. */
val RaddCurrentContainerDark = brandColor(BuildConfig.BRAND_COLORS_DARK_PRIMARY_CONTAINER)
/** onPrimaryContainer text on CurrentContainerDark: 10.3:1 AAA. */
val RaddOnCurrentContainer   = brandColor(BuildConfig.BRAND_COLORS_DARK_ON_PRIMARY_CONTAINER)
/** onPrimary — the ONLY legal text/icon color on current500+ fills. 7.4:1 vs 500 (AAA). */
val RaddDeepCurrentInk  = brandColor(BuildConfig.BRAND_COLORS_DARK_ON_PRIMARY)

// ── 3. CORAL — secondary / affection ────────────────────────────────────────
// Favorites heart, "in your list" state. Coral is NEVER used for destructive
// actions (that is Danger) and never as a full-bleed surface.

/** coral400 — favorite icon, badge dot. 7.8:1 vs 950 (graphics AAA). */
val RaddCoral400         = brandColor(BuildConfig.BRAND_COLORS_DARK_SECONDARY)
/** secondaryContainer (dark) + its on-color: 9.7:1. */
val RaddCoralContainerDark = brandColor(BuildConfig.BRAND_COLORS_DARK_SECONDARY_CONTAINER)
val RaddOnCoralContainer   = brandColor(BuildConfig.BRAND_COLORS_DARK_ON_SECONDARY_CONTAINER)

// ── 4. TIDE INDIGO — tertiary ───────────────────────────────────────────────
// Download-vs-stream affordance and quiet progress accents. A cool blue that
// says "moving to device", never confused with the jade "watch now".

/** tideIndigo — download arrow, offline badge text. 8.8:1 vs 950. */
val RaddTideIndigo       = brandColor(BuildConfig.BRAND_COLORS_DARK_TERTIARY)
val RaddTideContainerDark = brandColor(BuildConfig.BRAND_COLORS_DARK_TERTIARY_CONTAINER)
val RaddOnTideContainer   = brandColor(BuildConfig.BRAND_COLORS_DARK_ON_TERTIARY_CONTAINER)

// ── 5. SIGNAL GOLD — ratings & premium prints ──────────────────────────────
/** signalGold — IMDb star, HDR/4K print badge. 13.0:1 vs 950, 11.2:1 vs 850. */
val RaddSignalGold       = brandColor(BuildConfig.BRAND_COLORS_DARK_ACCENT_GOLD)
/** bullion — "paid/entitlement" badge text on amber pills. 10.8:1 vs SignalPillInk. */
val RaddBullion          = Color(0xFFFFD57F) // app-local tint (not a brand ramp role)

// ── 6. LINK HEALTH semantics (the app's superpower) ─────────────────────────
// Source-link lifecycle in a JIT-resolving aggregator. Each has a text color
// (AA on its own dark pill) and a container. Never encode health by color
// alone — every pill also carries an icon + label (see DESIGN_SYSTEM.md §6).

/** healthy — <500ms, active sources. 9.0:1 vs its pill, 12.2:1 vs bg. */
val RaddHealthOk         = brandColor(BuildConfig.BRAND_COLORS_DARK_LINK_HEALTHY)
val RaddHealthOkPill     = Color(0xFF0D2E20)
/** slow — responding but >~2s. Same paint as Signal Gold (verified 9.8:1 on pill). */
val RaddHealthSlow       = brandColor(BuildConfig.BRAND_COLORS_DARK_LINK_SLOW)
val RaddHealthSlowPill   = Color(0xFF33240A)
/** expired — ephemeral link known to rot (temporary/torrent style). 7.5:1 on pill. */
val RaddHealthExpired    = brandColor(BuildConfig.BRAND_COLORS_DARK_LINK_EXPIRED)
val RaddHealthExpiredPill = Color(0xFF33200F)
/** dead — fails resolution; show struck-through, 60% alpha, never deleted. 5.9:1 on pill. */
val RaddHealthDead       = brandColor(BuildConfig.BRAND_COLORS_DARK_LINK_DEAD)
val RaddHealthDeadPill   = Color(0xFF3A1417)

// ── 7. ACTION affordances: stream vs download ──────────────────────────────
/** streamLabel — "Watch now" pill text (current500 paint, own pill 6.9:1). */
val RaddStreamPill       = RaddCurrentContainerDark
/** downloadLabel — "Keep offline" pill text on Tide container. 7.8:1. */
val RaddDownloadPill     = Color(0xFF16233B)
/** downloadLabel text = RaddTideBlue: 7.8:1 vs RaddDownloadPill. */
val RaddTideBlue         = Color(0xFF8FB8FF)

// ── 8. PRINT / QUALITY badges (BluRay > WEB-DL > HDR flavor > CAM) ─────────
// Badges over ARTWORK always sit on RaddArtScrim (see §10). Ratios below are
// label-vs-own-pill on solid ink; they only improve on scrim because scrim is
// darker than any artwork under 70% black.

/** 4K / Dolby-Vision / HDR prints — gold family. 10.8:1 vs RaddHdrPill. */
val RaddHdrLabel         = Color(0xFFFFD57F)
val RaddHdrPill          = Color(0xFF33240A)
/** BluRay / remux — cold silver-blue. 10.3:1 vs RaddBluRayPill. */
val RaddBluRayLabel      = Color(0xFFC7D6E8)
val RaddBluRayPill       = Color(0xFF1A2733)
/** WEB-DL / WEBRip — steel. 7.7:1 vs RaddWebDlPill. */
val RaddWebDlLabel       = Color(0xFF9FB4C9)
val RaddWebDlPill        = Color(0xFF16202A)
/** CAM / SCR / TS / HDTS — DISCOURAGED. Red-family but muted: the app never
 *  celebrates low prints, it warns. 7.9:1 vs RaddCamPill. Pair with a warning
 *  icon — redundancy for color-blind users. */
val RaddCamLabel         = Color(0xFFF2A0A8)
val RaddCamPill          = Color(0xFF3A161A)

// ── 9. ENTITLEMENT chips ────────────────────────────────────────────────────
/** free — "direct play" — reuses HealthOk paint + pill (9.0:1). */
/** ads — intermediate/redirect links with ad layers. 8.6:1 vs AdPill (#33220D). */
val RaddAdsLabel         = Color(0xFFFFB45E)
val RaddAdsPill          = Color(0xFF33220D)
/** paid/premium host keys — Bullion on HdrPill: 10.8:1. */
/** ephemeral-link warning — HealthExpired paints; dashed outline variant. */

// ── 10. SCRIMS — the only sanctioned way to put text over artwork ───────────
// WCAG measures text over images at the WORST case pixel (pure white art).
// 70% black scrim over white art composites to #4C4C4C: white text = 8.6:1
// (AAA); for muted text on art use RaddScrimMuted (#C9D6D2, 5.7:1) — the
// screen-muted RaddMistOnInk only reaches 4.3:1 there and FAILS on art.
// 60% scrim is the floor, and only for LARGE text (≥20sp bold / ≥24sp).
// Body-size text never floats on art.

/** Solid 70% black — badge chips on posters. */
val RaddArtScrim         = Color(0xB3000000)
/** Muted metadata text over artwork scrims. 5.7:1 vs scrim70-on-white-art. */
val RaddScrimMuted       = Color(0xFFC9D6D2)
/** 85% black — bottom of hero gradient under titles. White on top ≥ 15:1. */
val RaddHeroScrim        = Color(0xD9000000)
/** Full system scrim behind dialogs/bottom sheets. */
val RaddScrim            = Color(0xFF000000)

// ── 11. STATE layers & misc roles ───────────────────────────────────────────
/** Ripple/selection wash on ink (≈8% current). */
val RaddCurrentStateLayer = Color(0x142BC79A)
/** Poster placeholder shimmer endpoints (use with a sweep gradient). */
val RaddPlaceholderLow   = Color(0xFF10191C)
val RaddPlaceholderHigh  = Color(0xFF1C2A2E)
/** Adult-blocked / locked empty state — deliberately DESATURATED: blocked
 *  content is greyed to outline tiers, never tinted with the action color. */
val RaddBlockedStroke    = RaddInk600   // 3:1 graphics vs 950 — same brand paint, one source
/** Success toast/check (connection OK) — same family as HealthOk. */
val RaddSuccess          = brandColor(BuildConfig.BRAND_COLORS_DARK_SUCCESS)
/** Danger — errors, destructive confirm. 7.2:1 vs 950 (AAA text). */
val RaddDanger           = brandColor(BuildConfig.BRAND_COLORS_DARK_DANGER)
/** Warning glyph/text where Gold is too "premium"-coded. 9.9:1 vs 950. */
val RaddWarning          = brandColor(BuildConfig.BRAND_COLORS_DARK_WARNING)

// ── 12. DAYBREAK — light scheme neutrals + primaries ────────────────────────
// Light mode is "the same water at noon": warm-cool paper, same jade current
// deepened to 700 so it survives daylight. All pairs verified AA; muted tiers
// verified ≥4.5:1 against their container tier.

/** light background — cool paper. */
val RaddPaperDay         = brandColor(BuildConfig.BRAND_COLORS_LIGHT_BACKGROUND)
/** light surface. */
val RaddPaperSurface     = brandColor(BuildConfig.BRAND_COLORS_LIGHT_SURFACE)
/** light surfaceBright / surfaceContainerLowest — the whitest tier (dialogs, cards
 *  lifted off paper). Same brand paint as a light onPrimary label, hence one key pair. */
val RaddLightSurfaceBright = brandColor(BuildConfig.BRAND_COLORS_LIGHT_SURFACE_BRIGHT)
/** light onPrimary label paint (white on current700 = 6.2:1). */
val RaddLightOnPrimary     = brandColor(BuildConfig.BRAND_COLORS_LIGHT_ON_PRIMARY)
val RaddPaperContainerLow = brandColor(BuildConfig.BRAND_COLORS_LIGHT_SURFACE_CONTAINER_LOW)
val RaddPaperContainer    = brandColor(BuildConfig.BRAND_COLORS_LIGHT_SURFACE_CONTAINER)
val RaddPaperContainerHigh = brandColor(BuildConfig.BRAND_COLORS_LIGHT_SURFACE_CONTAINER_HIGH)
val RaddPaperContainerHighest = brandColor(BuildConfig.BRAND_COLORS_LIGHT_SURFACE_CONTAINER_HIGHEST)
/** light onSurface — deep undertow ink. 16.1:1 vs PaperDay. */
val RaddInkOnPaper       = brandColor(BuildConfig.BRAND_COLORS_LIGHT_TEXT)
/** light onSurfaceVariant. 5.4:1 vs ContainerHigh (AA). */
val RaddMistOnPaper      = brandColor(BuildConfig.BRAND_COLORS_LIGHT_TEXT_SECONDARY)
/** light muted. 5.1:1 vs ContainerHigh, 6.0:1 vs bg (AA body). */
val RaddWhisperOnPaper   = brandColor(BuildConfig.BRAND_COLORS_LIGHT_TEXT_MUTED)
val RaddOutlineOnPaper   = brandColor(BuildConfig.BRAND_COLORS_LIGHT_OUTLINE)
val RaddOutlineVarOnPaper = brandColor(BuildConfig.BRAND_COLORS_LIGHT_OUTLINE_VARIANT)
/** light primaryContainer + on-color: 11.1:1. */
val RaddCurrentContainerLight = brandColor(BuildConfig.BRAND_COLORS_LIGHT_PRIMARY_CONTAINER)
val RaddOnCurrentContainerLight = brandColor(BuildConfig.BRAND_COLORS_LIGHT_ON_PRIMARY_CONTAINER)
/** light error + container: onContainer 13.3:1, error-on-bg 6.1:1. */
val RaddDangerLight        = brandColor(BuildConfig.BRAND_COLORS_LIGHT_DANGER)
val RaddDangerContainerLight = brandColor(BuildConfig.BRAND_COLORS_LIGHT_DANGER_CONTAINER)
val RaddOnDangerContainerLight = brandColor(BuildConfig.BRAND_COLORS_LIGHT_ON_DANGER_CONTAINER)
/** light scheme badges keep the DARK pill treatment (badges are artwork-native
 *  and always read as raised ink chips even in light mode — documented in
 *  DESIGN_SYSTEM.md §5), so no light variants are defined for print pills. */

// ── 13. PLAYER CHROME — what the HUD draws over live video ──────────────────
// These are the only paints in the app that sit on a moving, unknown-bright
// frame instead of on the ink ramp, so their alpha is the design, not an
// afterthought: every tier here exists so a white glyph clears 4.5:1 whatever
// the film is showing behind it. They live in this file because ui/theme/
// Color.kt is the one owner of raw paint — a screen names the role, never the
// bytes. Migration note: the solid plates below are blue-grey while the brand
// neutrals are teal-shifted (§1), and the accent has no brand role at all. The
// hues were moved here unchanged rather than re-decided blind, because this
// box has no device; folding them into colors.dark.* is an owner call, and the
// old-to-brand-role table is recorded in this session's App/AGENTS.md log.

/** Full-bleed backdrop for audio-only playback, where there is no frame. */
val RaddPlayerStage        = Color(0xFF0B0E14)
/** Bottom-sheet container in the player (tracks, quality, subtitles, sleep). */
val RaddPlayerSheet        = Color(0xFF12161F)
/** Dialog container — one lift above a sheet, same scrim under both. */
val RaddPlayerDialog       = Color(0xFF151A23)

/** 53% black — the top/bottom HUD bars and any idle chip riding them. */
val RaddHudBar             = Color(0x88000000)
/** 40% black — round transport controls and edge pills, over motion. */
val RaddHudChip            = Color(0x66000000)
/** 60% black — a card that pauses the frame to be read: gesture, play-again. */
val RaddHudCard            = Color(0x99000000)
/** 80% black — the scrub readout, the shortest-lived but busiest text. */
val RaddHudToast           = Color(0xCC000000)
/** 20% white — the unplayed remainder of the 2 dp hairline position track. */
val RaddHudTrack           = Color(0x33FFFFFF)
/** 13% white — an unselected pill inside a HUD sheet (the speed rail). */
val RaddHudPillIdle        = Color(0x22FFFFFF)

/** 80% black — the caption plate both subtitle paths put behind text. Written twice
 *  on purpose: the Compose overlay takes the literal form, CaptionStyleCompat takes an
 *  ARGB int, and composing one from the other would change which overload the paint
 *  resolves through on a screen nobody can look at from this box. */
val RaddCaptionPlate       = Color(0xB3000000)
val RaddCaptionPlateArgb   = 0xB3000000.toInt()

/** The player's own accent: the selected rung, live speed, buffering, cinema.
 *  It paints states that CARRY meaning, so DESIGN_SYSTEM.md §9 forbids replacing
 *  it with an artwork-driven accent. No colors.dark.* role matches this orange;
 *  it is app-local until the brand file says otherwise. */
val AccentOrange           = Color(0xFFFF8552)
/** AccentOrange at 80% — the boost badge, which must read over any frame. */
val AccentOrangeToast      = Color(0xCCFF8552)
/** 80% blue-grey — the narration banner that reports a source change. */
val RaddNarrationPlate     = Color(0xCC1F2937)
/** The banner's "that worked" check. Not RaddSuccess: this green is the
 *  player's own, and changing it would restate the meaning of the banner. */
val RaddNarrationCheck     = Color(0xFF8FD14F)
/** 90% neutral grey — the player snackbar, deliberately colourless: whatever
 *  it reports may itself have been an error, so it must not shout. */
val RaddPlayerSnackbarPlate = Color(0xE6323232)

/** Keep-chip states at 40% so the frame shows through. The hues are the
 *  player's, not the catalog's badge greens/reds — a chip floating over video
 *  is measured against video, not against Ink950. */
val RaddKeepStored         = Color(0x662E7D32)
val RaddKeepBlocked        = Color(0x668B3A3A)
val RaddKeepKeeping        = Color(0x661565C0)

// ═════════════════════════════════════════════════════════════════════════════
//  LEGACY ALIASES — do not use in new code.
//  These keep files outside ui/theme compiling while screens migrate to
//  MaterialTheme.colorScheme roles. When a screen still imports one of these,
//  it is pinned to the DARK scheme; light mode needs colorScheme roles instead
//  (tracked in docs/HANDOFF_apptime.md).
// ═════════════════════════════════════════════════════════════════════════════
val BackgroundDark      = RaddInk950
val SurfaceDark         = RaddInk850
val SurfaceVariantDark  = RaddInk800
val OnBackground        = RaddPaperOnInk
val OnSurface           = RaddPaperOnInk
val OnSurfaceMuted      = RaddWhisperOnInk
/** ⚠ Buttons that set containerColor = AccentPrimary must set their label to
 *  RaddDeepCurrentInk (7.4:1). White text on this paint is 2.2:1 — see
 *  docs/HANDOFF_apptime.md §"button labels". */
val AccentPrimary       = RaddCurrent500
val AccentSecondary     = RaddCoral400
val AccentGold          = RaddSignalGold
val AccentGreen         = RaddSuccess
val AccentRed           = RaddDanger
