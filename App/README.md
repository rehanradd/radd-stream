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
- Type filter chips for **Movie and Series only**. The "Anime" chip in
  `HomeScreen.kt:48` / `SearchScreen.kt:49` sends `?type=anime`, which the backend
  does not support and which returns zero results — see the API note below.
- Debounced title search with the same server-side filters.
- Loading, empty, retry, and connection-error states.
- A detail screen (`GET /api/v1/posts/{id}`) and Media3 playback through
  `GET /api/v1/stream?id=…&redirect=0`, plus local Room favorites. None of this
  has been run on a real device yet.

The backend itself has **no authentication, no API keys, no sessions, and no rate
limiting**, replies with `Access-Control-Allow-Origin: *`, binds `0.0.0.0` by
default, and has no TLS — the Oracle host is plain HTTP. Nothing in this API is
private; do not describe it as an authorized-only or secured surface. Cleartext
HTTP is enabled only in the debug build, and a release build cannot currently point
at the HTTP-only Oracle host without a TLS deployment.

## Backend API

The app expects these endpoints at the configured server base URL:

| Endpoint | Use |
|---|---|
| `GET /api/v1/stats` | Verify the server connection and show the title count |
| `GET /api/v1/posts?page=1&limit=30` | Load catalog rows |
| `GET /api/v1/posts?q={query}&type={type}&page=1&limit=50` | Search/filter catalog rows |
| `GET /api/v1/posts/{id}` | Detail screen: post + `source_pages[]` + `releases[]` (each release with `sources[]`) |
| `GET /api/v1/stream?id={sourceId}&redirect=0` | Resolve a playable URL for the player |

`/api/v1/posts` returns `page`, `limit`, `total`, `total_pages`, and `results`.
Each result carries `id`, `clean_title`, `title`, `year`, `content_type`,
`seasons`, `poster_url`, `imdb_rating`, `imdb_id`, `tmdb_id`, `genres`,
`source_site`, `industry`, `country`, `language`, `release_count`, and
`source_count` — `slug` is **not** included in the list payload.

`type` is matched against `content_type` by **exact equality**, so the only values
that ever return rows are `movie`, `series`, `complete_season`, and
`ongoing_season`. Anime is stored in `is_animated` / `industry`, which this API
does not expose as a filter — anime filtering needs a new backend `animated` flag
parameter before a client can offer it.


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
