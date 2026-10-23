# HANDOFF — from the Brand/Theme agent ("Current & Undertow" v2.0) → all other agents

Date: 2026-10-22. My files: `ui/theme/**`, `res/**`, `design/**`. I touched
nothing else. Everything below is a request for files I do NOT own.

## 1. BUTTON LABELS — contrast fix, blocking for visual QA (screens agent)
`current500` is a bright primary: **white text on it measures 2.2:1 (fails
WCAG)**. Labels on jade-filled buttons must use `RaddDeepCurrentInk` (7.4:1).
- `SettingsScreen.kt` ~line 118–125: `ButtonDefaults.buttonColors(containerColor = AccentPrimary)` + `label = Text(…, color = OnBackground)` → change the label color to `RaddDeepCurrentInk` (import from ui.theme), or better, switch to `ButtonDefaults.buttonColors()` defaults which already map primary/onPrimary correctly in Theme.kt.
- `SetupScreen.kt` ~line 109: same pattern, same fix.
- Any NEW button: prefer `Button(onClick)` with no color overrides — Theme.kt maps `primary`/`onPrimary` properly.

## 2. FONT BUNDLING — binaries I cannot author (owner/CI agent)
Type direction decided in `Type.kt` (Display = **Outfit**, Text = **Inter**,
both SIL OFL). Files needed (variable TTFs preferred):
```
App/app/src/main/res/font/outfit_variable.ttf
App/app/src/main/res/font/inter_variable.ttf
```
Fetch in Codespaces/CI (no dependency, no gradle change — res/font needs none):
```
curl -L -o outfit.ttf https://github.com/google/fonts/raw/main/ofl/outfit/Outfit%5Bwght%5D.ttf
curl -L -o inter.ttf  https://github.com/google/fonts/raw/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf
```
Rename lowercase, no spaces/brackets (aapt requires valid font resource names;
variable fonts keep names like `outfit_variable.ttf` — but note resource file
names must match `[a-z0-9_]+`, so use exactly `outfit_variable.ttf`,
`inter_variable.ttf`). Once present, the one-line switch is mine/anyone's in
`Type.kt`: `RaddDisplayFamily = FontFamily(Font(R.font.outfit_variable))`,
`RaddTextFamily = FontFamily(Font(R.font.inter_variable))` (weight axis via
FontVariationSettings is optional polish). Until then both vals fall back to
platform sans and the build is unaffected.

## 3. LEGACY PNG LAUNCHER ICONS are stale (owner/CI agent)
`res/mipmap-{m,h,xh,xx,xxx}hdpi/ic_launcher*.png` still show the old purple
play triangle (pre-API-26 fallback; I can only author XML vectors). Regen from
the new `drawable/ic_launcher_foreground.xml` + `_background.xml` (any of:
Android Studio Image Asset, `rsvg-convert`, or screenshot the adaptive icon at
48/72/96/144/192). No gradle/manifest change needed.

## 4. LIGHT MODE MIGRATION (screens agent, not blocking)
Several screens hard-import dark-only legacy vals (`BackgroundDark`,
`SurfaceDark`, `AccentPrimary`, …) which I kept compiling as aliases. Any
screen still importing them is pinned to the dark scheme. Migrate to
`MaterialTheme.colorScheme.<role>` + `Radd*` semantic tokens when touched.
`RaddStreamTheme(darkTheme = true)` stays forced-dark until that migration is
done — do NOT flip it early or hard-painted dark UI will sit on light scheme.

## 5. SETTINGS — theme toggle (settings/viewmodel agent)
Theme.kt exposes `RaddStreamTheme(darkTheme=, dynamicColor=)`. Policy decided
in DESIGN_SYSTEM.md §10: brand-locked default; if a
"Material You (beta)" switch is added, it only sets `dynamicColor = true`
(API 31+ guarded inside Theme.kt already) and must NOT remap semantic paints.
Persisting it needs no new dependency (DataStore is already in the app).

## 6. HEADER / EMPTY STATES — new components available (screens agent)
`ui/theme/RaddMark.kt` exports `RaddStreamMark(size, color)` and
`RaddBrandLockup(markSize, onName, onStream)` for TopBars and empty states,
and `ui/theme/ArtworkAccent.kt` exports
`rememberArtworkAccent(bitmap, surface, fallback)` — usage rules (mood-only,
never buttons/badges) are documented in the file header and DESIGN_SYSTEM §9.
Coil hookup: `success.painter as? BitmapDrawable` → pass `.bitmap`.

## 7. MANIFEST — no changes required by me
Debug cleartext already exists (`src/debug/AndroidManifest.xml`,
`usesCleartextTraffic=true`) so remote HTTP posters/API load in debug builds.
Release must NOT relax cleartext: the Oracle host has no TLS
(ORACLE_DEPLOYMENT.md) — that is a backend deployment gap; until it is fixed,
release builds simply cannot browse the catalog over http. Do not "fix" this
with a main-manifest cleartext flag. Optional hardening later: replace the
debug blanket flag with a domain-scoped `res/xml/network_security_config.xml`
(I own res/** and can author it the moment a manifest owner agrees on the diff).

## 8. DOC DRIFT (AGENTS.md owner)
`App/AGENTS.md` §7 "Design System Quick Reference" still quotes v1
(`#0A0A0F`, `#6C63FF` purple). New truth: bg `#06090B`, primary `#2BC79A`
jade, secondary coral `#FF7A6B`; radius 12 for posters; see
`design/DESIGN_SYSTEM.md`. I am not allowed to edit AGENTS.md.

## 9. WHAT I COULD NOT VERIFY WITHOUT A BUILD (CI, eyes open)
- Compilation of `ui/theme/**` (Compose BOM 2024.06.00 assumed for
  `surfaceContainer*` scheme params + `CubicBezierEasing` — both exist there).
- Actual rendered icon masking (circle/squircle cuts) — geometry fits the 40dp
  safe radius by construction but has not been pixel-previewed.
- Typeface fallback reflow before fonts are bundled (metrics chosen Roboto-safe).
