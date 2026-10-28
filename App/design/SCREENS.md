# 📐 Screen Design Spec — RADD Stream

> ASCII wireframes + UX notes for every screen. Reference these during implementation.

> ⚠️ **Reality (re-verified against `Fast_Fetch/viewer.py` and `App/app/src` 2026-10-29).**
> This file is a *design* spec, so most of it is aspirational by
> intent — but the following two claims in it are false:
> 1. ~~**`?type=anime` does not work.**~~ **Retired — it works, and the app ships the chip.**
>    `viewer.py:2530` answers `type=anime` from the flag the data really carries,
>    `(p.is_animated = 1 OR lower(p.industry) LIKE '%anime%')`, and `:2539` offers the same
>    predicate as an `industry` facet. Re-measured read-only 2026-10-29:
>    `GET /api/v1/posts?type=anime&limit=1` → `200 in 0.24 s`, `total: 5847`, row carries
>    `is_animated: 1`. The Anime entry is live at `HomeScreen.kt:237` (`JumpOffRow`) and
>    `SearchScreen.kt:73-79` (`typeChips`), and `Post.isAnimated` decodes the flag (INTEGER 0/1 via
>    `LenientBooleanAdapter`), so a tile is typed ANIME from the list row, on the hero, and on
>    My List. `../AGENTS.md` §5 and `PARITY_BACKEND_BLOCKED.md` §4-A carry the measured detail.
> 2. **Screens 4–7 are already built**, not future work. Detail, Player, My List,
>    and Settings
>    exist in `App/app/src/.../ui/screens/` and are routed in `NavGraph.kt`. The
>    wireframes below describe intended polish that the shipped screens do not all
>    reach. (The old note here claimed Detail's season filter "cannot group" because the
>    release JSON carries `season`/`episode`, not `season_number`/`episode_number` — that is
>    retired too: `ReleaseDetail` now maps the columns the ledger writes and derives the season
>    and episode numbers through `ReleaseLabelParsing`, so `SeasonChips` paints real groups.)
>
> What the transport still is: the Oracle host is plain HTTP with no TLS, and the four catalog
> reads a phone makes (`stats`, `posts`, `posts/{id}`, `stream`) answer anyone who can reach nginx
> — nothing behind them is private. What is **not** true any more (re-verified in
> [`../AGENTS.md`](../AGENTS.md) §5): the `api/v2/account*` routes require the sync bearer key
> (`viewer.py:381`, `:389`), every request lands in a token bucket that carries the IETF
> `RateLimit-*` headers (`viewer.py:2957`, `redact.py:1163`), CORS is an allow-list that is
> currently empty (`redact.py:1278`), and the server binds `127.0.0.1` by default
> (`viewer.py:3491`) behind nginx.

---

## Screen 1 — Splash / First Launch Setup

**Shown**: Only on first app launch (or after server reset)

```
┌─────────────────────────────┐
│                             │
│                             │
│                             │
│        🎬 RADD Stream       │  ← App logo + name (center)
│                             │
│   Connect to your server    │  ← subtitle (on_surface_muted)
│                             │
│  ┌───────────────────────┐  │
│  │ http://your-server... │  │  ← TextField (server URL)
│  └───────────────────────┘  │
│                             │
│  ┌───────────────────────┐  │
│  │   ✓ Test Connection   │  │  ← outlined button (shows spinner)
│  └───────────────────────┘  │
│        ● ✓ Connected        │  ← green dot + "Connected" on success
│                             │
│  ┌───────────────────────┐  │
│  │  ▶  Let's Watch       │  │  ← primary button (disabled until connected)
│  └───────────────────────┘  │
│                             │
└─────────────────────────────┘
```

**UX Notes:**
- URL field auto-fills `http://` prefix
- "Test Connection" calls `GET /api/v1/stats` — shows title count on success
- "Let's Watch" navigates to Home and never shows this screen again
- Keyboard auto-opens on this screen

---

## Screen 2 — Home

**Bottom nav tab**: 🏠 Home

```
┌─────────────────────────────┐
│ ░░░░░░░░░░░░░░░░░░░░░░░░░░░ │  ← Status bar (edge-to-edge)
│                             │
│  ┌─────────────────────┐    │
│  │                     │    │
│  │   [HERO POSTER]     │    │  ← 260dp tall hero banner
│  │                     │    │
│  │  ▓▓▓▓▓▓  MOVIE      │    │  ← title + type badge (bottom-left)
│  │  ░ ░ ● ░ ░           │    │  ← dot indicators (center-bottom)
│  └─────────────────────┘    │
│                             │
│  Continue Watching    →     │  ← section header + "See All"
│  ┌────┐ ┌────┐ ┌────┐      │
│  │    │ │    │ │    │      │  ← horizontal scroll row
│  │ 🎬 │ │ 📺 │ │ 🎬 │      │  ← poster cards (120×180dp)
│  │    │ │    │ │    │      │
│  └────┘ └────┘ └────┘      │
│                             │
│  🎬 Movies             →    │
│  ┌────┐ ┌────┐ ┌────┐      │
│  │    │ │    │ │    │      │
│  └────┘ └────┘ └────┘      │
│                             │
│  📺 Series             →    │
│  ┌────┐ ┌────┐ ┌────┐      │
│  └────┘ └────┘ └────┘      │
│                             │
│  🎌 Anime              →    │
│  ┌────┐ ┌────┐ ┌────┐      │
│  └────┘ └────┘ └────┘      │
│                             │
│ [🏠 Home][🔍][❤️][⚙️]        │  ← Bottom nav
└─────────────────────────────┘
```

**UX Notes:**
- Hero banner auto-scrolls every 5s, pauses on user swipe
- Each horizontal row is independently scrollable
- "→" / "See All" navigates to Search pre-filtered by that type
- Skeleton shimmer shown while API loads
- Pull-to-refresh reloads all rows
- ✅ The **🎌 Anime row is built** (this note used to say it "cannot be built today" — retired
  2026-10-29): `?type=anime` answers `total: 5847` live, `Post.isAnimated` decodes the flag off the
  list row, and `typeGroupKey` gives a flagged series its own rail instead of the Series one, with
  `WorkTypeLabel.of` the single owner of the word "Anime" on tile, hero badge and detail header.
- ✅ **The hero banner and the per-type horizontal rows are implemented** in `HomeScreen.kt`
  (this note used to claim the screen "renders a single filtered grid" — false):
  `HeroCarousel` is composed at `HomeScreen.kt:126` over the first rail that actually has rows,
  capped at `HERO_LIMIT = 6` (`:66`), with `HeroSkeleton` holding its footprint while the first
  rail lands (`ui/components/HeroCarousel.kt`); the rails themselves are `MediaRail` sections
  (`:142`, `HomeRailSection` at `:269`/`:306`). One honest remainder: the hero is **rail 1 reused**,
  not a server-curated "featured" projection — there is no `featured` field on the wire to build
  the wireframe's editorial banner from.

---

## Screen 3 — Search

**Bottom nav tab**: 🔍 Search

```
┌─────────────────────────────┐
│                             │
│  ┌──────────────────────┐   │
│  │ 🔍 Search titles...  │   │  ← Search bar (auto-focus)
│  └──────────────────────┘   │
│                             │
│  [All] [Movies] [Series]    │  ← filter chips (horizontal scroll)
│  [Anime]                    │
│                             │
│  ┌──────┐ ┌──────┐          │
│  │      │ │      │          │  ← 2-column poster grid
│  │      │ │      │          │
│  │ Title│ │ Title│          │
│  └──────┘ └──────┘          │
│  ┌──────┐ ┌──────┐          │
│  │      │ │      │          │
│  └──────┘ └──────┘          │
│                             │
│          ...                │
│                             │
│ [🏠 Home][🔍][❤️][⚙️]        │
└─────────────────────────────┘
```

**States:**
- **Empty input**: shows "Recent Searches" list
- **Typing**: shimmer grid → results grid (debounced 300ms)
- **No results**: centered illustration + "Nothing found for '{query}'"
- **Filter chip active**: re-queries with `?type=movie|series|complete_season|ongoing_season|anime`.
  The `[Anime]` chip drawn above **is** implemented and answered by the server — it is in
  `SearchScreen.kt:73-79` (`typeChips` = All / Movies / Series / **Anime** / Seasons) and
  `viewer.py:2530` resolves it from `is_animated`/`industry` (live `total: 5847`, 2026-10-29).
  Search additionally sends the server-side facets `industry`, `genre`, `quality` and `sort`
  (App Session 12), which this wireframe predates.

---

## Screen 4 — Detail Screen

**Navigated to by**: tapping any poster card

```
┌─────────────────────────────┐
│  ← Back                     │  ← top bar (transparent over hero)
│  ┌─────────────────────┐    │
│  │                     │    │
│  │   [BACKDROP IMAGE]  │    │  ← full-width 200dp backdrop
│  │                     │    │
│  │  [poster]  Title    │    │  ← poster floats left, title right
│  │  120×180   Year     │    │
│  │            🎬 Movie │    │
│  └─────────────────────┘    │
│                             │
│  ┌─────────────────────┐    │
│  │  ▶  PLAY            │    │  ← PRIMARY play button (accent_primary)
│  └─────────────────────┘    │
│                             │
│  Synopsis                   │  ← section header
│  The story follows...       │  ← 3 lines collapsed, tap to expand
│                             │
│  ─── For Series Only ────── │
│  Season 1 ▼                 │  ← season dropdown
│  Ep1  Ep2  Ep3  Ep4  Ep5   │  ← episode grid chips
│  ─────────────────────────  │
│                             │
│  Quality                    │  ← one row per BAND, from the server
│  ┌────────────────────────┐ │
│  │ ● Auto      Best for   │ │  ← default rung: the ladder's own
│  │   ▶  Keep   this place │ │     pointer, not "highest number"
│  ├────────────────────────┤ │
│  │ ○ 1080p                │ │  ← one option per band: no copies,
│  │   ▶  Keep              │ │     no servers, no addresses
│  ├────────────────────────┤ │
│  │ ○ 720p        1.4 GB   │ │  ← size, so a metered connection
│  │   ▶  Keep              │ │     can choose on price
│  ├────────────────────────┤ │
│  │ ○ Data saver  480p     │ │
│  │   ▶  Keep              │ │
│  └────────────────────────┘ │
│                             │
└─────────────────────────────┘
```

**UX Notes:**
- `▶ PLAY` starts the auto ladder: the best rung that actually plays here, and if a
  link dies mid-session the ladder steps down on its own. The viewer never has to
  pick a source to get that.
- The list is built from `QualityOption` (`App/.../player/QualityLadder.kt`), which the
  server produced by collapsing every copy of every print into one best-and-fastest
  option per band (`Fast_Fetch/tiers.py`). A row has a picture quality and a size —
  **it has no field for a site, a hoster, or an address, and must never gain one**;
  the earlier `1080p · VegaDrive` / `720p · HubCloud` rows in this file documented a
  server-name list that the API no longer emits and the plan forbids.
- `Keep` = "play while downloading, keep offline"; it hands the rung to
  `CacheCoordinator` and the row shows progress in place. `↗` external-player
  hand-off was removed with the embed surfaces (task #29) — there is one player.
- A band whose only copy cannot be presented inline says `Download only` out loud
  rather than failing invisibly.
- Series: tapping an episode chip re-scopes the same rung list to that episode.
- ❤️ fab button (bottom-right) toggles watchlist
- Share button in top app bar generates deep link

---

## Screen 5 — Player

**Full screen, no navigation bar**

```
┌─────────────────────────────────────────────┐
│  [      VIDEO CONTENT FILLS ENTIRE SCREEN   ]│
│                                             │
│  ← ⋮  Title (S01E03)       🔒  PiP  ⛶     │  ← top controls overlay (auto-hide)
│                                             │
│                                             │
│                  ⏸                          │  ← center play/pause (large)
│             ⟨10   ⏸   10⟩                  │
│                                             │
│                                             │
│  0:13:22 ────────●─────────── 1:47:00       │  ← seek bar + time
│                                             │
│  ▶1× CC ⋮                                  │  ← bottom controls row
└─────────────────────────────────────────────┘
```

**Gesture Zones:**
```
┌────────────┬──────────────┬────────────┐
│            │              │            │
│ Brightness │  Tap=pause   │  Volume    │
│ swipe ↕    │  DblTap=-10  │  swipe ↕  │
│            │  DblTap=+10  │            │
│            │              │            │
└────────────┴──────────────┴────────────┘
  Left 1/4      Center 1/2    Right 1/4
```

**Controls (auto-hide after 3s of inactivity):**
- **Top bar**: ← Back, title + episode, 🔒 lock, PiP, ⛶ fullscreen toggle
- **Center**: double-tap left = -10s ripple, double-tap right = +10s ripple
- **Seek bar**: draggable with thumbnail preview
- **Bottom**: ▶1× speed selector, CC subtitles, ⋮ more (quality, download)

---

## Screen 6 — My List

**Bottom nav tab**: ❤️

```
┌─────────────────────────────┐
│  My List                    │  ← page title
│                             │
│  ┌──────┐ ┌──────┐          │
│  │      │ │      │          │
│  │ ❤️   │ │ ❤️   │          │  ← poster cards with favorite heart
│  │ Title│ │ Title│          │
│  └──────┘ └──────┘          │
│                             │
│  (empty state)              │
│     ❤️                      │
│  Nothing saved yet.         │
│  Tap ❤️ on any title.       │
│                             │
│ [🏠 Home][🔍][❤️][⚙️]        │
└─────────────────────────────┘
```

---

## Screen 7 — Settings

**Bottom nav tab**: ⚙️

```
┌─────────────────────────────┐
│  Settings                   │
│                             │
│  SERVER                     │  ← section header (labelSmall muted)
│  ┌────────────────────────┐ │
│  │ 🌐 Server URL          │ │  ← tapping → edit URL dialog
│  │ http://192.168.1.5:80  │ │
│  └────────────────────────┘ │
│  ┌────────────────────────┐ │
│  │ ● Connected · 1,031    │ │  ← green dot + release count
│  │   releases             │ │    (⚠️ 1,031 was a 2026-10-13 snapshot — an
│  └────────────────────────┘ │     illustrative wireframe value only. The
│                             │     shipped SettingsScreen shows Titles /
│                             │     Releases / Streams from /api/v1/stats.)
│                             │
│  PLAYBACK                   │
│  ┌────────────────────────┐ │
│  │ Quality      Auto  ›   │ │
│  └────────────────────────┘ │
│  ┌────────────────────────┐ │
│  │ Autoplay Next  ●  ON   │ │  ← toggle switch
│  └────────────────────────┘ │
│  ┌────────────────────────┐ │
│  │ Remember Position  ON  │ │
│  └────────────────────────┘ │
│                             │
│  DATA                       │
│  ┌────────────────────────┐ │
│  │ 🗑 Clear Cache         │ │
│  └────────────────────────┘ │
│  ┌────────────────────────┐ │
│  │ 🗑 Clear Watch History │ │
│  └────────────────────────┘ │
│                             │
│  ABOUT                      │
│  ┌────────────────────────┐ │
│  │ RADD Stream v1.0.0     │ │
│  │ github.com/radddao     │ │
│  └────────────────────────┘ │
│                             │
│ [🏠 Home][🔍][❤️][⚙️]        │
└─────────────────────────────┘
```

---

## Navigation Flow Map

```
SplashSetupScreen
       │ (first launch only)
       ▼
HomeScreen ←──────────────────────────────┐
  │  (tap card)                           │
  ▼                                       │
DetailScreen                              │
  │  (tap ▶ Play)                         │
  ▼                                       │
PlayerScreen ─── (back) ──────────────────┘
  │  (PiP button)
  ▼
PiP Window (floating, continues playback)

SearchScreen ──(tap card)──► DetailScreen
MyListScreen ──(tap card)──► DetailScreen
SettingsScreen (no sub-navigation)
```

---

## 🎨 Visual & Design Notes — Brand Pass v2.0 ("Current & Undertow")

> Additive design layer only — navigation, routes, and wireframe structure
> above are owned by the screens agent and are unchanged. Token references:
> `design/DESIGN_SYSTEM.md`, code: `ui/theme/`.

### Screen 1 — Splash / First Launch Setup
- Cold-start window bg is `radd_ink_950` (themes.xml) so launch feels like one
  continuous ink field; `RaddStreamMark` 72dp fades in (300ms alpha only) then
  `RaddBrandLockup` settles under it.
- Status line paints by meaning: connected → `RaddSuccess` + bolt icon; error →
  `RaddDanger` (7.2:1). Never jade text for "server unreachable" prettiness.
- Primary CTA = filled `primary` button, **ink label** (`RaddDeepCurrentInk`),
  52dp min height, bottom thumb zone.

### Screen 2 — Home
- Background `colorScheme.background`; nav bar `surfaceContainerHigh`; rail
  headers `headlineSmall` in `onSurface`, "see all" in `RaddCurrent500` (9.3:1).
- Poster cards: 2:3, radius 12 (`shapes.medium`), gap 8. Year/site metadata in
  `RaddWhisperOnInk` (≥6.4:1). Rating chip = Signal Gold star + `RaddNumeric`.
- Type chips: unselected = `surfaceContainerHigh` fill + `onSurfaceVariant`;
  selected = `primaryContainer` + `onPrimaryContainer` (10.3:1), indicator
  animates 250ms `EmphasizedDecelerate`.
- Skeletons shimmer `RaddPlaceholderLow↔High`, 1200ms linear; error state uses
  lock/wave illustration slot with mark at 15% watermark alpha.

### Screen 3 — Search
- Search field: `surfaceContainerHigh`, radius 12, leading icon
  `onSurfaceVariant`, hint `RaddWhisperOnInk`. Clear button ≥48dp touch.
- Empty-with-query and no-results states get `RaddStreamMark` 48dp at
  `current500` + one `bodyMedium` line — the brand IS the empty state.

### Screen 4 — Detail
- Hero backdrop 16:9 → scrim stack per DESIGN_SYSTEM §8: transparent →
  `RaddHeroScrim` (85%) → solid ink band; title `displayMedium` white-family
  `RaddPaperOnInk` (≥15:1 worst case over art).
- Optional: hero band tail + section rules tinted with
  `rememberArtworkAccent(backdrop)` (mood-only, guaranteed ≥4.5:1).
- Favorite toggle = `RaddCoral400` heart (7.8:1); Play = jade filled 52dp with
  ink label; Download = tide-blue outlined chip (never jade).
- Release rows: print badges per §3.3 (solid ink chips, 4dp radius,
  labelMedium caps); link-health pills per §3.1 — color + icon + text.
  Dead sources: strikethrough title, 60% alpha, kept in list.
  Ephemeral (`is_temporary`): dashed-outline expired-paint chip.
- Season/episode chips: `surfaceContainerHigh` rest, `primaryContainer`
  selected; `RaddNumeric` for episode counts.

### Screen 5 — Player
- Pure black letterbox (below `RaddInkVoid` intentionally: content-out-of-
  water moment); controls on 60% vertical scrim, icons `RaddPaperOnInk`.
- Progress: track `RaddInk700`, buffered `RaddInk600`, played `RaddCurrent400`;
  Scrubber hit area 48dp tall though visually 4dp.
- Resolution/bitrate readouts (when surfaced) use `RaddNumeric` to stop jitter.

### Screen 6 — My List
- Same grid rules as Home; remove action = coral outline icon button (48dp),
  undo snackbar `inverseSurface` family.
- Empty list: `RaddStreamMark` 96dp + headline + one ghost CTA to Home. No
  text-only shrug.

### Screen 7 — Settings
- Stats card numbers: `RaddStatNumeric` + `tnum` so live server counts don't
  shimmy as they refresh.
- Connection status follows the semantic language: ok = `RaddSuccess`,
  error = `RaddDanger` (7.2:1) — both with icons, never color-alone dots.
- Future "Theme: Brand / Material You (beta)" switch wires
  `RaddStreamTheme(dynamicColor = …)` per DESIGN_SYSTEM §10; default Brand.
- Cleartext/HTTP warning banner (amber `RaddHealthSlow` on `RaddHealthSlowPill`,
  9.8:1) while pointed at an http:// host — honest, visible, one tap to details.

### Global
- Every screen: 16dp gutter, content clears edge-to-edge bars (+24dp bottom),
  all taps ≥48dp, all motion from `RaddMotion` tokens, no hex outside
  Color.kt.
