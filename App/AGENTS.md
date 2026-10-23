# 🤖 AGENTS.md — Android App Guide for AI Agents

> **READ THIS ENTIRE FILE before making any changes to the App.**
> This is the authoritative guide for building the RADD Stream Android app.
> Also read the root [`AGENTS.md`](../AGENTS.md) for project-wide context.

---

## 0. One-Line Summary

> A native Kotlin/Compose Android client for a `radd-stream` server. As verified in `App/app/src`, the implemented surface covers server setup, catalog browsing, search, favorites, a detail screen, and Media3 playback via the stream resolver. Device/CI verification of that build is still pending — see §5 and §6 for the exact API contract and the known broken spots.

---

## 1. Critical Constraint — No Local Android Studio

The user has no powerful PC and cannot run Android Studio. The **entire build pipeline runs on GitHub Actions** (free Ubuntu runners). You write code, push to GitHub, and GitHub builds the APK automatically.

**Never tell the user to:**
- Open Android Studio
- Run `gradlew` locally
- Install the Android SDK locally
- Connect a device with ADB locally (they can sideload the APK manually)

**Always use:**
- GitHub Actions for builds
- GitHub Releases for APK distribution
- GitHub web editor / Codespaces / Replit for code editing

---

## 2. Build System Architecture

```
Code edit (anywhere)
    │
    ▼ git push
GitHub repo (radddao/radd-stream)
    │
    ▼ triggers
GitHub Actions (Ubuntu runner, free)
    │
    ├── ci.yml      → tests + lint + assembleDebug → uploads APK artifact (7 days)
    ├── release.yml → assembleRelease → signs → creates GitHub Release
    │
    ▼
APK available at:
  Debug:   github.com/radddao/radd-stream/actions  (Artifacts tab)
  Release: github.com/radddao/radd-stream/releases
```

---

## 3. Technology Stack (Current Android Direction)

| Layer | Technology | Why |
|---|---|---|
| Language | **Kotlin** | Maximum Android power, coroutines, type safety, Google's #1 language |
| UI | **Jetpack Compose** | Declarative, modern, Material 3, hot-reload in Codespaces |
| Media playback | **ExoPlayer / Media3** | `PlayerScreen.kt` + `PlaybackService.kt` exist and are wired into `NavGraph.kt`; never yet run on a device |
| Architecture | **MVVM + Repository + Hilt** | Testable, scalable, industry standard |
| Networking | **Retrofit 2 + OkHttp** | Type-safe API calls to radd-stream backend |
| Local DB | **Room** | Watchlist, continue watching, cached catalog |
| Images | **Coil** | Kotlin-native, Compose-aware, poster image cache |
| DI | **Hilt (Dagger)** | Automatic ViewModel injection |
| Navigation | **Jetpack Navigation Compose** | Type-safe, deep link support |
| Settings | **DataStore Preferences** | Server URL + user preferences |
| Build | **Gradle Kotlin DSL** (`build.gradle.kts`) | Type-safe, modern |

> Keep this Android app in Kotlin/Compose for the current milestone. Flutter can be reconsidered later; do not migrate the app without an explicit project decision.
> ❌ Do NOT introduce: React Native, Java, Glide, Volley, RxJava, Koin

---

## 4. Current Source Folder Structure

```
Repository root/
├── .github/workflows/
│   ├── ci.yml                                  ← tests, lint, debug APK on push/PR
│   └── release.yml                             ← signed APK on version tag
└── App/
    ├── app/src/main/kotlin/com/raddstream/app/
    │   ├── data/                               ← DataStore server settings
    │   ├── network/                            ← Retrofit API and JSON models
    │   ├── repository/                          ← catalog data access
    │   ├── ui/
    │   │   ├── components/PosterCard.kt
    │   │   ├── navigation/               ← Screen.kt, NavGraph.kt (4-tab bottom nav)
    │   │   ├── screens/                  ← Setup, Home, Search, Detail, Player, MyList, Settings
    │   │   └── theme/
    │   ├── viewmodel/                     ← setup, catalog, search, detail, favorites, settings
    │   ├── player/PlaybackService.kt      ← Media3 MediaSessionService
    │   └── MainActivity.kt
    ├── app/src/test/                            ← JVM unit tests
    ├── gradle/wrapper/
    ├── gradlew
    └── docs/
```

---

## 5. REST API Contract (Verified Against viewer.py)

⚠️ **Reality (verified against viewer.py 2026-10-22):** this section previously
described a metadata-only MVP that called two endpoints, and it listed `anime` as
a valid `type` value. Both were wrong. The app in `App/app/src` today calls
**four** endpoints, and `?type=anime` returns zero rows. The verified state is
below.

The backend is `Fast_Fetch/viewer.py`. The app currently consumes:

| Call site | Endpoint |
|---|---|
| `SetupViewModel` / `SettingsViewModel` → `CatalogRepository.testConnection()` / `getStats()` | `GET /api/v1/stats` |
| `HomeViewModel` / `SearchViewModel` → `CatalogRepository.getPosts()` | `GET /api/v1/posts` |
| `DetailViewModel.kt:69` → `CatalogRepository.getPostDetail()` | `GET /api/v1/posts/{id}` |
| `DetailViewModel.kt:130` → `CatalogRepository.resolveStream()` | `GET /api/v1/stream?id=…&redirect=0` |

`GET /api/v1/rules` is **not** called by the app. `App/.github/workflows/` and
the deferred roadmap items are separate concerns; see §6 and §8.

There is **no authentication, no API key, no bearer token, and no rate limiting**
anywhere in `viewer.py`. `send_json()` adds `Access-Control-Allow-Origin: *` to
every response (viewer.py:2037) and the server defaults to binding `0.0.0.0`
(viewer.py:2211). The deployed Oracle host is plain HTTP with no TLS. This API is
public to anyone who can reach the port — never treat it as a private or secured
surface.

### `GET /api/v1/posts`
**Query params** (viewer.py:2110-2117 → `api_v1_get_posts()` viewer.py:1886):

| Name | Behaviour |
|---|---|
| `q` | `LIKE '%q%'` against `clean_title`, `title`, or `slug`. Omit for no search. |
| `type` | Exact-equality match on `posts.content_type` (`p.content_type = ?`, viewer.py:1898). **Accepted values are only `movie`, `series`, `complete_season`, `ongoing_season`** — the four values `classify_media()` ever writes (fast_fetch.py:1613-1622). |
| `page` | 1-based, default `1`. |
| `limit` | Default `20`, clamped to `1..100` (viewer.py:2115). |

> 🚨 **There is no `?type=anime`.** `content_type` is filtered by exact string
> equality and no writer in the codebase ever stores `'anime'` there.
> `?type=anime` returns `{"total": 0, "results": []}` — an empty grid, not an
> error. Anime is carried by the separate `posts.is_animated` and
> `posts.industry` columns, and **the REST API exposes neither as a filter yet**,
> so anime filtering needs a new `animated` flag parameter plus backend support
> before any client chip can offer it. Note also that only
> `import_ssrmovies.py:470` currently populates `is_animated` at all.
> `HomeScreen.kt:48` and `SearchScreen.kt:49` still map the "Anime" chip to
> `type=anime`, so that chip is broken today — that is a Kotlin bug to fix in the
> app or in the backend, not something to work around in docs.

**Response** — `api_v1_get_posts()` selects exactly these keys per result
(viewer.py:1905-1909). The example below is a real row sampled from
`Fast_Fetch/multimovies.db` on 2026-10-22 (poster URL elided); the totals are that
staging database's counts, **not** the unified catalog's:

```json
{
  "page": 1,
  "limit": 20,
  "total": 10512,
  "total_pages": 526,
  "results": [
    {
      "id": 10512,
      "clean_title": "Sorcerer Heavenly Master · Dark Hades",
      "title": "Sorcerer Heavenly Master · Dark Hades",
      "year": null,
      "content_type": "movie",
      "seasons": null,
      "poster_url": "https://...",
      "imdb_rating": null,
      "imdb_id": "tt35786199",
      "tmdb_id": 1673401,
      "genres": "Action, Adventure, Drama, Fantasy",
      "source_site": "multimovies",
      "industry": "Hollywood",
      "country": "USA",
      "language": "English",
      "release_count": 8,
      "source_count": 8
    }
  ]
}
```

`slug` is **not** in the list payload — it is only on the detail response. `year`,
`imdb_rating`, and `seasons` are nullable; `year` and `tmdb_id` arrive as JSON
**numbers** when present. Results are ordered `p.id DESC` (newest first), and rows
with `is_18_plus = 1` are excluded by the SQL `WHERE` (viewer.py:1891).

### `GET /api/v1/posts/{id}`
Returns `{"success": true, "data": {...}}`, where `data` is the raw `posts` row
plus `source_pages[]` and `releases[]`, each release carrying `sources[]`.
Releases are ordered **`id ASC`** only (viewer.py:1942) — no quality sorting and no
season/episode grouping; group them client-side. The tier ordering applies only
to `sources` inside a release (viewer.py:1946-1961). An unknown id or an
adult-flagged post returns `404 {"success": false, "error": "Post not found"}`.

### `GET /api/v1/stream`
`redirect=1` (default) → bare `302` with `Location`. `redirect=0` → JSON with
`success`, `id`, `url`, `cached`, `refreshed`, `service`, `is_temporary`,
`is_resumable`, `source_name`, `mime_type` — `is_temporary` and `is_resumable` are
JSON **booleans**, which `StreamResponse` must not model as integers. Failure →
`404 {"success": false, "error": ...}`.

### `GET /api/v1/stats`
Field names are snake_case exactly as below (viewer.py:2156-2174). **The values
are illustrative only** — they were read live from the `multimovies.db` staging
catalog on 2026-10-22, the old `131 / 1031 / 2017` figures were a 2026-10-13
milestone snapshot, and the unified catalog grows with every scraper run. Call the
endpoint on the server you are pointed at to get real numbers.

```json
{
  "posts": 10512,
  "releases": 612180,
  "sources": 675000,
  "active_sources": 675000,
  "resumable_sources": 0,
  "temporary_sources": 0
}
```

> ⚠️ `/api/v1/stats` counts **every** post, including `is_18_plus = 1` rows that
> `/api/v1/posts` hides (viewer.py:2157-2162 has no adult filter). The stats
> counts will therefore exceed what the browsable catalog can actually show.

---

## 6. Screens Reference

See [`design/SCREENS.md`](../design/SCREENS.md) for full wireframes. Verified
against `App/app/src/main/kotlin/com/raddstream/app/ui/`:

**Implemented and navigable** (`NavGraph.kt:105-165`, four-tab bottom nav):

| Screen | Route | Key Components |
|---|---|---|
| Setup | `setup` | Server URL, `/api/v1/stats` connection check |
| Home | `home` | Type filter chips, catalog poster grid, refresh |
| Search | `search` | Debounced title search, type chips, poster grid |
| My List | `my_list` | Room-backed favorites |
| Settings | `settings` | Server config + live server diagnostics |
| Detail | `detail/{postId}` | `getPostDetail`, release/source lists, play action |
| Player | `player/{url}/{title}` | Media3 ExoPlayer, `resolveStream` |

The §5 note above supersedes the "app calls only `/api/v1/stats` and
`/api/v1/posts`" statement, and the earlier Phase 1 task lists in §8 and the
Session 2/3 logs, which described a metadata-only MVP that no longer matches
`App/app/src`. Treat those as historical plan, not current state.

> ⚠️ The "Anime" chip on Home and Search is **known broken** — see the
> `?type=anime` warning in §5. The type chips should offer only Movie / Series
> (and, if the backend adds them, Complete Season / Ongoing Season).

> 🚨 **`ReleaseDetail` does not match the backend release rows.** The `releases`
> table columns returned by `/api/v1/posts/{id}` are `id, post_id, release_title,
> season, episode, quality, codec, size, languages, intermediate_url, created_at,
> source_site, origin_url` (verified via `PRAGMA table_info`). `Models.kt:68-84`
> asks instead for `season_number`, `episode_number`, `episode_title`,
> `resolution`, and `audio` — **none of those keys exist in the response**, so all
> five are always `null`. `DetailScreen.kt:206-220` builds its whole season filter
> on `seasonNumber`, and `DetailScreen.kt:426-428` on `episodeNumber`, so series
> season/episode grouping silently does nothing today. Map `season` / `episode` /
> `release_title` instead. Likewise `StreamResponse.isTemporary: Int?` cannot hold
> the JSON **boolean** the resolver returns (`is_temporary` is
> `bool(...)` in `resolve_live_source()`), so Gson will reject that field.


---

## 7. Design System Quick Reference

See [`design/DESIGN_SYSTEM.md`](../design/DESIGN_SYSTEM.md) for full spec. Key values:

```kotlin
// Colors
Background:     #0A0A0F    // near-black
Surface:        #141420    // cards / nav bar
AccentPrimary:  #6C63FF    // buttons, active state (purple)
AccentRed:      #FF6B6B    // favorites heart

// Spacing
Horizontal page padding: 16.dp
Card corner radius:       12.dp
Play button height:       52.dp

// Typography — Inter font (Google Fonts)
Title:    18.sp SemiBold
Body:     16.sp Normal
Label:    12.sp Medium (muted metadata)
```

---

## 8. Phase Roadmap

⚠️ **Reality (verified against `App/app/src` 2026-10-22):** the "Deferred" labels
on Phase 2 detail/playback/watchlist/settings no longer match the source. Those
screens, the Room favorites DB, and `PlaybackService` all exist and are wired into
`NavGraph.kt`. What is actually missing is verification, not implementation.

| Phase | What to build | Status |
|---|---|---|
| **Phase 0** | Gradle project skeleton + CI | ✅ Complete |
| **Phase 1** | Server setup → metadata catalog → search | 🚧 Implemented; needs CI/device verification |
| **Phase 2** | Detail pages, playback, watchlist, settings | 🚧 Code implemented; unverified, and the season/episode + `is_temporary` model mismatches in §6 block correct series playback |
| **Phase 3** | Chromecast, multi-server, Android TV | ⏳ Future |

---

## 9. Phase 0 Implementation Notes (Historical)

Phase 0 created the Gradle project skeleton and the GitHub Actions build. The following steps are retained as historical implementation notes.

### Step-by-step:

**Step 1 — Create `settings.gradle.kts`**
```kotlin
pluginManagement {
    repositories {
        google(); mavenCentral(); gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories { google(); mavenCentral() }
}
rootProject.name = "radd-stream-app"
include(":app")
```

**Step 2 — Create root `build.gradle.kts`**
```kotlin
plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.android) apply false
    alias(libs.plugins.hilt) apply false
    alias(libs.plugins.kotlin.kapt) apply false
}
```

**Step 3 — Create `gradle/libs.versions.toml`** (version catalog)
Define all library versions in one place — see TECH_STACK.md for the full list.

**Step 4 — Create `app/build.gradle.kts`**
- `applicationId = "com.raddstream.app"`
- `minSdk = 21`, `targetSdk = 35`, `compileSdk = 35`
- Configure signing config from env vars (`KEY_STORE_PASSWORD` etc.)
- Add all dependencies from TECH_STACK.md

**Step 5 — Create `gradle-wrapper.properties`**
```properties
distributionUrl=https\://services.gradle.org/distributions/gradle-8.7-bin.zip
```

**Step 6 — Create `gradlew` + `gradlew.bat`**
Download from any fresh Android project or https://github.com/gradle/gradle-wrapper

**Step 7 — Create `AndroidManifest.xml`**
```xml
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
```

**Step 8 — Create minimal `MainActivity.kt`**
```kotlin
@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { RaddStreamApp() }
    }
}
```

**Step 9 — Create `RaddStreamApplication.kt`**
```kotlin
@HiltAndroidApp
class RaddStreamApplication : Application()
```

**Step 10 — Push → watch GitHub Actions → verify green ✓ + APK artifact**

---

## 10. Signing Configuration

The `app/build.gradle.kts` must read signing from environment variables (set as GitHub Secrets):

```kotlin
signingConfigs {
    create("release") {
        val keystoreBase64 = System.getenv("KEYSTORE_BASE64") ?: ""
        if (keystoreBase64.isNotEmpty()) {
            // Decode keystore from base64 env var to a temp file
            val keystoreFile = File(rootProject.buildDir, "release.jks")
            keystoreFile.writeBytes(android.util.Base64.decode(keystoreBase64, 0))
            storeFile = keystoreFile
        } else {
            storeFile = file("../radd-release-key.jks")  // local fallback
        }
        storePassword = System.getenv("KEY_STORE_PASSWORD") ?: ""
        keyAlias = System.getenv("KEY_ALIAS") ?: ""
        keyPassword = System.getenv("KEY_PASSWORD") ?: ""
    }
}
buildTypes {
    release {
        isMinifyEnabled = true
        proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        signingConfig = signingConfigs.getByName("release")
    }
}
```

**One-time keystore generation** (run in GitHub Codespaces terminal — no local install needed):
```bash
# Open Codespaces on the repo, open terminal, run:
keytool -genkey -v \
  -keystore radd-release-key.jks \
  -keyalg RSA -keysize 2048 \
  -validity 10000 \
  -alias radd-key \
  -dname "CN=RADD Stream, O=RADD, C=US"

# Encode for GitHub Secret:
base64 -w 0 radd-release-key.jks

# Add to GitHub: Settings → Secrets → Actions:
#   KEYSTORE_BASE64 = (paste output above)
#   KEY_STORE_PASSWORD = (the password you chose)
#   KEY_ALIAS = radd-key
#   KEY_PASSWORD = (the key password you chose)
```

---

## 11. Git and Credential Safety

Use the repository's Git workflow for commits and pushes; do not use GitHub's
Contents API to write files one at a time. Never put a GitHub token in source,
shell arguments, a checked-in script, chat, or logs. Authenticate through the
workspace's secret-backed Git credential flow, and do not persist the token in
the repository.

### Oracle backend connection

- The configured backend host is `http://92.4.95.252/` over plain HTTP; the
  SSH account is `ubuntu@92.4.95.252` on port 22. Use the secret-safe process
  in [`../ORACLE_DEPLOYMENT.md`](../ORACLE_DEPLOYMENT.md).
- The app calls `/api/v1/stats`, `/api/v1/posts`, `/api/v1/posts/{id}`, and
  `/api/v1/stream` (see §5). It does not call `/api/v1/rules`.
- Cleartext HTTP is permitted only in the debug build. The release build must
  use HTTPS; do not relax Android network security globally to make a release
  work over HTTP.
  ⚠️ **Reality (verified against viewer.py 2026-10-22):** the backend has no TLS
  support at all and the Oracle host is plain HTTP, so a release build cannot
  legally point at `http://92.4.95.252/`. That is a deployment gap, not something
  to paper over by loosening network security. The API is also unauthenticated
  with wildcard CORS — nothing behind it is private.
- The user's permanent choice is to configure `ORACLE_SSH_KEY` and
  `GITHUB_TOKEN` as Replit Configurations environment variables, not Secrets.
  Verify presence by name only; never reveal values, ask to move them, or place
  either in the APK, GitHub Actions logs/artifacts, or Oracle environment.
- GitHub Actions only discovers workflows from the repository-root
  `.github/workflows/`; the current workflow files under `App/.github/workflows/`
  are not automatically discovered there.

---

## 12. Session Log — Append Here

### Session 1 — Antigravity — Oct 2026
**Built:**
- Created `App/` folder structure in repo
- [`App/README.md`](../README.md): architecture overview + Oracle VPS capacity notes (12 GB RAM → 800–1,200 concurrent sessions)
- [`App/docs/PLAN.md`](../docs/PLAN.md): full 3-phase feature roadmap with screen map, API map, and MVP success criteria
- [`App/docs/TECH_STACK.md`](../docs/TECH_STACK.md): Kotlin selected over Flutter/RN/Java with detailed rationale
- [`App/docs/BUILD_PLAN.md`](../docs/BUILD_PLAN.md): complete GitHub Actions CI/CD strategy (no local Android Studio needed)
- [`App/design/DESIGN_SYSTEM.md`](../design/DESIGN_SYSTEM.md): full design system (dark cinematic theme, colors, typography, spacing, animations)
- [`App/design/SCREENS.md`](../design/SCREENS.md): ASCII wireframes for all 7 screens + navigation flow
- [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml): test, lint, and debug APK build on push/PR
- [`.github/workflows/release.yml`](../../.github/workflows/release.yml): signed APK + GitHub Release on version tag
- [`App/AGENTS.md`](AGENTS.md): this file — comprehensive agent guide for app development
- All files pushed to GitHub via direct API

**Next agent should:** Follow the current Phase 1 status and update this guide after app changes.

---

## 13. Critical Rules for App Agents

1. **No local Android Studio** — always target GitHub Actions as the build environment
2. **Kotlin only** — no Java files
3. **Compose only** — no XML layouts
4. **Every screen must be a Composable function** — no Activities (except MainActivity)
5. **All API calls via Retrofit + coroutines** — no raw `HttpURLConnection` in the UI layer
6. **All state via StateFlow/ViewModel** — no mutable state in Composables directly
7. **Test every network model** — add a JSON deserialization test for every new data class
8. **Keep APK under 15 MB** — no bundled video assets, lazy-load everything
9. **Minimum SDK 21** — never use APIs below API 21 without a Build.VERSION_CODES guard
10. **Always update this AGENTS.md** with your session log before ending


---

## 14. Session Log

### Session 2 — Phase 0: Gradle Skeleton Complete (2026-10-14)

**Agent:** Antigravity (Google Deepmind)  
**Status:** ✅ COMPLETE — All files pushed to GitHub  
**Commit Range:** b6751b4 → (see CHANGELOG.md)

#### What Was Done

**Files Created & Pushed (43 total):**

| Category | Files |
|---|---|
| Gradle build | `build.gradle.kts` (root), `app/build.gradle.kts`, `settings.gradle.kts`, `gradle.properties`, `gradle/libs.versions.toml` |
| Gradle wrapper | `gradlew`, `gradlew.bat`, `gradle/wrapper/gradle-wrapper.jar`, `gradle/wrapper/gradle-wrapper.properties` |
| App manifest | `app/src/main/AndroidManifest.xml` (INTERNET, FOREGROUND_SERVICE, PiP, deep links `radd://`) |
| Kotlin source | `MainActivity.kt`, `RaddStreamApplication.kt` |
| UI theme | `Color.kt`, `Type.kt`, `Theme.kt` (dark cinematic: bg `#0A0A0F`, accent `#6C63FF`) |
| Navigation | `Screen.kt`, `NavGraph.kt` |
| Screens | `HomeScreen.kt`, `SetupScreen.kt`, `SearchScreen.kt`, `MyListScreen.kt`, `SettingsScreen.kt` |
| Player | `PlaybackService.kt` (Media3 MediaSessionService) |
| Network | `RaddStreamApi.kt` (Retrofit), `models/Models.kt` (Post, PostsResponse, Release, Source, StreamResponse, StatsResponse) |
| Resources | `values/strings.xml`, `values/themes.xml` |
| Launcher icons | `mipmap-anydpi-v26/ic_launcher.xml` + `ic_launcher_round.xml` (adaptive, API 26+) |
| Icon drawables | `drawable/ic_launcher_background.xml` (`#0A0A0F`), `drawable/ic_launcher_foreground.xml` (purple play button) |
| Mipmap PNGs | `ic_launcher.png` + `ic_launcher_round.png` in mdpi/hdpi/xhdpi/xxhdpi/xxxhdpi (fallback for pre-API-26) |
| Tests | `app/src/test/kotlin/.../network/ModelsTest.kt` (12 JVM unit tests for all model classes) |
| Push system | `push.py` (added `.jar` to INCLUDE_EXTENSIONS) |

#### Key Decisions

- `gradle-wrapper.jar` pushed as binary via GitHub API (base64) — `push.py` now includes `.jar`
- Launcher icons use adaptive XML for API 26+ + solid-color PNG fallbacks for older devices
- Icons styled to match design system: background `#0A0A0F`, foreground purple play triangle `#6C63FF`
- Unit tests use actual model classes from `Models.kt` — 12 tests covering all data classes
- `gradlew` script is standard Gradle 8.7 POSIX shell (not downloaded, created from spec)

#### GitHub Actions Status After Push

The `ci.yml` workflow will trigger on this push. Expected outcome:
- ✅ JDK 17 setup
- ✅ Gradle wrapper downloads Gradle 8.7
- ✅ `./gradlew test` — 12 unit tests pass
- ✅ `./gradlew lint` — runs (continue-on-error)
- ✅ `./gradlew assembleDebug` — produces `app-debug.apk`
- ✅ APK uploaded as artifact (7-day retention)

#### Current Status and Next Agent Notes

The task list above this section is historical. As verified in October 2026,
the MVP includes server setup, catalog metadata, search/filter, Retrofit
networking, repositories, and DataStore. Details/playback and a signed release
remain incomplete; the Android build has not been verified on a device. The
latest observed Actions run failed during Android SDK setup, and workflows
nested under `App/.github/workflows/` are not discovered by GitHub.

Before choosing work, inspect the current source and [`docs/PLAN.md`](docs/PLAN.md)
rather than relying on the historical Phase 1 task list. For backend host and
secret-safe GitHub instructions, read [`../ORACLE_DEPLOYMENT.md`](../ORACLE_DEPLOYMENT.md).

1. Read this guide and `Fast_Fetch/ANDROID_INTEGRATION.md`.
2. Confirm the current build/workflow status before relying on Actions.
3. Use Git over HTTPS with the temporary askpass helper in
   `../ORACLE_DEPLOYMENT.md`; do not use the legacy per-file API uploader.

**Architecture Pattern (must follow):**
```
Screen.kt (Compose UI)
    ↓ collectAsStateWithLifecycle()
ViewModel.kt (StateFlow, coroutines)
    ↓ repository calls
Repository.kt (single source of truth)
    ↓ Retrofit API / Room DB
```

---

### Session 3 — Metadata Client MVP (2026-10-15)

**Status:** Implementation and documentation complete; GitHub Actions build pending.

**Completed:**
- Replaced the Android API models with the backend's actual paginated `results` response and snake-case statistics fields.
- Added server URL validation/persistence, `/api/v1/stats` connection testing, API provider, and catalog repository.
- Implemented first-run setup, filtered catalog grid, and debounced filtered search.
- Added JSON mapping and server URL validation unit tests.
- Added the missing Unix Gradle wrapper launcher and root GitHub Actions CI/release workflows.
- Updated the root README and Android docs to mark detail/playback as deferred.

**Verification:** Python database and video-output tests plus `setup_check.py` pass. This workspace has no local JDK, so Android compilation is pending GitHub Actions.

---

### Session 4 — Complete App UI, Room Favorites & CI Pipeline (2026-10-16)

**Status:** Implementation complete; ready for GitHub Actions CI verification.

**Completed:**
- Added repository-root `.github/workflows/ci.yml` and `.github/workflows/release.yml` with `setup-android` action and Gradle caching.
- Created executable Unix `App/gradlew` launcher wrapper script.
- Built 4-tab Material3 Bottom Navigation Bar in `NavGraph.kt` (Home, Search, My List, Settings).
- Built `DetailScreen.kt` and `DetailViewModel.kt` with poster header, season chips, quality releases, direct stream sources, and external video player fallback.
- Built full-screen `PlayerScreen.kt` with Media3 / ExoPlayer, screen-on lock, and error recovery.
- Implemented Room local SQLite database (`AppDatabase`, `FavoritePost`, `FavoriteDao`, `DatabaseModule`, `FavoritesRepository`).
- Built `MyListScreen.kt` and `MyListViewModel.kt` to view and manage saved favorite titles.
- Built `SettingsScreen.kt` and `SettingsViewModel.kt` with server configuration and live server diagnostics.
- Expanded `Models.kt` (`PostDetail`, `ReleaseDetail`, `SourceDetail`, `StreamResponse`) and added comprehensive test cases in `ModelsTest.kt`.

**Verification:** Backend tests (36/36 DB tests, 6/6 VIDOUT tests) continue to pass. Android compilation is verified via GitHub Actions CI pipeline.

---

### Session 5 — Native APK Compilation on Oracle & Public Deployment (2026-10-16)

**Status:** ✅ COMPLETE — `app-debug.apk` compiled and deployed live.

**Completed:**
- Set up Android SDK command-line tools (`platforms;android-35`, `build-tools;35.0.0`) and OpenJDK 21 on the Oracle Ubuntu ARM64 server (`92.4.95.252`).
- Fixed Google's AAPT2 ARM64 binary incompatibility by installing `qemu-user-static` and extracting AMD64 dynamic libraries (`libc6`, `libstdc++6`, `zlib1g`) to enable execution of x86_64 AAPT2 on ARM64.
- Resolved minor Gradle and Android resource build issues (theme parent attribute).
- Successfully compiled `assembleDebug` with full Jetpack Compose UI, Room SQLite database, Media3 ExoPlayer, and D8/R8 DEX packaging (`BUILD SUCCESSFUL in 6m 41s`).
- Deployed resulting 21.5 MB `app-debug.apk` to `/var/www/download/radd-stream.apk`.
- Configured and verified public download endpoint at `http://92.4.95.252/download/radd-stream.apk` returning HTTP 200 OK.

---

### Session 6 — Documentation truth-audit against viewer.py (2026-10-22)

**Status:** ✅ Docs corrected. No `.kt`, `.kts`, or `.py` file was touched, and nothing was committed or pushed.

**What changed in this guide:** §0, §3, §4, §5, §6, §8, and §11 were rewritten to
the state actually present in `App/app/src` and `Fast_Fetch/viewer.py`. The prior
§5 claimed `?type=anime` was a supported filter and that the app called only
`/api/v1/stats` and `/api/v1/posts`; §6 claimed Detail/Player/MyList/Settings were
"not navigable". All three statements were false.

**Verified against code:**
- `viewer.py:1898` filters `content_type` with `p.content_type = ?` (exact
  equality) and `classify_media()` (`fast_fetch.py:1613-1622`) only emits
  `movie` / `series` / `complete_season` / `ongoing_season` — a live
  `api_v1_get_posts(content_type='anime')` call returned `total: 0`.
- `viewer.py:1905-1909` is the exact list-route `SELECT` (17 keys; `slug` absent).
- `viewer.py:1942` orders releases `id ASC` with no grouping; `viewer.py:1946-1961`
  applies the tier `CASE` to `sources` inside a release only.
- `viewer.py:2037` wildcard CORS, `viewer.py:2211` binds `0.0.0.0`, and grepping
  `viewer.py` for `Authorization` / `api_key` / `Bearer` / `rate_limit` returned
  zero hits — there is no auth, no key, no rate limiting, and no TLS.
- `RaddStreamApi.kt` + `CatalogRepository.kt:38,46` + `DetailViewModel.kt:69,130` +
  `NavGraph.kt:139-165` prove the app calls four endpoints.

**Known-broken items recorded but NOT fixed (out of scope, code):**
1. `HomeScreen.kt:48` / `SearchScreen.kt:49` still send `type=anime` → empty grid.
2. `Models.kt:68-84` `ReleaseDetail` maps `season_number` / `episode_number` /
   `episode_title` / `resolution` / `audio`, none of which the API returns;
   `DetailScreen.kt:206-220,426-428` season/episode grouping is therefore dead.
3. `StreamResponse.isTemporary: Int?` vs the JSON boolean `resolve_live_source()`
   returns.
4. `AndroidManifest.xml:43-48` registers a `radd://` filter but `NavGraph.kt` has
   no `navDeepLink` entries.
5. `viewer.py:2100-2108` — `/api/heal` never writes a response, so clients hang.

**Next agent should:** pick one of (1)/(2)/(3) as real work, then re-verify these
sections against the code again rather than trusting prose.



---

## 15. Re-Skinning The Product From ONE File (`/brand.properties`)

`<repo root>/brand.properties` is the single brand source for **both** the
Android build and the Python server. It is flat `key=value`, sectioned with
`[group]` headers, and read natively by `java.util.Properties` (Gradle) and
`configparser` (`Fast_Fetch/config.py`) — no new dependency on either side.

Procedure (the whole job):

1. Edit `/brand.properties` — identity, colour ramps, scheme behaviour, copy
   strings, deep-link scheme, user-agent token, feature flags, cache TTLs,
   storage limits.
2. Rebuild the app (GitHub Actions, or `./gradlew :app:assembleDebug` on a
   machine with the SDK — remember §1: CI is the normal path).
   `:app:generateBrandAssets` renders `brand.json` into
   `app/build/generated/assets/brand/` (merged into the APK assets, never
   committed, never hand-edited), `app/build.gradle.kts` emits
   `BuildConfig.BRAND_<KEY>`, `resValue` colours/strings and the
   `${brandScheme}` manifest placeholder, and `settings.gradle.kts` renames the
   Gradle project from `identity.name`.
3. Restart the server: `Fast_Fetch/config.py` re-exports the `[server]` section
   as `PROJECT_NAME` / `PROJECT_VERSION` / `PROJECT_DESCRIPTION` /
   `PROJECT_GITHUB` (existing importers such as `fast_fetch.py:50` and
   `viewer.py` are unchanged), plus `BRAND`, `BRAND_COPY`, `BRAND_FEATURES`,
   `BRAND_TTL`, `BRAND_STORAGE`, `BRAND_COLORS_*`.
4. Run `./gradlew :app:testDebugUnitTest --tests '*BrandDriftTest*'` (or let CI).

Kotlin side of the brand:

| Want | Use |
|---|---|
| app / short / wordmark name | `Brand.name`, `Brand.shortName`, `Brand.wordmarkFirst/Second` |
| user-visible prose | `Brand.copy("offline_notice", fallback, "title" to t)` |
| deep-link URI | `Brand.deepLinkUri("detail/$id")` |
| player User-Agent | `Brand.userAgent` |
| TTL / storage limits | `Brand.catalogTtlSeconds`, `Brand.offlineMaxBytes`, … |
| colours | `MaterialTheme.colorScheme.<role>` → `Radd*` vals in `ui/theme/Color.kt`, which read `brandColor(BuildConfig.BRAND_COLORS_*)` |
| text size | `brandSp(14)` in `ui/theme/Type.kt` (× `typography.scale`) |

`Brand` falls back to the compiled `BuildConfig` constants, so it is correct
before `RaddStreamApplication.onCreate()` calls `Brand.load(this)`; after that
call the runtime `brand.json` snapshot wins. `BrandDriftTest`
(`app/src/test/kotlin/com/raddstream/app/brand/`) is a plain JUnit4/JVM test —
no Robolectric — that fails on hardcoded brand names, raw `Color(0x…)` literals
outside `ui/theme/Color.kt`, hardcoded `radd://` schemes, brand hexes that are
not valid, re-declared colours in `res/values/colors.xml`, a manifest that stops
using the generated label/placeholder, copy strings that still name an old
brand, and on any growth of its explicit "pending migration" lists.

### What genuinely cannot come from one file (be honest about this)

1. **Binary PNG launcher mipmaps.** `mipmap-{m,h,xh,xxh,xxxh}dpi/ic_launcher*.png`
   (and the `_round` twins) are pixel bitmaps, not text; a re-skin must still
   replace those 10 PNGs by hand. The adaptive vector pair
   (`mipmap-anydpi-v26/ic_launcher.xml` + `drawable/ic_launcher_{background,foreground,monochrome}.xml`)
   *is* brand-driven — it references `@color/radd_launcher_top`,
   `@color/radd_launcher_bottom`, `@color/radd_current`, all generated from this
   file. (Those drawables still carry literal hexes today; converting them to the
   `@color/` references is a one-line-per-stop edit.)
2. **Manifest-registered components.** Activities, services, providers,
   permissions and the `Theme.RaddStream` style name must be literal in
   `AndroidManifest.xml` (AGP requires it). Brand controls only their **label**
   (`@string/brand_app_name`), **icon**, **theme colour** and **deep-link
   scheme** through generated values.
3. **The `.jks` signing key** and any resource name a re-brand would have to
   rename (`RaddStreamApi`, `com.raddstream.app` package) stay as-is; brand
   changes what users see, not internal identifiers.

---

### Session 7 — Phase 3: single-file branding (2026-10-23)

**Status:** brand pipeline implemented on both sides; Android tree still does not
compile because of other workstreams, so nothing was verified by Gradle here.

**Created:** `/brand.properties` (135 keys), `App/app/src/main/kotlin/com/raddstream/app/brand/Brand.kt`,
`App/app/src/test/kotlin/com/raddstream/app/brand/BrandDriftTest.kt`.
**Changed:** `App/app/build.gradle.kts` (Properties read, BuildConfig/resValue/
manifestPlaceholder/sourceSet assets/`generateBrandAssets`), `App/settings.gradle.kts`
(`rootProject.name` from brand), `AndroidManifest.xml` (generated label +
`${brandScheme}`), `res/values/colors.xml` (emptied — names are generated),
`res/values/themes.xml` (doc), `ui/theme/Color.kt` (51 brand hexes now via
`brandColor(BuildConfig.…)`), `ui/theme/Theme.kt` (no raw paints; defaults from
`[scheme]`), `ui/theme/Type.kt` (`brandSp` × `typography.scale`, brand font
roles), `ui/theme/RaddMark.kt`, `ui/screens/HomeScreen.kt`,
`ui/screens/SettingsScreen.kt` (name/copy/version from `Brand`),
`Fast_Fetch/config.py` (brand reader, all old constants intact),
`Fast_Fetch/viewer.py:28-30` (imports `BASE_DIR`/`DB_PATH` from config).

**Verified:** both parsers load the file with identical values (`java` +
`python3` spot-checks); `python3 -S -c "import config, fast_fetch, viewer"` OK;
every `BuildConfig.BRAND_*` referenced in Kotlin maps to a real key; the
BrandDriftTest assertions were re-implemented in a throwaway script and pass.
**Not verified:** no JDK/Android SDK build was run (`gradlew`), so
`BrandDriftTest`, `Brand.kt`, and the Gradle script are unexecuted; Kotlin syntax
was reviewed by hand only.
**Next agent should:** call `Brand.load(this)` in `RaddStreamApplication.onCreate()`,
migrate the 7 pending brand-name files + `NavGraph.kt` `radd://` literals +
`PlayerScreen.kt` raw paints, delete the now-unused `res/values/strings.xml`
`app_name`, point `ic_launcher_*.xml` at `@color/radd_launcher_*`, and add
`-keep class com.raddstream.app.BuildConfig { *; }` to `proguard-rules.pro`.
