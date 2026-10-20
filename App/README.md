# RADD Stream Android App

Native Kotlin and Jetpack Compose client for browsing metadata from a RADD Stream
server.

## Current milestone

The Android MVP currently supports:

- First-run server URL setup with a real `GET /api/v1/stats` connection check.
- Persisting the server URL locally after a successful connection.
- A poster grid populated by `GET /api/v1/posts`.
- Movie, series, and anime type filters.
- Debounced title search with the same server-side filters.
- Loading, empty, retry, and connection-error states.

The app currently displays catalog metadata only. It does not resolve source
links or play media. Use it only with a server and catalog you are authorized
to access. HTTPS is recommended for release builds; cleartext HTTP is enabled
only in the debug build for local development.

## Backend API

The app expects these endpoints at the configured server base URL:

| Endpoint | Use |
|---|---|
| `GET /api/v1/stats` | Verify the server connection and show the title count |
| `GET /api/v1/posts?page=1&limit=30` | Load catalog rows |
| `GET /api/v1/posts?q={query}&type={type}&page=1&limit=50` | Search/filter catalog rows |

`/api/v1/posts` returns `page`, `limit`, `total`, `total_pages`, and `results`.
The client maps each result's title, year, type, poster, rating, and source-site
metadata.

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
| [`design/SCREENS.md`](design/SCREENS.md) | Screen design references |
| [`design/DESIGN_SYSTEM.md`](design/DESIGN_SYSTEM.md) | Colors, typography, and spacing |
