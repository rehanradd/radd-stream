# RADD Stream App — Current Scope and Roadmap

## Vision Statement

> **RADD Stream** is an Android catalog client for a `radd-stream` server. The
> current milestone is limited to server setup, metadata browsing, and search.

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
- [x] Filter by movie, series, and anime.
- [x] Show poster, title, year, type, and rating with loading/error/empty states.
- [x] Manual refresh and search navigation.

#### 1.3 Search Screen
- [x] Search titles with a 300 ms debounce.
- [x] Filter results by movie, series, and anime.
- [x] Show loading, error, and no-match states.

### Deferred roadmap — not part of the current MVP

#### Detail Screen
- Large poster / backdrop hero image
- Title, type badge (Movie / Series / Anime), year
- Synopsis / description text
- **Releases section**: list of available releases (quality: 4K / 1080p / 720p / HDRip)
- Per release: list of sources with server name badge
- **▶ PLAY** button (big, obvious, centered) — picks best quality source automatically
- **Choose Source** expandable section for manual source selection
- For series: Season/Episode selector grid

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

---

### Phase 2 — Quality of Life
> *Makes the app feel polished and personal.*

#### 2.1 Watchlist / Favorites
- ❤️ Heart button on Detail Screen → saves to local Room DB
- **My List** tab on Home Screen
- Works fully offline (local data)

#### 2.2 Continue Watching
- Tracks last-played position per title (Room DB)
- **Continue Watching** row on Home Screen
- Tapping → resumes from saved timestamp
- Auto-clears entries watched to >90%

#### 2.3 Downloads (Offline Playback)
- Download button on Detail Screen for individual releases
- Uses `DownloadManager` API for background downloading
- Downloads stored in app-private storage
- **Downloads** tab in bottom nav
- Offline playback from local file via ExoPlayer

#### 2.4 Settings Screen
- Server URL / connection settings (edit/reset)
- Default video quality preference (Auto / 4K / 1080p / 720p)
- Autoplay next episode toggle
- Continue Watching toggle
- Clear cache button
- Clear watch history button
- App version / about

#### 2.5 Deep Links
- `radd://stream/{source_id}` → opens Player directly
- `radd://title/{post_id}` → opens Detail Screen
- Share button on Detail Screen generates shareable deep link

---

### 🌟 Phase 3 — Power Features
> *For advanced users and heavy usage.*

#### 3.1 External Player Support
- "Open in external player" option on Detail Screen
- Sends resolved stream URL via Intent to: VLC, MPV, MX Player, Nova Player
- Falls back gracefully if no external player installed

#### 3.2 Cast / DLNA Support
- Google Cast (Chromecast) integration via Media3 Cast extension
- DLNA renderer discovery (cast to smart TVs without Chromecast)

#### 3.3 Multi-Server Support
- Add / switch between multiple radd-stream server profiles
- Each profile: name, URL, token, last-connected status
- Quick-switch from Settings or notification shade

#### 3.4 Admin Panel (Power Users)
- Trigger a sync on the server (`/api/v1/sync` — to be added to backend)
- View database stats (`/api/v1/stats`)
- View `/api/v1/rules` (active unwrapper patterns)
- Basic log viewer

#### 3.5 Android TV Support
- Leanback UI variant for TV remote navigation
- D-pad focus management on all screens
- TV-optimized player controls

---

## Screen Map

```
Current navigation:
Setup (first launch) → Home catalog ↔ Search

Deferred, not wired into the current MVP:
Detail page, media playback, watchlist, and settings
```

---

## API Consumption Map

| App Screen | Backend Endpoint |
|---|---|
| Server setup | `GET /api/v1/stats` |
| Catalog | `GET /api/v1/posts?page=1&limit=30` |
| Search/filter | `GET /api/v1/posts?q={query}&type={filter}&page=1&limit=50` |

Detail, resolver, and playback endpoints are not used by the current app.

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
- [x] Home screen requests catalog metadata and supports type filtering.
- [x] Search is debounced and supports type filtering.
- [ ] Verify API-backed setup, browsing, and search on a reachable server/device.

Playback and streaming performance criteria belong to a later milestone.
