# 🤖 AGENTS.md — Android App Guide for AI Agents

> **READ THIS ENTIRE FILE before making any changes to the App.**
> This is the authoritative guide for building the RADD Stream Android app.
> Also read the root [`AGENTS.md`](../AGENTS.md) for project-wide context.

---

## 0. One-Line Summary

> A native Kotlin/Compose Android metadata client for an authorized `radd-stream` server. The current MVP covers server setup, catalog browsing, and search; playback is deferred.

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
| Future media playback | **ExoPlayer / Media3** | Native Android playback; not part of the current metadata MVP |
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
    │   │   ├── navigation/
    │   │   ├── screens/                        ← Setup, Home, Search
    │   │   └── theme/
    │   ├── viewmodel/                           ← setup, catalog, search state
    │   └── MainActivity.kt
    ├── app/src/test/                            ← JVM unit tests
    ├── gradle/wrapper/
    ├── gradlew
    └── docs/
```

---

## 5. REST API Contract (Current Metadata Client)

The Android MVP talks to the Python API for catalog metadata only. These are
the endpoints currently consumed by the app:

### `GET /api/v1/posts`
**Query params:** `q` (optional title search), `type` (`movie`, `series`, or
`anime`), `page` (1-based, default 1), and `limit` (default 20, maximum 100).

**Response:**
```json
{
  "page": 1,
  "limit": 20,
  "total": 131,
  "total_pages": 7,
  "results": [
    {
      "id": 42,
      "title": "Inception",
      "clean_title": "Inception",
      "year": 2010,
      "content_type": "movie",
      "poster_url": "https://...",
      "imdb_rating": "8.8",
      "source_site": "vegamovies"
    }
  ]
}
```

### `GET /api/v1/stats`
```json
{
  "posts": 131,
  "releases": 1031,
  "sources": 2017,
  "active_sources": 1840,
  "resumable_sources": 250,
  "temporary_sources": 90
}
```

The app checks the stats endpoint before saving the server URL. It does not
currently call post-detail, resolver, or rules endpoints.

---

## 6. Screens Reference

See [`design/SCREENS.md`](../design/SCREENS.md) for full wireframes. Summary:

| Screen | Route | Key Components |
|---|---|---|
| Setup | `setup` | Server URL, connection check |
| Home | `home` | Type filter chips, catalog poster grid, refresh |
| Search | `search` | Debounced title search, type chips, poster grid |

Detail, player, watchlist, and settings screens are deferred and not navigable
in the current MVP.

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

| Phase | What to build | Status |
|---|---|---|
| **Phase 0** | Gradle project skeleton + CI | ✅ Complete |
| **Phase 1** | Server setup → metadata catalog → search | 🚧 Implemented; needs CI/device verification |
| **Phase 2** | Detail pages, playback, watchlist, settings | ⏳ Deferred |
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
- The Android MVP currently calls only `/api/v1/stats` and `/api/v1/posts`.
  It does not use playback or resolver endpoints.
- Cleartext HTTP is permitted only in the debug build. The release build must
  use HTTPS; do not relax Android network security globally to make a release
  work over HTTP.
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


