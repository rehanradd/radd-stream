# 🎨 RADD STREAM DESIGN SYSTEM — "Current & Undertow" v2.0

> **The identity in one line:** the interface is deep water at night —
> teal-shifted near-black ink ("Undertow") carrying one electric jade action
> color ("Current") — where artwork, not chrome, is the light of the room,
> and every link's health is legible at a glance.
>
> Owned by `app/src/main/kotlin/com/raddstream/app/ui/theme/` (Color.kt,
> Type.kt, Theme.kt, ArtworkAccent.kt, RaddMark.kt) and mirrored for XML in
> `res/values/colors.xml`. **Code is the source of truth; this document is the
> contract.** If they disagree, fix the code or this file in the same PR.

---

## 1. Philosophy — why this is not a Netflix clone

1. **Dark-first, but not black-for-black's-sake.** Netflix owns "black + red".
   We own "undertow ink + jade current". Neutrals carry a teal hue (≈195°) so
   large dark fields feel aquatic, not dead. Elevation is expressed with M3
   tone-based `surfaceContainer` tiers, not drop shadows — depth like water
   getting brighter as it rises.
2. **One action color, zero ambiguity.** Jade `current500` answers exactly one
   question: *"what do I press?"* It is never decorative. Favorites are coral,
   quality is gold, downloads are indigo, failure is red — the palette is a
   **color language**, because this app's real subject is *source links and
   their health*, which generic streaming shells never have to say.
3. **Bright primary breaks the usual rule on purpose.** `current500` is high
   luminance, so **text on it is dark ink, never white** (white-on-current is
   2.2:1 — a fail). Buttons ship `primary` fill + `onPrimary` ink label. This
   inverts the default Material button look and is a signature, not a bug.
4. **Artwork is the hero.** UI maximum luminance stays below poster luminance;
   the chrome never out-shines the grid. Personalization comes from the
   *content* (artwork-driven accent, §9), not from wallpaper — which is also
   why dynamic color is opt-in (§10).
5. **Awards are won by restraint.** Three hues (jade / coral / gold) plus a
   semantic red-amber scale, disciplined radii ("river stone"), and one motion
   curve family. Anything that could be removed, was.

---

## 2. Color roles (dark scheme = flagship)

Kotlin val ↔ M3 role ↔ use. Ratios verified by WCAG 2.x relative-luminance
math (see Color.kt inline annotations for the full audit table).

| M3 role | Token | Hex | Pairing & ratio |
|---|---|---|---|
| background | `RaddInk950` | `#06090B` | app canvas |
| surface | `RaddInk900` | `#0E1518` | sheets, nav bar — onSurface 16.1:1 |
| surfaceContainerLowest | `RaddInkVoid` | `#040708` | floor under raised cards |
| surfaceContainer | `RaddInk850` | `#141D20` | **default card fill** — onSurface 14.4:1 |
| surfaceContainerHigh | `RaddInk800` | `#1E282B` | chips, text fields — muted text 6.4:1 |
| surfaceContainerHighest | `RaddInk750` | `#283336` | dialogs |
| onSurface | `RaddPaperOnInk` | `#E4EDEA` | primary text — 16.7:1 vs bg (AAA) |
| onSurfaceVariant | `RaddMistOnInk` | `#A5BDB8` | secondary text/icons — 8.6:1 vs 850 |
| muted metadata | `RaddWhisperOnInk` | `#93AEA9` | year/source — 6.4–7.2:1 (AA) |
| outline / outlineVariant | `RaddInk600` / `700` | `#6F8783` / `#3A4B49` | borders, dividers |
| **primary** | `RaddCurrent500` | `#2BC79A` | action — 9.3:1 vs bg (AAA) |
| **onPrimary** | `RaddDeepCurrentInk` | `#00281D` | **ink label on jade fill — 7.4:1** |
| primaryContainer | `RaddCurrentContainerDark` | `#0D2C24` | on-color `#89E9C3` 10.3:1 |
| secondary | `RaddCoral400` | `#FF7A6B` | favorites — 7.8:1 vs bg |
| tertiary | `RaddTideIndigo` | `#9AA5FF` | download affordance — 8.8:1 |
| error | `RaddDanger` | `#FF6B6E` | 7.2:1 vs bg (AAA) |

**Light ("Daybreak")** mirrors the same water at noon: bg `#F5F8F7`, ink text
`#0A1F1A` (16.1:1), primary deepens to `#0A6E52` (5.8:1 on paper; white label
6.2:1), containers `#EFF3F2→#D3E2DE`. See Color.kt §12; screens must migrate
off hard-painted dark tokens before light mode is exposed (HANDOFF).

---

## 3. Semantic color language (this app only)

**Rule: color never travels alone. Every semantic state = color + icon +
text label.** (Color-blind users must get the same information.)

### 3.1 Link health (source rows, detail sheet)
| State | Label paint | Pill bg | Ratio | Icon |
|---|---|---|---|---|
| healthy | `#4FE3A3` | `#0D2E20` | 9.0:1 | bolt |
| slow | `#FFC85C` | `#33240A` | 9.8:1 | hourglass |
| expired | `#FF9A6B` | `#33200F` | 7.5:1 | clock-arrow |
| dead | `#FF6B70` | `#3A1417` | 5.9:1 | broken-link + strikethrough + 60% alpha |

Dead links are *kept visible* (zero-loss rule) — greyed, never hidden.

### 3.2 Action affordance
- **Stream/watch now** → jade (primary). Text `current500` on jade-tinted pill
  `#0D2C24` = 6.9:1, or filled `primary` button with ink label.
- **Download/keep offline** → tide blue `#8FB8FF` on `#16233B` = 7.8:1.
  Never jade: a download is not an instant action.

### 3.3 Print / quality badges (over artwork or in release rows)
| Badge family | Label | Pill | Ratio |
|---|---|---|---|
| 4K · HDR10 · Dolby Vision | `#FFD57F` | `#33240A` | 10.8:1 |
| BluRay / REMUX | `#C7D6E8` | `#1A2733` | 10.3:1 |
| WEB-DL / WEBRip | `#9FB4C9` | `#16202A` | 7.7:1 |
| CAM / SCR / TS (**discouraged**) | `#F2A0A8` | `#3A161A` | 7.9:1 + warning icon |

Premium-DV convention: print badges are **solid ink chips, small caps,
labelMedium**, top-left or bottom-left of artwork; HDR chips may add a 1dp
gold `outline` to distinguish "format" from "print". We do NOT ship a
rainbow "Dolby-style" gradient — the gold tier is the premium signal.

### 3.4 Entitlement
free → health-ok paints · ads → `#FFB45E` on `#33220D` (8.7:1) ·
paid/key-required → Bullion `#FFD57F` on `#33240A`.
**Ephemeral links** (resolver `is_temporary`): expired-paint chip with a
**dashed outline** — "this address rots; watch now or re-resolve later".

### 3.5 Adult-blocked & empty states
18+ content is filtered at every surface, so the *blocked state* is a design
state: a desaturated slate lock motif (`RaddBlockedStroke #6F8783` on ink,
5.2:1 graphics) + `RaddStreamMark` at `current500` **only when the mark
represents the app itself** (search empty, list empty); blocked/forbidden UIs
must never wear the action color — jade always means "pressable".

---

## 4. Typography

| Slot | Role | Style | Use |
|---|---|---|---|
| Hero title | `displayMedium` 34/B | Display face, −0.4sp track | DetailScreen scrim |
| Screen title | `headlineMedium` 20/SB | Display | TopBars |
| Section head | `headlineSmall` 18/M | Display | Rail headers |
| Card title | `titleSmall` 14/M | Text | Poster captions |
| Synopsis | `bodyLarge` 16/24 | Text, 0.3sp | Body |
| Metadata | `bodySmall`/`labelMedium` 12–12/16 | Whisper paint | year · site · lang |
| Buttons | `labelLarge` 14/M 0.1sp | — | min height 44dp |

- **Faces:** Display = Outfit, Text = Inter (both OFL, to be bundled —
  `res/font/` slots + HANDOFF). Until bundled both fall back to platform
  sans; the scale is metric-tested against Roboto so nothing reflows.
- **Small-phone law:** floor 11sp (badges only, one line max); body line
  heights ≥1.4×; positive tracking ≤14sp, negative only ≥26sp; hierarchy by
  **weight (400/500/600/700)** not size deltas.
- **Numerics:** `RaddNumeric` (13/M, `tnum`, 0 tracking) for sizes, bitrates,
  latency, page counts; `RaddStatNumeric` (20/SB) for the settings stats card.
  Tabular digits keep release rows column-aligned.

## 5. Badge & pill rules

Height 20dp (22dp for HDR family), radius = `shapes.extraSmall` (4dp) — badges
are *labels*, not buttons; nothing tappable may look like a badge. Padding
6h/1v. Uppercase text via `labelMedium` (0.4sp tracking — uppercase needs
extra air). On artwork, badge pills are always one of the §3 ink pills (never
translucent color-on-color) or sit on `RaddArtScrim` (§8). Max 2 badges per
poster corner, never all four corners.

## 6. Accessibility & contrast policy

- All text pairs ≥4.5:1 (AA) as audited above; primary text targets ≥7:1.
- Large text (≥24sp / ≥20sp bold) pairs must clear 3:1; UI components/graphics
  3:1 against adjacent surface.
- Never signal state by color alone (icons + labels everywhere, §3).
- Touch targets ≥48dp (Compose minimum) with 8dp separation; primary CTAs
  (Play) ≥52dp tall and inside the bottom 60% thumb zone on phones.
- 200% font-scale: rails reflow, hero title clamps to 2 lines, badges may
  ellipsize — no screen may lose the Play control off-screen.
- Reduce-motion: crossfade only (`RaddMotion.FadeWhenReduced`), no slides.

## 7. Spacing · shapes · elevation

Grid = 4dp base: `RaddSpacing.xs/sm/md/lg/xl/xxl` = 4/8/12/16/24/32. Page
gutter 16dp; poster grid gap 8dp; rail gap 24dp; content clears edge-to-edge
bars by `thumbBarClearance` 24dp.
Radii ("river stone"): 4 (badge) · 8 (small chips) · **12 (posters, inputs)** ·
16 (cards, sheets top) · 28 (dialogs, hero container). Circles are reserved
for the mark's dots and FABs — never for posters (posters are 2:3 stones).
Elevation: use container tiers (§2), shadows ≤8% alpha, never on posters.

## 8. Artwork rules

Posters **2:3** (`2:3` — `aspectRatio(2f/3f)`), radius 12dp, gap 8dp; grid:
2 cols small phone → 3 → 4 landscape. Backdrops **16:9** (hero, 55–65% of
viewport height), players 16:9 letterboxed on ink.
**Scrim law:** text never floats on raw art. Chips/badges: `RaddArtScrim`
(70% black — white text worst-case 8.6:1 over pure-white art; muted text on
art must use `RaddScrimMuted` `#C9D6D2` = 5.7:1 — the screen-muted token
`RaddMistOnInk` fails at 4.3:1 over art).
Hero gradient: transparent → `RaddHeroScrim` (85%) → solid `RaddInk950` band
under title; ≥60% scrim floor, and body-size text only inside the solid band.
**Placeholders:** shimmer between `RaddPlaceholderLow/High` on `Linearish`
easing 1200ms, radius 12, plus the mark at 24dp/15% alpha if load >2s. Failed
loads keep the frame + broken-film icon (`RaddInk600`) — never a blank.

## 9. Artwork-driven accent (hook)

`rememberArtworkAccent(bitmap)` (ArtworkAccent.kt) returns the poster's
dominant chroma lifted to ≥4.5:1 vs the target surface; achromatic art falls
back to `current500`. Use it for *mood only*: hero gradient tail, section
rule color, My List tile glow. **Never** for buttons, badges, health, or
anything whose color carries meaning. It is deliberately incompatible with
dynamic color — that asymmetry is decided in §10.

## 10. Dynamic color policy

**Brand-locked by default; Material You is an opt-in setting.** Reasons:
(1) our scheme roles carry a color language; wallpaper-derived primaries
silently break it. (2) the scrim/contrast math (§8) is tuned to Undertow
neutrals. (3) personalization is already delivered per-title via §9, which
beats per-wallpaper tinting for a media app. When enabled (Settings), dynamic
color may remap generic M3 roles only — every `Radd*` semantic paint and the
neutral ink tiers stay fixed, so badges/health/scrim keep working. The
launcher icon's `<monochrome>` layer lets the *system* theme the icon even
when the app refuses to be themed.

## 11. Motion spec (`RaddMotion`)

| Token | ms | Easing | Use |
|---|---|---|---|
| DurationQuick | 120 | Standard (0.2,0,0,1) | press states, icon morphs |
| DurationDefault | 250 | EmphasizedDecelerate (0.05,0.7,0.1,1) | chips, tab indicator, expand |
| DurationEmphasized | 400 | EmphasizedDecelerate | screen enter/exit, sheet |
| DurationSlow | 600 | Emphasized | hero share-element only |

Exit accelerates (0.3,0,0.8,0.15); entrance decelerates — content arrives
like a settling wave and leaves like a pulled current. No overshoot/bounce in
media grids (it reads cheap under posters); physics spring reserved for the
brand splash mark only. Staggered rail entrance: 40ms/card, cap 8 cards.
Shimmer is the only `Linearish` motion.

## 12. Do / Don't

✅ Do map UI to `MaterialTheme.colorScheme.<role>`; pull semantic paints from
`Radd*` tokens; give every status color an icon; use `RaddNumeric` for
numbers; test pairs against the table in Color.kt.
❌ Don't: white text on jade (2.2:1); jade outside actions; red as a brand
accent (that's the whole Netflix cliché); third-party or studio logos anywhere
(including badges — "4K HDR" not brand marks); text on raw artwork; gradients
on chrome (gradients exist only in the launcher background and hero scrim);
new fonts, radii, or "one-off" hex values that aren't in Color.kt.

## 13. Brand mark (in-app)

`RaddStreamMark(size, color)` — the Source Ripple (core dot = source, two
open rings = current, rider dot = the stream you're on; round caps, built on
a 100-unit grid, identical geometry to the launcher vector). `RaddBrandLockup`
= mark + "Radd**Stream**" two-tone wordmark for TopBars/empty states. The
wordmark is typeset ("Radd Stream", display face), never a bespoke logo image.
Minimum clear space = ½ rider-dot radius all round; never rotate, never
recolor semantics (§3.5), monochrome-on-ink at 100% alpha or 15% for watermarks.

## 14. Platform honesty (for anyone using this system)

The deployed backend is **plain HTTP** (see root `ORACLE_DEPLOYMENT.md`), so
remote posters/API over cleartext need a debug-only network security config
(requested in `App/docs/HANDOFF_apptime.md`); release builds must not relax
this — TLS on the host comes first. This affects imagery only: until then,
grids show placeholders (§8) over dead HTTP image hosts if the OS blocks.

---
*v2.0 — "Current & Undertow". Supersedes the v1 "Dark Cinematic" spec
(`#6C63FF` generic-purple era). Contrast figures computed 2026-10-22 with
WCAG 2.x relative luminance; recompute if a hex changes.*
