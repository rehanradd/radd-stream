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
- [x] Filter by movie, series, and anime. — **shipped, and the "not achievable as specified"
  verdict is retired (re-measured 2026-10-29).** `viewer.py:2530` answers `type=anime` from
  `(p.is_animated = 1 OR lower(p.industry) LIKE '%anime%')` — live `total: 5847` — and the same
  predicate is offered as the `industry` facet (`:2539`). The entry is at `HomeScreen.kt:237`
  (`JumpOffRow`, All / Movies / Series / Anime / Seasons); the old citation `HomeScreen.kt:48` and
  its "broken chip" claim described the 2026-10-22 tree. No new backend flag parameter was needed.
- [x] Show poster, title, year, type, and rating with loading/error/empty states.
- [x] Manual refresh and search navigation.

#### 1.3 Search Screen
- [x] Search titles with a 300 ms debounce.
- [x] Filter results by movie, series, and anime. — the defect this row pointed at is closed:
  `typeChips` in `SearchScreen.kt:73-79` is All / Movies / Series / **Anime** / Seasons, and the
  server answers `type=anime` (`viewer.py:2530`, live `total: 5847`). Search also sends the
  server-side `industry` / `genre` / `quality` / `sort` facets, which this checklist predates.
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
- Title, type badge (`Movie` / `Series` / `Anime` / `Complete Season` / `Ongoing Season`) — one
  owner, `WorkTypeLabel.of(contentType, isAnimated)`, painted at `DetailScreen.kt:484` and on the
  tile (`PosterCard.kt:63`). The parenthetical claim that used to sit here — "these are the only
  `content_type` values the backend emits; there is no `Anime` type" — was true of `content_type`
  and misleading about the badge: anime is a **flag** (`is_animated`), not a `content_type`, and a
  flagged series is labelled Anime and groups into its own rail (`typeGroupKey`).
- Year, synopsis / description text
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

> **Reality (re-verified against `App/app/src` 2026-10-29):** the note that used to sit here —
> "only background playback is implemented today … Auto-next episode, remember-position,
> subtitles/CC, and mid-play quality switching are not present in `PlayerScreen.kt`" — was a
> 2026-10-22 reading and is false on four counts. All four shipped:
> - **Auto-next episode** — `PlaybackService.kt:516-534` `handleEnded()` asks
>   `EpisodeProgression.computeNext(...)` and either seeks the next episode inside the same file or
>   hands a next-bundle request up; `PlayerEvent.PlayNextEpisode` reaches
>   `PlayerScreen.kt:2285` → `NavGraph.kt:255`. A successor's ladder is prefetched at 85 % of the
>   current episode (App Session 11). **The one wireframe detail that is genuinely missing is the
>   10 s countdown with a dismiss button** — hand-off is automatic, not cancellable; the only
>   countdown UI today is the sleep timer (`PlayerScreen.kt:979`, `:1906-1915`).
> - **Remember position** — `PlaybackService.kt:176` takes `request.resumePositionMs`/`startOverrideMs`
>   into `pendingResumeMs`, and `:473` seeks it on `STATE_READY`; the rows are written from
>   `PlayerViewModel`/`DetailViewModel` into the Room `watch_history` table.
> - **Subtitles / CC** — a track sheet (`PlayerScreen.kt:1962-1966`), a stored selection
>   (`PlayerViewModel.kt:1383`), an offset sync sheet, and the offset applied at the decoder:
>   `PlaybackService.kt:93-109` wraps `buildTextRenderers` with `OffsetSubtitleDecoderFactory`.
> - **Mid-play quality switching** — `armAutoQuality(...)` at `PlaybackService.kt:178` and the
>   one-decision-per-tick `evaluateAutoQuality()` at `:375`, plus the manual rung switch in
>   `PlayerViewModel`.
>
> Background playback was and remains implemented (`MediaSessionService`).

---

### Phase 2 — Quality of Life
> *Makes the app feel polished and personal.*

⚠️ **Reality (re-verified against `App/app/src` 2026-10-29):** all five sub-sections are
implemented and navigable — §2.1 favorites + My List, §2.2 Continue Watching, §2.3 Downloads,
§2.4 Settings, and §2.5 deep links (partially: two of the three work, see that row). What the
2026-10-22 note called "§2.2, §2.3, and §2.5 are not" is retired; the honest remaining gaps are
named inside each sub-section, not by a blanket ❌.

#### 2.1 Watchlist / Favorites — ✅ implemented
- ❤️ Heart button on Detail Screen → saves to local Room DB
- **My List** tab on Home Screen
- Works fully offline (local data)

#### 2.2 Continue Watching — ✅ implemented (this heading said "❌ not implemented"; retired 2026-10-29)
- Tracks last-played position per title (Room DB) — `data/local/WatchHistory.kt:20`
  `WatchHistoryEntity`, table `watch_history` created by real DDL in `AppDatabase.kt:111-122`
  (migration 4 → 5), primary key `(workRef, seasonNumber, episodeNumber)`.
- **Continue Watching** row on Home Screen — `HomeViewModel.kt:108/132 observeContinueWatching()`
  combines the local DAO with the server's synced-progress DAO through `WatchHistoryMerge` and
  publishes `ResumeTile`s; `viewmodel/ContinueWatchingTile.kt` owns the scope label and progress
  fraction a card paints (`ContinueWatchingTileTest` pins both).
- Tapping → resumes from saved timestamp — `PlayerViewModel.kt:465 startStreamHandle(...,
  startOverrideMs)` → `PlayerSessionStore.requestLoad` → `PlaybackService.kt:176` → `seekTo` on
  `STATE_READY` (`:473`).
- **Auto-clears entries watched to >90%** — not the shipped rule, and the shipped rule is the
  honest one: a row is *offered* while `WatchHistoryEntity.resumable` holds (`positionMs >= 1_000`
  and `< durationMs - 10_000`, `WatchHistory.kt:34-37`), so a finished scope drops out of the rail
  by an end-band guard rather than a percentage. The DAO's only deletion is `clear()` (`:95`), which
  nothing calls from Settings — see §2.4's last bullet.

#### 2.3 Downloads (Offline Playback) — ✅ implemented, on two deliberately different choices
(this heading said "❌ not implemented"; retired 2026-10-29)
- Download button on Detail Screen for individual releases — `DetailScreen.kt:246` keeps a print and
  `:251` keeps a ladder rung, both behind the storage-permission gate; a provider-page link is
  refused with `PAGE_NOT_A_FILE`, because a page is not a file (App Session 25).
- ~~Uses `DownloadManager` API~~ → **a custom foreground `Service`** is what shipped:
  `data/downloads/DownloadService.kt:55`, chosen at `:46-51` because the platform's
  `DownloadManager` has pause/resume-remove only and no pause/resume. Range-resume and the
  per-task progress card are ours.
- ~~Downloads stored in app-private storage~~ → **public and user-visible**:
  `Movies/RaddStream/` through MediaStore on Android 10+, the public directory below it
  (`DownloadService.kt:51`, `:284`). That is the opposite of the plan's bullet, and it is the
  decision — a kept file the viewer can see is a kept file they can move off the phone.
- **Downloads** tab in bottom nav → routed and reachable, but **not** a bottom-nav tab:
  `NavGraph.kt:203` registers `Screen.Downloads`, reached from Settings' "Offline" card
  (`ui/screens/DownloadsScreen.kt`, gated by the operator's `downloads` feature flag). The four
  tabs are Home / Search / My List / Settings (`NavGraph.kt:72-76`).
- Offline playback from local file via ExoPlayer — a kept copy wins before the network is touched:
  `PlaybackService.localCopyUrlFor` → `OfflineCacheEngine.playableUri`, served over
  `data/cache/LocalMediaProxy.kt:33` on `127.0.0.1` (a `file://` URI is not what ExoPlayer is
  handed), and `NavGraph.kt:212`/`:282-285` route a tap from the list through `Screen.PlayerLocal`.

#### 2.4 Settings Screen — ✅ implemented, six bullets re-scored against the screen (2026-10-29)
- Server URL / connection settings (edit/reset)
- Default video quality preference (Auto / 4K / 1080p / 720p) — **present**: the `ImageQuality`
  `ChipRow` in the "Playback & Display" card (`SettingsScreen.kt:352`, the rail around `:371`).
  Subtitle-language and audio-language rails sit beside it, which this plan never asked for.
- Autoplay next episode toggle — **not present**, and that is a real gap: auto-advance is
  unconditional (see the §Phase 2 player note), so a viewer cannot turn the hand-off off.
- Continue Watching toggle — **not present**: the Home rail always shows what the DAO returns.
- Clear cache button — **present but narrower than asked**: "Clear poster images"
  (`SettingsScreen.kt:467-470`, `viewModel::clearImageCache`), and its own copy says kept videos
  are untouched here. There is no cache clearing of kept media or of the HTTP/image disk cache.
- Clear watch history button — **not present**. `WatchHistoryDao.clear()` exists
  (`data/local/WatchHistory.kt:95-96`) and has no caller, so a viewer cannot empty their own
  Continue Watching list from Settings; no screen offers it.
- App version / about — **present**: the "About" card paints `Brand.versionName` /
  `Brand.versionCode` and the connection/TLS line (`SettingsScreen.kt:496+`).

#### 2.5 Deep Links — ⚠️ two of three work; the advertised Player link goes nowhere
- ~~`radd://stream/{source_id}` → opens Player directly~~ **NOT wired — the one real gap in this
  section.** `AndroidManifest.xml:59-65` registers the VIEW/DEFAULT/BROWSABLE filter and its comment
  on `:59` advertises exactly `<brand.deeplink.scheme>://stream/12345`, but `NavGraph.kt` declares
  `navDeepLink` for only two routes — `browse/{type}` (`:168`) and `detail/{postId}` (`:223`) — so
  there is no Player pattern to match, and `brand.properties:178-181` defines hosts for `browse` and
  `detail` only. A `…/stream/…` cold start therefore lands on the normal start destination. Do not
  advertise it until a `player/{handle}` `navDeepLink` exists — and note the argument is an **opaque
  stream handle**, never a URL (§5 of `../AGENTS.md`), so a shareable Player link has to mint or
  carry that handle, which is a design decision, not a one-line registration.
- ✅ `radd://detail/{postId}` → opens Detail Screen — `NavGraph.kt:223`. (`browse/{type}` works too,
  `:168`; neither was listed here.) The scheme is `${brandScheme}`, generated from
  `brand.properties` `deeplink.scheme` — `radd` today, not a literal.
- ✅ Share button on Detail Screen — `DetailScreen.kt:216` (`Icons.Default.Share`, `:219`) calls
  `shareTitle(...)` at `:1037-1048`. **But it shares words, not a link:** the text is
  `copy.share_template` from `brand.properties:167` — `Check out "{title}" in RADD Stream.` — with
  no URI in `EXTRA_TEXT`. So "generates shareable deep link" is still false, and it is false for the
  same reason as the row above: there is no receivable target to point at. A recipient gets a title
  they cannot open.

> Retired here (it described the 2026-10-22 tree): "the manifest registers the filter at
> `AndroidManifest.xml:43-48` but `NavGraph.kt` declares **no** `navDeepLink` entries … there is
> also no share button". `NavGraph.kt` now declares two, and `DetailScreen.kt` has a share action —
> the filter moved to `:59-65`.

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
  pointless today for the catalog routes: `viewer.py` accepts no API key, bearer
  token, or session on them, and `CORS_ALLOW_ORIGINS` is an empty allow-list rather
  than the wildcard this note used to claim. The server does hold credentials
  elsewhere — `RADD_ADMIN_TOKEN` on the loopback operator port, account sync keys —
  and none of them survives an HTTP trip. Add real auth to the backend first, then
  make a `token` field mean something. ⚠️ Reality verified against
  `viewer.py`/`redact.py` 2026-10-30.)
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
