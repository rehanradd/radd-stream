# RADD Stream Android App

Native Kotlin and Jetpack Compose client for browsing a RADD Stream catalog and
playing its sources.

## Current milestone

⚠️ **Reality (verified against `App/app/src` and `Fast_Fetch/viewer.py`
2026-10-22):** this section used to describe a metadata-only client. The source
tree in `App/app/src/main/kotlin/com/raddstream/app/` actually contains a detail
screen, a Media3 player screen, `PlaybackService`, Room favorites, and a settings
screen, all wired into `NavGraph.kt`. The gap is device/CI verification, not
implementation. The bullet list below reflects the verified code.

The app currently supports:

- First-run server URL setup with a real `GET /api/v1/stats` connection check.
- Persisting the server URL locally after a successful connection.
- A poster grid populated by `GET /api/v1/posts`.
- Type filter chips for **All / Movies / Series / Anime / Seasons**. The Anime entry lives in
  `HomeScreen.kt:237` (`JumpOffRow`) and `SearchScreen.kt:73-79` (`typeChips`) and sends
  `?type=anime`, which the server answers from the animation flag the data actually carries —
  `(p.is_animated = 1 OR lower(p.industry) LIKE '%anime%')` (`Fast_Fetch/viewer.py:2530`).
  Re-measured read-only on 2026-10-29: `GET /api/v1/posts?type=anime&limit=1` → `200 in 0.24 s`,
  `total: 5847`, and the row carries `is_animated: 1`. The client decodes that flag onto `Post`
  (`Models.kt`, via `LenientBooleanAdapter`), so a tile inside an anime-filtered list is typed
  ANIME from the wire — see the API note below.
- Debounced title search with the same server-side filters.
- Loading, empty, retry, and connection-error states.
- A detail screen (`GET /api/v1/posts/{id}`) and Media3 playback through
  `GET /api/v1/stream?id=…&redirect=0`, plus local Room favorites. None of this
  has been run on a real device yet.

The backend is **not** the open book this file used to describe: the four catalog reads
(`/api/v1/stats`, `/api/v1/posts`, `/api/v1/posts/{id}`, `/api/v1/stream`) answer anyone who can
reach nginx, but every `api/v2/account*` route requires a bearer sync key, `_bucket_for()`
(`Fast_Fetch/viewer.py:2957`) puts each request in a token bucket and `redact.py:1163` writes the
`RateLimit-*` triple, and CORS is an **empty allow-list** (`redact.CORS_ALLOW_ORIGINS`,
`redact.py:1278`) — no origin is granted, and nothing sends `*` any more. The default bind is
loopback (`viewer.py:3491`), with nginx as the public gate. What has **not** changed: there is no
TLS and the Oracle host is plain HTTP, so nothing behind those four reads is private — do not
describe the catalog as an authorized-only or secured surface, and do not describe the account
routes as unauthenticated. Cleartext HTTP is enabled only in the debug build, and a release build
cannot currently point at the HTTP-only Oracle host without a TLS deployment.

## Backend API

The app expects these endpoints at the configured server base URL:

| Endpoint | Use |
|---|---|
| `GET /api/v1/stats` | Verify the server connection and show the server's **stored** totals |
| `GET /api/v1/posts?page=1&limit=30` | Load catalog rows |
| `GET /api/v1/posts?q={query}&type={type}&page=1&limit=50` | Search/filter catalog rows |
| `GET /api/v1/posts/{id}` | Detail screen: post + `source_pages[]` + `releases[]` (each release with `sources[]`) |
| `GET /api/v1/stream?id={sourceId}&redirect=0` | Resolve a playable URL for the player |

`/api/v1/posts` returns `page`, `limit`, `total`, `total_pages`, and `results`.
Each result carries `id`, `clean_title`, `title`, `year`, `content_type`,
`seasons`, `poster_url`, `imdb_rating`, `imdb_id`, `tmdb_id`, `genres`,
`source_site`, `industry`, `country`, `language`, `release_count`, and
`source_count` — `slug` is **not** included in the list payload.

> `GET /api/v1/stats` answers the server's own totals and they are **not** a browsable count — and
> not in any stable direction. Measured 2026-10-29: `stats.posts` answered `116922` (the Layer-1
> projection's stamped tally, `Fast_Fetch/viewer.py:2854-2869`) while `/api/v1/posts?limit=1` — which
> counts the live `posts` table with the adult rule (`viewer.py:2605`) — answered `total: 131559`.
> A day earlier the projection's adult-flagged rows made the stored figure the *larger* one; the
> owner's merges grew one table without rebuilding the other. `sources` and `active_sources` both
> answered `3783959`, so a stamped "live" count is not a playability claim either.
> The app therefore calls them what they are — `viewmodel/CatalogScale.kt` is the single owner of
> the three labels and of both connection notices, and `tooling/StatsHonestyTest` fails any surface
> that renames a stored total into a promise. A real browsable count comes from
> `/api/v1/posts?limit=1`'s adult-scoped `total`, never from reskinning this endpoint.

`type` is matched against `content_type` by **exact equality** — `movie`, `series`,
`complete_season`, `ongoing_season` — **plus one special case**: `type=anime` is answered from the
flag the ledger really holds, `(p.is_animated = 1 OR lower(p.industry) LIKE '%anime%')`
(`Fast_Fetch/viewer.py:2530`, and the same predicate behind the `industry` facet at `:2555`). It is
a filter that works today, measured `total: 5847` on 2026-10-29; the old note here claiming anime
"needs a new backend `animated` flag parameter" described the 2026-10-22 server and is retired.
The list route also appends `subtitled` per row (`viewer.py:2636`, computed by `_subtitled_posts()` at `:2466`) in the current tree — **the
deployed service has not been restarted, so the live payload does not carry that key yet**
(re-measured 2026-10-29: absent from both probe rows), and the app's Subtitled chip stays dark in
production until the next deploy.


## Build and download

The Android build runs in GitHub Actions; a local Android SDK or Android Studio
is not required. Push a branch to run the CI workflow and download its debug APK
from the run's **Artifacts** section. Version tags run the signed release
workflow; see [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md) for its required
GitHub Actions secrets.

## Project docs

| Document | Description |
|---|---|
| [`docs/PLAN.md`](docs/PLAN.md) | Current milestone and deferred app roadmap |
| [`docs/TECH_STACK.md`](docs/TECH_STACK.md) | Android stack and architecture |
| [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md) | GitHub Actions build and release setup |
| [`docs/PARITY_BACKEND_BLOCKED.md`](docs/PARITY_BACKEND_BLOCKED.md) | Which competitive features the server contract blocks, with the measurement that says so |
| [`design/SCREENS.md`](design/SCREENS.md) | Screen design references |
| [`design/DESIGN_SYSTEM.md`](design/DESIGN_SYSTEM.md) | Colors, typography, and spacing |
