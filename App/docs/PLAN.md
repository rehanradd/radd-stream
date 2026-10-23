# RADD Stream App — Current Scope and Roadmap

## Vision Statement

> **RADD Stream** is an Android catalog client for a `radd-stream` server. The
> current milestone is limited to server setup, metadata browsing, and search.

⚠️ **Reality (verified against `App/app/src` 2026-10-22):** the "limited to …
search" sentence above is the original Phase 1 scope and no longer matches the
source. `App/app/src/main/kotlin/com/raddstream/app/` also contains `DetailScreen`,
`PlayerScreen`, `PlaybackService`, `MyListScreen` + Room favorites, and
`SettingsScreen`, all wired into `NavGraph.kt`, and the app calls
`/api/v1/posts/{id}` and `/api/v1/stream` as well as `/api/v1/posts` and
`/api/v1/stats`. Treat the "Deferred roadmap" and the Phase 2/3 sections below as
historical planning, and see
[`../AGENTS.md`](../AGENTS.md) §5–§6 for the verified current state.

---

## Core Design Principles

1. **So simple a 3-year-old can use it** — one tap to browse, one tap to play.
2. **Zero friction** — no sign-up, no account wall, no paywall ever.
3. **Speed first** — content loads in under 1 second on a fast connection.
4. **User owns everything** — points to your own server, your own data.
5. **Clean & beautiful** — dark, cinematic UI. Nothing cluttered.

---

## Feature Milestones

---

### ✅ Phase 0 — Foundation (complete)

- [x] Android project, Kotlin/Compose, navigation, and theme.
- [x] Retrofit API models for the metadata and statistics responses.
- [x] GitHub Actions test, lint, and debug APK workflow.

### 🚧 Phase 1 — Metadata Client MVP (current)

#### 1.1 Onboarding / Server Setup Screen
- [x] First-launch screen for the server base URL.
- [x] Test the connection with `/api/v1/stats`.
- [x] Save the URL to DataStore only after a successful response.

#### 1.2 Home Screen (Catalog Browser)
- [x] Load a paginated catalog from `/api/v1/posts`.
- [ ] Filter by movie, series, and anime. — **not achievable as specified.**
  `viewer.py` filters `content_type` by exact equality and the backend never
  stores `'anime'`, so `?type=anime` returns zero rows. Only `movie`, `series`,
  `complete_season`, and `ongoing_season` return results today. The chip ships in
  `HomeScreen.kt:48` but is broken; anime needs a new backend `animated` filter.
- [x] Show poster, title, year, type, and rating with loading/error/empty states.
- [x] Manual refresh and search navigation.

#### 1.3 Search Screen
- [x] Search titles with a 300 ms debounce.
- [ ] Filter results by movie, series, and anime. — same defect as 1.2; see the
  `?type=anime` note in [`../AGENTS.md`](../AGENTS.md) §5.
- [x] Show loading, error, and no-match states.

### Deferred roadmap — historical plan, partially superseded

> ⚠️ **Reality (verified against `App/app/src` 2026-10-22):** the Detail Screen
> and Player Screen described below are **no longer deferred** — `DetailScreen.kt`,
> `DetailViewModel.kt`, `PlayerScreen.kt`, and `player/PlaybackService.kt` exist
> and `NavGraph.kt:139-165` routes to both. They are unverified on a device and
> blocked by the release-model mismatch noted under Detail Screen. Everything else
> in this heading's subsections remains unbuilt.

#### Detail Screen
- Large poster / backdrop hero image
- Title, type badge (`Movie` / `Series` / `Complete Season` / `Ongoing Season` —
  these are the only `content_type` values the backend emits; there is no `Anime`
  type), year
- Synopsis / description text
- **Releases section**: list of available releases (quality: 4K / 1080p / 720p / HDRip)
- Per release: list of sources with server name badge
- **▶ PLAY** button (big, obvious, centered) — picks best quality source automatically
- **Choose Source** expandable section for manual source selection
- For series: Season/Episode selector grid

> ⚠️ **Reality (verified against viewer.py 2026-10-22):** `/api/v1/posts/{id}`
> returns releases in plain `id ASC` order with **no** season/episode grouping and
> **no** quality sorting (viewer.py:1942), and the release JSON carries `season`,
> `episode`, and `release_title` — not the `season_number` / `episode_number` /
> `episode_title` keys `Models.kt` maps. The implemented `DetailScreen` season
> filter therefore cannot group anything. The tier ordering the code does perform
> applies only to `sources` inside a release (viewer.py:1946-1961).

#### Player Screen
- Full-screen ExoPlayer / Media3 player
- **Controls** (auto-hide after 3s):
  - Play / Pause
  - Seek bar with time labels
  - +10s / -10s skip buttons
  - Playback speed selector (0.5× / 1× / 1.25× / 1.5× / 2×)
  - Quality selector (switch source mid-play)
  - Subtitles / CC toggle
  - Lock screen button (disables touch except unlock)
  - Picture-in-Picture (PiP) button
  - Fullscreen toggle
- **Gesture controls**:
  - Swipe left/right → seek ±10s
  - Swipe up/down on left half → brightness
  - Swipe up/down on right half → volume
  - Double-tap left → -10s, double-tap right → +10s
- Auto-next episode (series) with 10s countdown dismiss
- Remember position (resume from last point on reopen)
- Background playback with notification controls + lock-screen controls

> Of these, only background playback is implemented today — `Media3`
> `MediaSessionService` lives in `player/PlaybackService.kt`. Auto-next episode,
> remember-position, subtitles/CC, and mid-play quality switching are not present
> in `PlayerScreen.kt`.

---

### Phase 2 — Quality of Life
> *Makes the app feel polished and personal.*

⚠️ **Reality (verified against `App/app/src` 2026-10-22):** §2.1 (Room favorites +
My List tab) and §2.4 (Settings screen with server config and live diagnostics)
are already implemented and navigable. §2.2, §2.3, and §2.5 are not.

#### 2.1 Watchlist / Favorites — ✅ implemented
- ❤️ Heart button on Detail Screen → saves to local Room DB
- **My List** tab on Home Screen
- Works fully offline (local data)

#### 2.2 Continue Watching — ❌ not implemented
- Tracks last-played position per title (Room DB)
- **Continue Watching** row on Home Screen
- Tapping → resumes from saved timestamp
- Auto-clears entries watched to >90%

#### 2.3 Downloads (Offline Playback) — ❌ not implemented
- Download button on Detail Screen for individual releases
- Uses `DownloadManager` API for background downloading
- Downloads stored in app-private storage
- **Downloads** tab in bottom nav
- Offline playback from local file via ExoPlayer

#### 2.4 Settings Screen — ✅ implemented
- Server URL / connection settings (edit/reset)
- Default video quality preference (Auto / 4K / 1080p / 720p) — not present
- Autoplay next episode toggle — not present
- Continue Watching toggle — not present
- Clear cache button — not present
- Clear watch history button — not present
- App version / about — not present

#### 2.5 Deep Links — ⚠️ half-wired, effectively broken
- `radd://stream/{source_id}` → opens Player directly
- `radd://title/{post_id}` → opens Detail Screen
- Share button on Detail Screen generates shareable deep link

> The manifest does register an intent filter for `android:scheme="radd"`
> (`App/app/src/main/AndroidManifest.xml:43-48`), but `NavGraph.kt` declares **no
> `navDeepLink` entries**, so a `radd://` cold start lands on the normal start
> destination and goes nowhere. Do not advertise deep links as working until the
> nav graph handles them. There is also no share button: `DetailScreen.kt` contains
> no share action at all.

---

### 🌟 Phase 3 — Power Features
> *For advanced users and heavy usage.*

#### 3.1 External Player Support — ✅ implemented
- "Open in external player" option on Detail Screen (`DetailScreen.kt:529-539`,
  an `ACTION_VIEW` chooser)
- Sends resolved stream URL via Intent to: VLC, MPV, MX Player, Nova Player
- Falls back gracefully if no external player installed

#### 3.2 Cast / DLNA Support — ❌ not implemented
- Google Cast (Chromecast) integration via Media3 Cast extension
- DLNA renderer discovery (cast to smart TVs without Chromecast)

#### 3.3 Multi-Server Support
- Add / switch between multiple radd-stream server profiles
- Each profile: name, URL, last-connected status. (A `token` field would be
  pointless today: `viewer.py` implements no authentication — no API key, bearer
  token, or session — and answers with `Access-Control-Allow-Origin: *`. Add real
  auth to the backend first. ⚠️ Reality verified against viewer.py 2026-10-22)
- Quick-switch from Settings or notification shade

#### 3.4 Admin Panel (Power Users)
- Trigger a sync on the server — **`/api/v1/sync` DOES NOT EXIST.** It is a
  proposal only; `viewer.py`'s `do_GET()` has no such route (nor any `do_POST`
  handler at all), so nothing can be triggered over HTTP today. Sync runs from the
  CLI (`fast_fetch.py sync`). Do not build client code against this endpoint.
  ⚠️ Reality (verified against viewer.py 2026-10-22)
- View database stats (`/api/v1/stats`) — exists, but note it counts adult-flagged
  rows that `/api/v1/posts` hides.
- View `/api/v1/rules` (active unwrapper patterns) — exists.
- Basic log viewer — no such endpoint exists.
- ⚠️ There is no authentication anywhere in `viewer.py`, so an "admin panel" over
  this API would be public to anyone who can reach the port. Auth must be added
  before anything administrative is exposed.

> Also note `/api/heal?id=…` **is** routed but is broken: the handler builds its
> payload and never writes a response to the socket (viewer.py:2100-2108), so
> HTTP/1.1 clients hang until timeout. Do not wire a "heal" button to it.

#### 3.5 Android TV Support
- Leanback UI variant for TV remote navigation
- D-pad focus management on all screens
- TV-optimized player controls

---

## Screen Map

```
Verified in NavGraph.kt (2026-10-22) — all four bottom-nav tabs plus detail and player:
Setup (first launch) → Home catalog ↔ Search
                     → My List (Room favorites)
                     → Settings
Home / Search / My List → Detail (tap card) → Player

Still genuinely not implemented:
Continue Watching, offline Downloads (DownloadManager), Cast/DLNA, Android TV.
External-player hand-off IS implemented — DetailScreen.kt:529-539 fires an
ACTION_VIEW chooser.
```

---

## API Consumption Map

| App Screen | Backend Endpoint |
|---|---|
| Server setup | `GET /api/v1/stats` |
| Catalog | `GET /api/v1/posts?page=1&limit=30` |
| Search/filter | `GET /api/v1/posts?q={query}&type={filter}&page=1&limit=50` |
| Detail | `GET /api/v1/posts/{id}` |
| Player source resolve | `GET /api/v1/stream?id={sourceId}&redirect=0` |

`/api/v1/rules` is defined in the backend but **not** called by the app.
`/api/v1/sync` is **not** a backend endpoint — see §3.4.

`type` accepts only `movie`, `series`, `complete_season`, `ongoing_season`;
`anime` returns zero rows.

---

## Phase Delivery Timeline

| Phase | Description | Est. Effort |
|---|---|---|
| Phase 0 | Scaffolding + CI | Complete |
| Phase 1 | Metadata MVP (server setup + browse + search) | In progress |
| Phase 2 | Details, playback, watchlist + settings | Deferred |
| Phase 3 | Cast + TV + Multi-server | 2–3 weeks |

---

## Success Criteria for MVP (Phase 1)

- [x] User can enter a server URL and test `/api/v1/stats`.
- [x] Home screen requests catalog metadata and supports type filtering — but see
  the §1.2 note: only Movie/Series actually return rows.
- [x] Search is debounced and supports type filtering — same Movie/Series caveat.
- [ ] Verify API-backed setup, browsing, and search on a reachable server/device.

The `131`-style totals that older revisions of these docs quoted in examples were
a 2026-10-13 milestone snapshot, not the current catalog size — read
`/api/v1/stats` on the target server for live counts.

Playback and streaming performance criteria belong to a later milestone.
