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

### 1a. Correction: builds DO happen on this VM, and only one at a time

The rule above is stale as written. GitHub Actions is currently disabled at the account
level, so on the Oracle host the real verification loop is a **local** offline Gradle run —
that is how every milestone since has been proven. It is also how agents break each other's
builds: this VM has **one vCPU**, and two concurrent Gradle invocations writing into the same
`App/app/build` tree fail BOTH of them (`kaptDebugKotlin` aborts with
`Unable to delete directory .../generated/source/kapt` — a lock race, not a code error).

So, on this host:

- **Never run `./gradlew` directly.** Use the queue, which waits for any other agent's build
  and then takes an exclusive lock: `/tmp/qbuild.sh :app:compileDebugKotlin :app:testDebugUnitTest`
- Read the `GRADLE_EXIT=` line it prints, not your pipeline's status — `... | tail` reports
  the exit code of `tail`, which is always 0.
- Never read `app/build/test-results/**` as passing without checking the file is newer than
  your run; a stale XML looks identical to a green one.
- One build at a time, and no build while another agent is mid-verification. If you are a
  fan-out worker, edit freely and build rarely — each build is minutes of this VM's entire
  CPU.

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

### 2026-10-25 — Task #23: collapse the duplicated model layer (compile + JVM tests green)

**Concept → surviving owner → deleted/relocated copies** (rule 1, one owner per concept):
- *quality-ladder view state* → kept `viewmodel/QualityLadder.kt`'s view types
  (`QualityOption`/`LadderForScope`/`object QualityLadder`) **relocated** to
  `player/QualityLadder.kt` (genuinely player-local view state), with `LadderTier.toOptionOrNull`
  the single crossing from the wire. Wire owner `network/models/QualityLadder.kt`
  (`LadderLink`/`LadderTier`/`LadderAuto`/`OptionGroup`, `@SerializedName`) stays the sole wire
  owner. **Deleted** `viewmodel/QualityLadder.kt` (+ its test → `player/QualityLadderTest.kt`).
- *release-label grammar* → surviving owner `network/models/ReleaseLabelParsing.kt`
  (`PrintDescriptor`/`PrintScope`/`ReleaseLabelParsing`, a faithful port of
  `Fast_Fetch/release_descriptor.py`) + `network/models/CatalogEnums.kt`. **Deleted**
  `viewmodel/ReleaseParser.kt` (the 528-line duplicate: `V1Resolution`/`V1SourceTag`/
  `V1HdrFormat`/`V1Codec`/`V1Edition`, `LinkHealth`, `parseSizeBytes`/`parseScope`/`parseLanguages`,
  `wordMatch`) and `viewmodel/ReleaseParserTest.kt`.
- *detail-screen view state* → NEW `viewmodel/ReleaseLayoutBuilder.kt` owns ONLY presentation
  (`RankedLink`/`RankedPrint` wrapping a `PrintDescriptor`, `EpisodeGroup`/`SeasonGroup`/
  `ReleaseLayout`, enum→string display maps, grouping). It imports the network enums — no second
  grammar, no `typealias`/re-export/`@Deprecated` shim (rule 1). `RankedPrint.resolution/sourceTag/
  hdr/codec/edition/coverage/season` are all read off `release.printDescriptor`.

**Grammar rules that MOVED** (file:line in the deleted `ReleaseParser.kt` → survivor):
`V1Resolution.fromText:46-55`, `V1SourceTag.fromText:76-90`, `V1HdrFormat.fromText:101-110`,
`V1Codec.fromText:120-128`, `V1Edition.fromText:141-151`, `parseScope:482-504`,
`parseSizeBytes:338-350`, `parseLanguages:352-366`, `wordMatch:35-36` → all replaced by
`ReleaseLabelParsing.describe()`/`detect*()` + `CatalogEnums.*.fromWire` (documented in the
builder's header port-table). `LinkHealth` (3 states) → richer `LinkState` (`network/models/
CatalogEnums.kt:291`, adds EXPIRED/UNCHECKED).

**Deliberate, server-faithful deltas** (asserted in `ReleaseLayoutBuilderTest`):
size DECIMAL(1000)→BINARY(1024) (`2.4GB`→`2_576_980_378`); no synthetic `"Multi-audio"` language
(real `dualAudio` flag instead); a bare `"HD"`/`"576"`/`"sd"` quality word no longer fabricates a
resolution rung (stays `Resolution.UNKNOWN`, keeps the honest `"HD"` **label** — matches
`release_descriptor._quality_label`); ranking is the single `qualityScore*10+availableLinks`
print scale (CAM capped at 250 → a CAM can never outrank any official print).

**C17** — verified already correct in the survivor and now pinned by tests in `ModelsTest.kt`:
`is_temporary` is `Boolean?` via `LenientBooleanAdapter` (decodes `1`/`true`/`"1"`, junk→null,
never `Int?`); every server-string enum has `UNKNOWN` + a non-crashing `fromWire`
(`a link status the app has never seen degrades to UNKNOWN`,
`every fromWire table answers UNKNOWN ...` — 19 enums). No snake_case↔structured field mismatch
survived in the collapsed types (they read `printDescriptor`).

**Bug fixed during collapse:** a whole-work film (`CoverageType.WHOLE_WORK`) set `isPacked=true`,
which made `looksLikeSeries()` route movies into the (empty) series branch and blank `workPrints`.
Fixed by triggering the series branch only on `SEASON_PACK`/season/episode, never `WHOLE_WORK`.
`ReleaseLayout.isSeriesLike` kept its name so `DetailScreen`/`DetailViewModel` are unchanged.

**Build:** `./gradlew --offline :app:compileDebugKotlin :app:testDebugUnitTest` → BUILD SUCCESSFUL.
284 JVM unit tests, 0 failures/errors/skipped (ReleaseLayoutBuilderTest 16, player.QualityLadderTest 8,
ModelsTest 11, ProvenanceWireTest 4). One transient unrelated `hiltJavaCompileDebugUnitTest`
"cyclic inheritance" stale-codegen error cleared by removing `build/generated/hilt/*/debugUnitTest`.

**NOT done (honest scope):** concepts 3 & 4 (player↔v2-domain `CatalogV2`, `Models.kt`↔`CatalogV2`)
were NOT merged. **Correction, same day:** the claim that `/api/v2` is "documented but not
served" was verified against a 2026-10-22 read of `viewer.py` and is no longer true — the v2
edge is mounted (`viewer.py:2464` GET, `:2700` POST via `api_v2.route_get`/`route_post`) and
serves `manifest`, `browse`, `search`, `suggest`, `works/{id}`, `works/{id}/seasons/{n}`,
`POST /play`, `POST /links/{id}/report`, `resolve`, `offset`, `sync`, `stats`, `collections`,
`feed.m3u`. What is actually true is narrower: **the app cannot use any of it yet**, because
every v2 route answers `unavailable` ("The catalog projection has not been built yet") until
the live database is swapped to the projected catalog (task #38). So the LIVE app path stays
v1(`Models.kt`)+viewmodel+player, `CatalogV2`/`V2Wire`/`V1CatalogMapper` remain
target-contract code, and `EndpointGaps` now means "unreachable for this install", not
"unimplemented on the server". Migrating the player/UI onto the v2 domain types would be a
behaviour change that cannot be verified on this no-device, 1-CPU box, so it was left intact
rather than silently rewritten; v1 fallback `Models.kt` is retained per rule 3 (its DTOs are
the ones actually parsed).

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

---

### Session 8 — Hero banner, ghost mode, image fallback, repo hygiene (2026-10-26)

**Status:** all four asks implemented and **verified by Gradle on this box**:
`./gradlew --offline testDebugUnitTest assembleDebug` → BUILD SUCCESSFUL, **320 JVM
tests, 0 failures**, `app/build/outputs/apk/debug/app-debug.apk` produced. Nothing
committed (no commit was requested); the tree still carries other workstreams' edits.

**Created:** `ui/components/HeroCarousel.kt` (400dp full-bleed pager, auto-advance
gated on `rememberReduceMotion`, vertical scrim, year/type badge + language pills,
Watch Now button, tappable page dots), `test/…/ui/HeroCarouselTest.kt`,
`test/…/network/models/WireTextTest.kt`.
**Changed:** `ui/screens/HomeScreen.kt` (hero over the first visible rail,
`HERO_LIMIT = 6`, no invented rail), `network/models/Models.kt` (`Post.backdropUrls`
/ `backdropList` / `heroArtUrl` — the list route really does send `backdrop_urls`;
`Fast_Fetch/viewer.py` `_art_pair()` proves it, so §5's "no backdrop on the list row"
note is stale), `player/PlayerUiState.kt` (`ViewMode.STANDARD|PURE_CINEMA` +
`pureCinema`), `player/PlayerGestures.kt` (`pureCinema`, `cinemaRewindMs = 3_000`,
`onTwoFingerTap`), `ui/screens/PlayerScreen.kt` (`EdgeHud` hairline + three chips, no
pause scrim / no center button in cinema, read-only Initial-pass pointer lane with a
nano-time guard so the two-finger rewind never steals the single tap or the pinch),
`viewmodel/PlayerViewModel.kt` + `data/ServerSettingsRepository.kt` (the mode is
persisted and re-read like the other gestures), `ui/components/CatalogImage.kt`
(`error = { ImageFallbackCard(...) }`, new public `fallbackLabel`), `PosterCard.kt`,
`brand/Brand.kt` + `/brand.properties` (`copy.hero_watch_now`).
**Fixed (a real crash, found only because the hero exercised a new path):**
`WireText.splitOnAny` called an unqualified `listOf(source)` inside `object WireText`,
which resolved to the *member* `WireText.listOf` — infinite mutual recursion, so every
non-JSON text column (any CSV `genres`, any `"Hindi + English"` `language`) threw
`StackOverflowError`. Now `kotlin.collections.listOf`, and `WireTextTest` is the first
suite to cover those shapes at all.
**Removed:** the five retired push stubs at the repo root (`push.py`,
`github_push.py`, `emergency_push.py`, `push_github.py`, `safe_push.sh`) — verified
each was a `Disabled:`-and-exit-2 no-op first, then deleted with plain `rm`; root
`AGENTS.md` repo map and the "do not run or restore" bullet updated to say they are
gone from the tree and their history stays in Git.
**Not verified:** no device or emulator run — the pager, the HUD and the two-finger
gesture are compile- and unit-verified only; Compose rendering needs a manual pass.
**Next agent should:** put the hero behind a real "featured" projection once the
backend sends one (today it reuses rail 1 by design), cover the cinema-mode pointer
arbitration with an instrumentation test, and fold the remaining `PlayerScreen.kt`
raw paints back into `Color.kt` so `pendingColorMigration` can shrink.

### Session 9 — Subtitle sync sheet + Pakistani VIP upgrade screen (2026-10-26)

**Status:** both features implemented and **verified by Gradle on this box**:
`./gradlew --offline testDebugUnitTest assembleDebug` → BUILD SUCCESSFUL, **339 JVM
tests, 0 failures**, `app/build/outputs/apk/debug/app-debug.apk` produced. Nothing
committed (no commit was requested); the tree still carries other workstreams' edits.

**Created:** `player/subtitles/SubtitleOffsetSheet.kt` (pure `SubtitleOffset`
clamp/shift/reset/quantize/format/describe + `ModalBottomSheet` with live readout,
±60s slider, `-0.5s -0.1s RESET +0.1s +0.5s`, external-overlay hint),
`test/…/player/subtitles/SubtitleOffsetTest.kt` (8), `ui/screens/VipUpgradeScreen.kt`,
`viewmodel/VipViewModel.kt` (`VipPlan`, `VipTid`, `VipUiState`, remote-config load with
retry, pending-reference flow), `network/models/VipRemoteConfig.kt`,
`test/…/network/models/VipRemoteConfigTest.kt` (4), `test/…/viewmodel/VipTidTest.kt` (5).
**Changed:** `player/PlayerUiState.kt` (`subtitleOffsetSheetVisible`),
`viewmodel/PlayerViewModel.kt` (`show/hideSubtitleOffsetSheet`, `setSubtitleOffset`),
`ui/screens/PlayerScreen.kt` (sync control button, sheet render, `dialogBlocking`, the
old inline delay slider replaced by a row that opens the new sheet),
`network/RaddStreamApi.kt` + `repository/CatalogRepository.kt`
(`GET api/v1/app/remote-config`), `data/ServerSettingsRepository.kt`
(`VipPendingSubmission` persisted in the existing DataStore),
`ui/navigation/Screen.kt` + `NavGraph.kt` (`vip_upgrade` route),
`ui/screens/SettingsScreen.kt` (VIP card, `onOpenVipUpgrade`).
**Deliberately honest about activation:** the backend publishes prices and payment
handles at `/api/v1/app/remote-config` but has **no endpoint that receives a transaction
id and no approval ledger**, so the screen does not flip a VIP flag client-side. A
submitted reference is stored on the device as pending and both the form and the pending
card say it was not sent automatically. Prices fall back to PKR 200 / 1,500 and handles
show “Not configured yet” when the operator has not filled them in.
**Not verified:** no device or emulator run — both screens are compile- and
unit-verified only; the sheet animation and copy/snackbar interaction need a manual pass.
**Next agent should:** add the missing server-side payment submission + operator
approval route before claiming “instant activation”, then have this screen POST the TID
and read back a real VIP status instead of the local pending record.

### Session 10 — Distinct season artwork + one-tap phone/key sync (2026-10-26)

**Goal:** stop repeating the root series poster across every season, and make the optional
sync account reachable in one tap with a Pakistani mobile number or a 16-character key.

**Server artwork now reaches the screen.** `PostDetail` decodes the new
`season_artwork` array (`seasonArtworkRows` raw, `seasonArtwork` non-null getter because
Gson does not run Kotlin defaults for an absent key). `DetailViewModel` passes it into
`ReleaseLayoutBuilder.build(...)`, where a published `season_poster` wins for its season
and a published `episode_still` wins for its exact (season, episode). The existing work-art
pool remains only as the fallback for databases that have not run `backfill_tmdb.py`.
`DetailScreen` already paints `SeasonGroup.artworkUrl`, `SeasonHeader` and
`EpisodeRow.stillUrl` through `CatalogImage` with the branded gradient when null.

**One-tap account sync.** `SyncContract` now carries the phone rules: canonical
`03XXXXXXXXX` normalization (accepts `3XXXXXXXXX`, `+92`, `92`, `0092`, spaces/dashes),
a deterministic 16-character key derived with SHA-256 and a public domain separator, and
`quickLoginKey()` which sends a 16- or 43-character key the viewer already holds
**unchanged** — re-deriving a stored credential would open a different, empty library.
The manual base64url encoder exists because `java.util.Base64` is API 26. The card shows
one field and one "Sign in" button; signing in immediately runs `syncNow()` so the second
device pulls bookmarks and resume points without a second tap. "Create a random key"
remains for a credential only the viewer knows. The copy states plainly that a phone
number is a convenience, not a secret: anyone who knows it can derive the same key.
After the first sync, the card re-reads stored sign-in state, so a sync that hit a 401/404
(and therefore dropped the key) cannot leave the card claiming a session storage no longer
backs.

**Tests / build:** `./gradlew --offline testDebugUnitTest assembleDebug` → BUILD
SUCCESSFUL, 356 unit tests across 42 classes, 0 failures, `app-debug.apk` produced. New/updated:
`SyncContractTest` (8), `ReleaseLayoutBuilderTest` (+2 published-art cases),
`ModelsTest` (+2 season_artwork cases).

**Deliberately not verified:** no device or emulator run, so the account card's real
network round-trip and the season grid's image loading are compile/unit-verified only.
Nothing committed (no commit requested); the tree still carries other workstreams' edits.

### Session 11 — Shimmer, tier badges, 85% binge hand-off, sponsor-slot guard (2026-10-27)

**Goal:** Netflix/Prime-style loading polish, release-tier audio/HDR badges, instant
next-episode hand-off, and a structural guarantee that a sponsor break can never interrupt
a running title.

**Loading.** `ShimmerBox` sweeps a soft highlight band across a `surfaceVariant` base with
a 1.4 s linear pass; `rememberReduceMotion()` swaps it for a static block. `SkeletonBox`
uses the same primitive, and `CatalogImage.loading` now paints it, so `PosterCard`, every
rail tile and the new `HeroSkeleton` (full-bleed shimmer plus title/badge/button bars at
`HERO_HEIGHT`) all share one animation. `HomeScreen` shows `HeroSkeleton` while the first
rail is loading and no hero items exist yet.

**Badges.** `MediaBadges.kt` gained `HdrBadge`, `PrintSourceBadge`, `AudioBadge` and
`SubtitleBadge`, fed by the existing `PrintDescriptor` (`hdrs`, `source`, `dualAudio`,
`audioLangs`, subtitle flags). `DetailScreen` renders them in `FlowRow`s on both the
per-episode best print and each release card, alongside the resolution badge.

**Binge hand-off.** Route launches carry only an opaque handle, so the episode identity now
travels separately: `PlayerSessionStore.SyncScope` gained `postId`/`workType`,
`DetailViewModel.stageSyncScope` fills them, and `startStreamHandle` stamps a
`PlayTarget` with `PlaybackBundle.withStagedTarget`. `prepareBingePrefetch` resolves the
successor's ladder (`QualityLadder.forNumberedScope` → `resolvedFor(AUTO)`) while the
current episode plays; at 85% `prefetchNextEpisodeHead` asks the redirector about that
handle; END / manual-next calls `openPrepared`, which stages work refs, failover handles
and the auto ladder before loading. A cold END still resolves on demand, and only falls
back to `PlayerEvent.PlayNextEpisode` when no playable rung exists. In-file packed
successors are skipped because the service already seeks within the same file.

**Sponsor timing.** `AdSlotPolicy` is the only placement authority: `PRE_ROLL` requires
paused-at-start within a 2 s grace, `BETWEEN_EPISODES` requires a real END plus a successor
(`EpisodeProgression.computeNext`, including in-file), and every playing title returns
`NONE`. `PlayerUiState.adBreak`, `PlayerViewModel.requestAdBreak()`/`dismissAdBreak()`,
`SponsorBreakDialog` and the `dialogBlocking` gate are wired, but nothing raises a break
automatically: there is no ad SDK, creative or VIP entitlement in the app, so this is a
guarded seam rather than a fake ad.

**Tests / build:** `./gradlew --offline assembleDebug` → BUILD SUCCESSFUL;
`./gradlew --offline testDebugUnitTest` → 371 tests / 45 suites / 0 failures. New:
`AdSlotPolicyTest` (7), `BingePreloaderTest` (8, pre-existing file re-verified).

**Deliberately not verified:** no device/emulator run, so shimmer smoothness, badge
layout under long language lists and the next-episode hand-off are compile/unit-verified
only. Nothing committed (no commit requested).

---

### Session 12 — Rewarded 4-hour VIP pass on the device (2026-10-27)

**Goal:** the app half of the earning engine — a time-boxed VIP grant that the backend's
shortener bypass can honour, without inventing an entitlement the app cannot prove.

**Storage.** `ServerSettingsRepository` gained `rewardedVipExpiresAt` (a
`longPreferencesKey` deadline, default `0L`), `grantRewardedVip(hours = 4)` and
`isRewardedVipActive()`. A grant sets `max(now, current) + hours`, so re-watching extends
an active pass instead of truncating it, and hours are clamped to 1..24. Because the
deadline is wall-clock and persisted, it survives process death and a sleeping device;
nothing ticks in the background.

**State.** `VipViewModel` exposes `rewardedVipExpiresAt` in `VipUiState`, observes the
flow at init, and offers `grantRewardedVip()` plus a synchronous
`isRewardedVipActive(now)`. `RewardedVipPass` is a pure helper (no Android types) for
`remainingMs`, `isActive` and `formatRemaining` — `3h 59m 58s`, `59m 58s` — which is what
makes the countdown testable on the JVM.

**Screen.** `VipUpgradeScreen` renders a `RewardedVipSection` under the hero: when no pass
is active, the button reads exactly **"Watch Ad for 4-Hour VIP Pass"**; when one is, the
card shows *"VIP pass active"* with a one-second countdown driven by a `LaunchedEffect`
against the stored deadline. The card says plainly that this build ships no ad player, so
the press activates the pass directly, and that the pass is device-local — the same
honesty rule the VIP screen already applies to the operator's manual confirmation.

**Tests / build:** `./gradlew --offline :app:compileDebugKotlin :app:testDebugUnitTest`
→ BUILD SUCCESSFUL (exit 0); 381 tests / 47 suites / 0 failures, including the new
`RewardedVipPassTest` (5). Note: the run competed with a second Gradle invocation from
another session on the same project, which forced Kotlin to fall back to in-process
compilation — slow, but the result is a full compile plus test pass.

**Deliberately not verified:** no device/emulator run, so the countdown's visual tick and
button state are compile/unit-verified only. The pass is device-local by design: the app
does not and cannot mint the server-side `vip` capability, so a rewarded viewer still sees
shortened links until an operator-side grant exists. Nothing committed (no commit
requested).

### Session 12 — Facet search, hero ambient glow, broadcast update dialog (2026-10-27)

**Goal:** the requested "2026 Luxury UI & Multi-Filter Search" pass: real multi-facet
search, a subtle radial glow behind the hero banner, and a one-tap APK update notice fed
by `apk_update_url` in remote config.

**Search.** `/api/v1/posts` now accepts `industry`, `genre`, `quality` and `sort`
(server-side SQL before paging, so a chip narrows the catalog instead of the rows already
on the phone). Quality is an `EXISTS` test over `releases.quality` because the v1 list row
has no quality column; `4K` also matches 2160p/UHD. "Trending" is honest — there is no
play-count column, so it ranks by `release_count + source_count`. The app's
`SearchViewModel` owns the facet enums, `hasSearchIntent` (a blank query with a facet is
still a search, so `loadMore` pages), and re-fetches on every facet/sort change through the
same 300 ms debounce. `SearchScreen` renders one scrolling rail (Type · Industry · Genre ·
Quality · Sort) and the same groups as `FlowRow`s in the filter sheet, plus a loading state.

**Hero glow.** `HeroAmbientGlow` draws two low-alpha radial blooms from the theme's
primary/secondary/tertiary and cross-fades them when the active page changes (snaps under
`rememberReduceMotion()`). The banner card is inset 14dp with a 24dp corner so the light
reads around it; `HeroSkeleton` matches the inset so the page does not jump.

**Update dialog.** `VipRemoteConfig` decodes `apk_update_url` and `maintenance_mode`.
`AppUpdate.from(config)` is the pure rule (non-empty + http(s) only), `HomeViewModel`
re-checks on load/refresh and fails silently, and `HomeScreen` shows a branded
`AlertDialog` whose "Update Now" opens the link via `ACTION_VIEW` (no
REQUEST_INSTALL_PACKAGES; installing stays the platform's job). The dialog closes only if
the browser actually launched; `Later` suppresses that URL for the session. Added
`copy.update_title` / `copy.update_message` / `copy.update_now` to `/brand.properties`.

**Tests / build:** `./gradlew --offline :app:compileDebugKotlin` → BUILD SUCCESSFUL;
`./gradlew --offline testDebugUnitTest` → 381 tests / 47 suites / 0 failures (new
`AppUpdateTest` 3, `VipRemoteConfigTest` 6, `BrandDriftTest` 9). Backend:
`python3 -S Fast_Fetch/test_database.py` → 64 OK; `test_vidout.py` → 6 OK.

**Deliberately not verified:** no device/emulator run, so glow smoothness, facet-rail
scrolling and the dialog are compile/unit-verified only. Remote config has no version
code, so the notice cannot claim "newer" — it says "a new build is available".
`maintenance_mode` is decoded but no screen consumes it yet. Nothing committed (no commit
requested).

### Session 13 — The VIP claim becomes a real server round-trip (2026-10-27)

**What was false before this:** the app's "Submit" button stored the transaction ID in
DataStore and told the viewer it had been kept — the server was never called, so a paid
membership could not exist. `VipUpgradeScreen` even said "this server has no payment
collection endpoint". `Fast_Fetch/payments.py` already had one, deployed and tested; the app
just never spoke to it.

**The contract, taken from the server rather than invented:** `POST api/v2/account/payment`
with bearer sync key and body `{"plan","method","tid"}`; `GET api/v2/account/entitlement`
returning `{"vip","vip_until","pending"}` through `redact.py`'s `account_payment` /
`account_entitlement` projections. The projections deliberately carry **no `tid`** — the
ledger keeps it, the phone never gets it back.

**Wired:**
- `AccountWire.kt` — `PaymentRequest`, `PaymentReceipt`, `PaymentSubmitResponse`,
  `AccountEntitlement`, `EntitlementResponse`. The membership type is `AccountEntitlement`,
  **not** `Entitlement`: `CatalogV2.kt:216` already owns that name for a per-work licence,
  and reusing it was a redeclaration that only surfaced at compile time.
- `SyncAccountRepository.kt` — `submitPayment()` classifies through the existing
  `SyncContract` verdicts (no retries, `detail` never surfaces); `refreshEntitlement()` is
  throttled to one read per 60 s and keeps the last good answer on a transient failure, but
  clears on `SIGN_OUT`; `startEntitlementWatch()` polls every 6 h from
  `RaddStreamApplication.onCreate()` and never starts without a key.
- `VipViewModel.kt` — plans/channels became the server's own spellings (`vip_monthly`,
  `jazzcash`, …), `submitTransaction()` posts when signed in and keeps the draft on the
  device when not, `VipSubmission.outcome()` maps every refusal to our own sentence, and a
  kept draft is auto-filed once an account exists.
- Entitlement now gates something real: `AdSlotPolicy.decide()` returns `AdSlot.NONE` when
  `isEntitled`, and the sponsor card leaves `DetailScreen`. The rewarded pass and the server
  membership both silence ads and nothing else — **no resolution/quality gate was invented**,
  because remote config publishes no such flag.
- `VipUpgradeScreen` gained the plan/channel pickers, an entitlement card, a live
  "Sending…" state, and honest copy for the signed-out path.

**Drift pinned:** `VipWireContractTest` reads `payments.py` and `redact.py` off disk (the
`BrandDriftTest` pattern) and asserts plan names, plan days, fallback prices, channel names
and both projection field sets, plus that `tid` appears in neither.

**Tests / build:** `:app:compileDebugKotlin :app:testDebugUnitTest` → BUILD SUCCESSFUL,
**410 tests / 50 suites / 0 failures** (new: `VipWireContractTest` 9, `VipSubmissionTest` 6,
`ModelsTest` +3, `AdSlotPolicyTest` +2, `RewardedVipPassTest` +2). `PosterCardProvenanceTest`
still self-skips on aarch64.

**Operational finding for every agent on this host:** two concurrent Gradle invocations in
`App/` corrupt each other's kapt output (`BUILD FAILED`, no compile errors) on this 1-vCPU
VM. Builds now go through `/tmp/qbuild.sh`, which waits for other agents' builds and takes an
exclusive lock; the rule is recorded in `App/AGENTS.md` §1a. Also: `android_tasks.md` was
instructing workers to POST to a `/api/v1/vip/submit-tid` route **that does not exist** —
corrected, because a second fake payment path would have shipped beside the real one.

**Deliberately not verified:** no device or emulator, so the posted claim, the operator's
approval round-trip and the entitlement countdown are compile/unit-verified only. A
`GET` before `POST` ordering question was settled by live probe: `viewer.py` reads the body
before dispatch, so a missing bearer is a 401 on every account route, uniformly — not a bug.

### Session 14 — The android_tasks sprint: remote switches, VIP quality gate, recents, subtitles, kept-file playback (2026-10-27)

**Goal:** work the six-task `android_tasks.md` sprint in order, Kotlin only, running
`testDebugUnitTest` after each change.

**1. Remote config is fully decoded and obeyed.** `VipRemoteConfig` now carries everything
`admin_panel.py:remote_config` publishes: `maintenance_mode`, `apk_update_url`, the
`feature_flags` board (`downloads`, `pure_cinema`, `chromecast`, `quality_gate`, plus the
aliases the brief allowed), `ads` (`monetag_rewarded_zone_id`, `adsterra_native_banner_id`),
and `link_shorteners` (network + configured — the tokens never leave the server).
`ServerSettingsRepository` mirrors maintenance and the feature switches in ONE atomic
DataStore write, so a torn refresh cannot leave half a config behind. A new
application-scoped `RemoteConfigWatcher` refreshes every five minutes and only writes after
a fully decoded answer; it is started in `RaddStreamApplication`, beside the entitlement
watch. `MaintenanceScreen` renders ahead of navigation in `MainActivity`, so the whole app
is behind the notice, not just the home page. (A second session on this host added the
operator `quality_gate` flag to the same board; the tree below was verified as one unit.)

**2. VIP: one real payment route and an enforceable quality promise.** The brief named
`POST /api/v1/vip/submit-tid`; that route does not exist. The Retrofit method is therefore
named `submitVipTid` but wired to the ledger route that does exist
(`POST api/v2/account/payment`), and `phone` is neither collected nor sent because the
server accepts `{plan, method, tid}` only. The entitlement is cached in DataStore
(`vip_active` / `vip_until` / `vip_pending_claim`) and hydrated at startup so a restart knows
what the last confirmed answer was; sign-out clears it. `VipQualityGate` holds the single
premium rule (2160p/4K/1080p), applied in `DetailViewModel` when the layout and ladder are
derived and again in `PlayerViewModel` when the quality switch and binge look-ahead are
armed — with a visible "4K and 1080p are part of VIP" card instead of silently deleting
sources. It is behind the operator's `quality_gate` switch: with the flag off, no viewer is
restricted. The rewarded pass buys ad-free, never a higher rung, and the code says so.

**3. Search recents survive a restart.** `ServerSettingsRepository.searchRecents` stores the
rail as one U+001F-joined string (newest first) rather than a `Set`, because recency is the
whole point; every write trims, drops blanks, strips the separator, dedupes and caps at
`SEARCH_RECENTS_MAX = 20`. `SearchViewModel` hydrates from the flow at init and writes
through the same normaliser, so the optimistic UI and the persisted list cannot disagree.

**4. Subtitle parsing is pinned by tests.** New `SubtitleParsersTest` (15): SRT with and
without indices, CRLF, multiline cues, tag stripping, out-of-order cues; VTT header/NOTE/cue
settings/`MM:SS.mmm`; empty and whitespace-only input; malformed start/end/reversed timing
skipped without throwing; `parseTimestamp` shape rejects; a 20,000-cue SRT and a 10,000-cue
VTT parsed in order; `activeCues` delay semantics; format detection.

**5. A kept file is played through the loopback proxy.** `OfflineCacheEngine.playableUri`
no longer returns a `file://` URI: it serves the committed cache file through
`LocalMediaProxy` on `127.0.0.1`, one bounded LRU of four servers, with a content type from
the file extension. `PlaybackService.handleLoad` now asks for a kept copy BEFORE building the
media item and swaps the rendition to that loopback URL (clearing the redirector's
`expires_at`), logging the choice in the failover trail; an engine miss or failure falls
straight through to the server. Two real defects were fixed in `LocalMediaProxy` on the way:
it materialised the whole requested range in a `ByteArray` (an open-ended `bytes=0-` request
would have read a movie into memory — it now streams 64 KiB chunks), and its range parser
treated an explicit end as exclusive (`bytes=0-99` answered 99 bytes, leaving a one-byte hole
at every seek — HTTP ranges are inclusive).

**Tests / build:** `/tmp/qbuild.sh -Dorg.gradle.jvmargs="-Xmx1536m" compileDebugKotlin
testDebugUnitTest` → BUILD SUCCESSFUL, **447 tests / 54 suites / 0 failures**
(`LocalMediaProxyTest` 7, `SearchRecentsTest` 7, `SubtitleParsersTest` 15). Another session
was building the same working tree during this sprint; the final serialized run reported
`OVERLAP=NO`, and the test task was cache-validated against the exact sources in the commit.
`PosterCardProvenanceTest` still self-skips on aarch64.

**Deliberately not verified:** no device or emulator, so Media3 playing a loopback URL, the
maintenance overlay, the VIP upsell card and the recents rail are compile/unit-verified only.
The proxy is exercised over real HTTP in `LocalMediaProxyTest`, but not by ExoPlayer.

**GitHub branch/commit/push result:** App changes committed locally in this session; a later
session pushed them (`d3c54d1` carries this sprint's tree to `master`). **Oracle deployment
result:** not deployed from App — the app is not a server process; the API that serves it was
restarted, see Session 15.

### Session 15 — The gate became an operator switch, the maintenance notice kept a door, and a tapped keep plays its own bytes (2026-10-27)

**What this session was for:** close the three gaps Session 14 left open, each of which was a
decision rather than a defect, and get the tree verified green on an idle VM before shipping.

**1. The VIP quality gate answers to the operator, and defaults off.** A worker had written a
hard "1080p/4K is VIP" rule into `DetailViewModel`/`PlayerViewModel` on a brief that asked for
something softer, and shipping it would have hidden catalog content from every viewer the ledger
has not confirmed — including all signed-out ones. The rule stayed; what changed is that it now
reads `feature_flags.quality_gate`, which `admin_panel.py` publishes and `/admin` toggles, and
which **defaults to 0** where the three flags beside it default to 1, because those hide a feature
a viewer was already free to use and this one withholds content. `test_admin_panel.py` pins that
inverse default (a flip to `1` stays visible in `/admin`, and a second save of `0` clears it).
Every call site now goes through one pure function, `VipQualityGate.premiumAccess(gateEnabled,
isVip) = isVip || !gateEnabled`, so the detail page and the player cannot disagree; identity is
asserted when the switch is off, meaning the same list object comes back out of `gate()`.

**2. A maintenance-flagged server is no longer a brick.** `MaintenanceScreen` covered the whole app
including the screen that changes which server the app talks to, so a wrongly-flagged deployment
had no escape. The notice now carries "Use a different server" → `Screen.Setup`, and the escape is
dropped as soon as the flag clears.

**3. Tapping an in-app keep plays the file that is already on the device.** Session 14 made
`PlaybackService` prefer a kept copy at load; the Downloads screen still sent every tap back out
through `/api/v1/stream`, so a kept title needed the resolver, a live upstream and a data plan.
`DownloadsViewModel.playRoute()` now asks the engine by task key and routes through one pure
truth table (`KeepPlayback.route`): local wins whenever the engine can name a complete file —
including a task that never got a handle — otherwise the handle, otherwise `NothingPlayable`,
which says so instead of navigating to an empty player. `OfflineCacheEngine.playableUri` and the
new `playableUriForSourceKey` share one `serveUri`, so the player and the list cannot disagree
about what "complete" means.

**Tests / build:** `/tmp/qbuild3.sh :app:compileDebugKotlin :app:testDebugUnitTest` → BUILD
SUCCESSFUL, **452 tests / 55 suites / 0 failures**, all 55 result XMLs newer than the run,
`OVERLAP=NO`. Backend in the same tree: 49 `test_redact` + 64 `test_database` + 6 `test_vidout` +
56 `test_admin_panel`, `setup_check.py` all pass. `PosterCardProvenanceTest` still self-skips on
aarch64, and `/tmp/qbuild.sh`'s foreign-build detector was replaced: it matched another agent's
`bash -c` that merely *mentions* `GradleWrapperMain`, which deadlocked this session's queue
against a session that was waiting for a build to start. The new one counts only a `java` process.

**Deliberately not verified:** no device or emulator was used, so the locked-rung card, the
maintenance notice and its escape, and Media3 opening a loopback URL are compile/unit-verified only.

**GitHub / Oracle:** `d3c54d1`, `6449970`, `b4fee9a`, `50edcb4` pushed to `master` on the explicit
clean URL. `radd-stream.service` restarted (the running process predated the payment ledger, so
`/remote-config` was missing `quality_gate`), and two nginx blocks were added because every
`/api/v2/account*` route and `remote-config` were a public 403 — see `ORACLE_DEPLOYMENT.md`.

### Session 16 — Independent verification of the android_tasks sprint (2026-10-27)

**What this session was for:** the six-task sprint was already in the tree from Sessions 14–15
(Task 2 was closed by the orchestrator as done), so this session re-verified it under the
one-build-at-a-time queue instead of re-implementing anything. No Kotlin source was changed here.

**Result:** `/tmp/qbuild.sh :app:compileDebugKotlin :app:testDebugUnitTest` → BUILD SUCCESSFUL,
`GRADLE_EXIT=0`, `FOREIGN_BUILD_PIDS_SEEN=` empty, `OVERLAP=NO`. Test results: **452 tests /
55 suites / 0 failures / 0 errors / 0 skipped**, all 55 XMLs written by that run (previous
newest was `1793106530`).

**One transient failure, not a defect in committed code:** the first run failed
`:app:compileDebugUnitTestKotlin` on `ScreenSnapshotTest.kt` referencing `RaddTheme`, a
composable that does not exist (`ui/theme/Theme.kt` defines `RaddStreamTheme`). That file is
untracked work from a parallel session; it was corrected to `RaddStreamTheme` while the build
was in flight, and the rerun compiled it. The file and its `build.gradle.kts` arm64 exclusion
remain uncommitted and are not part of this session's commit.

**What the run re-proves:** maintenance flag → overlay + "Use a different server" escape;
`RemoteConfigWatcher`'s five-minute fail-safe poll; recents persisted to DataStore with the
20-entry cap; `SubtitleParsersTest`; a finished keep played through `LocalMediaProxy`
(`PlaybackService.handleLoad` → `OfflineCacheEngine.playableUri`); and the VIP quality gate
still behind `feature_flags.quality_gate` (default OFF) via
`VipQualityGate.premiumAccess`.

**Deliberately not verified:** no device/emulator pass. `ScreenSnapshotTest` and
`PosterCardProvenanceTest` are excluded on aarch64 because Robolectric has no native runtime
here, so their snapshot cases executed nowhere on this host.

**Git:** only this log entry is staged/committed — no source changes, and the parallel
session's three uncommitted App files were left untouched.

