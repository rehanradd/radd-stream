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

The rule above is stale as written in one direction and stale in the other since 2026-10-29:
GitHub Actions is **enabled and running** (measured through the API — all three root workflows are
active, 42 runs recorded, and `backend-ci.yml` is **green at `64c0b1b`** on both refs). The Android `ci.yml`
job is red, so a **local** offline Gradle run is still the fast verification loop on the Oracle
host and is how every milestone since has been proven — a CI check is now a second opinion
available to everyone, not an unavailable gate. Local builds are also how agents break each
other's work: this VM has **one vCPU**, and two concurrent Gradle invocations writing into the
same `App/app/build` tree fail BOTH of them (`kaptDebugKotlin` aborts with
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

> The nine arm64-excluded Robolectric tests, why they are excluded here and what the hosted
> runner proved about them, moved to
> [`../docs/SPEC_APP_ROBOLECTRIC_ARM64.md`](../docs/SPEC_APP_ROBOLECTRIC_ARM64.md). The exclusion
> stays: no number printed on this host includes those two suites.

---

## 2. Build System Architecture

The CI pipeline diagram moved to
[`../docs/SPEC_APP_BUILD_ARCHITECTURE.md`](../docs/SPEC_APP_BUILD_ARCHITECTURE.md). What stays law
is §1a (one build at a time, through this host's queue) and §13.

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

The tree inventory moved to
[`../docs/SPEC_APP_SOURCE_LAYOUT.md`](../docs/SPEC_APP_SOURCE_LAYOUT.md).
`find App/app/src -name '*.kt' | wc -l` is the only honest count of what exists today.

---

## 6. Screens Reference

The per-screen inventory moved to [`../docs/SPEC_APP_SCREENS.md`](../docs/SPEC_APP_SCREENS.md);
the wireframes stay in [`design/SCREENS.md`](design/SCREENS.md), and
`app/src/main/kotlin/com/raddstream/app/ui/` is the source of truth over both.

---

## 7. Design System Quick Reference

The token dump moved to
[`../docs/SPEC_APP_DESIGN_QUICKREF.md`](../docs/SPEC_APP_DESIGN_QUICKREF.md).
[`design/DESIGN_SYSTEM.md`](design/DESIGN_SYSTEM.md) is the spec — read that, not a summary.

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


## Moved out (reference prose, verbatim)

- 5. REST API Contract (Verified Against viewer.py) → [`../docs/SPEC_APP_API_CONTRACT.md`](../docs/SPEC_APP_API_CONTRACT.md) (214 lines) — the endpoint contract, field by field
- 9. Phase 0 Implementation Notes (Historical) → [`../docs/SPEC_APP_PHASE0_NOTES.md`](../docs/SPEC_APP_PHASE0_NOTES.md) (74 lines) — historical implementation notes
- 12. Session Log — Append Here → [`docs/SESSION_HISTORY.md`](docs/SESSION_HISTORY.md) (19 lines) — app session log
- 14. Session Log → [`docs/SESSION_HISTORY.md`](docs/SESSION_HISTORY.md) (235 lines) — app session log, second half
- 15. Re-Skinning The Product From ONE File (`/brand.properties`) → [`../docs/SPEC_APP_RESKIN_BRAND_PROPERTIES.md`](../docs/SPEC_APP_RESKIN_BRAND_PROPERTIES.md) (1686 lines) — the one-file re-skin reference
- 1a. The nine arm64-excluded Robolectric tests → [`../docs/SPEC_APP_ROBOLECTRIC_ARM64.md`](../docs/SPEC_APP_ROBOLECTRIC_ARM64.md)
- 2. Build System Architecture → [`../docs/SPEC_APP_BUILD_ARCHITECTURE.md`](../docs/SPEC_APP_BUILD_ARCHITECTURE.md)
- 4. Current Source Folder Structure → [`../docs/SPEC_APP_SOURCE_LAYOUT.md`](../docs/SPEC_APP_SOURCE_LAYOUT.md)
- 6. Screens Reference → [`../docs/SPEC_APP_SCREENS.md`](../docs/SPEC_APP_SCREENS.md)
- 7. Design System Quick Reference → [`../docs/SPEC_APP_DESIGN_QUICKREF.md`](../docs/SPEC_APP_DESIGN_QUICKREF.md)
