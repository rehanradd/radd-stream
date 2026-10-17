# 📐 Screen Design Spec — RADD Stream

> ASCII wireframes + UX notes for every screen. Reference these during implementation.

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
- **Filter chip active**: re-queries with `?type=movie|series|anime`

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
│  Sources                    │  ← section header
│  ┌────────────────────────┐ │
│  │ 🔵 1080p · VegaDrive   │ │  ← source row
│  │          ▶ Play  ↗     │ │
│  └────────────────────────┘ │
│  ┌────────────────────────┐ │
│  │ 🟡 720p · HubCloud     │ │
│  │          ▶ Play  ↗     │ │
│  └────────────────────────┘ │
│                             │
└─────────────────────────────┘
```

**UX Notes:**
- `▶ PLAY` button uses highest-quality available source automatically
- `▶ Play` on each source row plays that specific source
- `↗` icon → "Open in external player" (Intent to VLC/MPV/MX)
- Series: tapping episode chip navigates to that episode's sources
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
│  │   releases             │ │
│  └────────────────────────┘ │
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
