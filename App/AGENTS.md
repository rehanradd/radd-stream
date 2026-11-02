# 🤖 AGENTS.md — Android App Guide for AI Agents

> **READ THIS ENTIRE FILE before making any changes to the App** — the authoritative guide for the
> RADD Stream Android app. Read the root [`AGENTS.md`](../AGENTS.md) for project-wide context.

---

## 0. One-Line Summary

> A native Kotlin/Compose Android client for a `radd-stream` server. Verified in `App/app/src`, the
> surface covers server setup, catalog browsing, search, favorites, a detail screen, and Media3
> playback via the stream resolver. Device/CI verification is pending — §5 and §6 give the exact
> API contract and the known broken spots.---

## 1. Critical Constraint — No Local Android Studio

The user has no powerful PC and cannot run Android Studio; the **entire build pipeline runs on GitHub Actions** (free Ubuntu runners) — you push, GitHub builds the APK.

**Never tell the user to:** open Android Studio; run `gradlew` locally; install the Android SDK locally; connect a device with ADB (they can sideload the APK manually).

**Always use:** GitHub Actions for builds, GitHub Releases for APK distribution, GitHub web editor / Codespaces / Replit for code editing.

### 1a. Correction: builds DO happen on this VM, one at a time

The rule above is stale in both directions since 2026-10-29: GitHub Actions is **enabled and
running** (API-measured: three root workflows active, 42 runs, `backend-ci.yml`
**green at `64c0b1b`** on both refs). Android `ci.yml` is red, so a **local** offline Gradle run is
still the fast verification loop on the Oracle host and how every milestone since was proven — CI
is now a second opinion, not an unavailable gate. Local builds are also how agents break each
other's work: this VM has **one vCPU**, and two concurrent Gradle invocations into the same
`App/app/build` tree fail BOTH (`kaptDebugKotlin` aborts with `Unable to delete directory
.../generated/source/kapt` — a lock race, not a code error).

On this host:

- **Never run `./gradlew` directly.** Use the queue — it waits for any other agent's build, then
  takes an exclusive lock: `/tmp/qbuild.sh :app:compileDebugKotlin :app:testDebugUnitTest`
- Read the `GRADLE_EXIT=` line it prints, not your pipeline's status (`... | tail` reports
  `tail`'s exit, always 0).
- Never read `app/build/test-results/**` as passing unless newer than your run — a stale XML looks
  identical to a green one.
- One build at a time, and no build while another agent is mid-verification. Fan-out workers:
  edit freely, build rarely — each build is minutes of this VM's entire CPU.

> The nine arm64-excluded Robolectric tests — why excluded here, what the hosted runner proved —
> moved to [`../docs/SPEC_APP_ROBOLECTRIC_ARM64.md`](../docs/SPEC_APP_ROBOLECTRIC_ARM64.md). The
> exclusion stays: no number printed on this host includes those two suites.

---

## 2. Build System Architecture

The CI pipeline diagram moved to
[`../docs/SPEC_APP_BUILD_ARCHITECTURE.md`](../docs/SPEC_APP_BUILD_ARCHITECTURE.md). What stays law is §1a (one build at
a time, through this host's queue) and §13.

---

## 3. Technology Stack (Current Android Direction)

| Layer | Technology | Why |
|---|---|---|
| Language | **Kotlin** | Coroutines, type safety, Google's #1 language |
| UI | **Jetpack Compose** | Declarative, Material 3, hot-reload in Codespaces |
| Media playback | **ExoPlayer / Media3** | `PlayerScreen.kt` + `PlaybackService.kt`, wired into `NavGraph.kt`; never run on a device |
| Architecture | **MVVM + Repository + Hilt** | Testable, industry standard |
| Networking | **Retrofit 2 + OkHttp** | Type-safe calls to the radd-stream backend |
| Local DB | **Room** | Watchlist, continue watching, cached catalog |
| Images | **Coil** | Compose-aware poster image cache |
| DI | **Hilt (Dagger)** | Automatic ViewModel injection |
| Navigation | **Jetpack Navigation Compose** | Type-safe, deep links |
| Settings | **DataStore Preferences** | Server URL, preferences |
| Build | **Gradle Kotlin DSL** (`build.gradle.kts`) | Type-safe |

> Keep this app in Kotlin/Compose for the current milestone; Flutter can be reconsidered later —
> do not migrate without an explicit project decision.
> ❌ Do NOT introduce: React Native, Java, Glide, Volley, RxJava, Koin

---

## 4. Current Source Folder Structure

The tree inventory moved to [`../docs/SPEC_APP_SOURCE_LAYOUT.md`](../docs/SPEC_APP_SOURCE_LAYOUT.md).
`find App/app/src -name '*.kt' | wc -l` is the only honest count of what exists.

---

## 6. Screens Reference

The per-screen inventory moved to [`../docs/SPEC_APP_SCREENS.md`](../docs/SPEC_APP_SCREENS.md); the
wireframes stay in [`design/SCREENS.md`](design/SCREENS.md), and
`app/src/main/kotlin/com/raddstream/app/ui/` is the source of truth over both.

---

## 7. Design System Quick Reference

The token dump moved to [`../docs/SPEC_APP_DESIGN_QUICKREF.md`](../docs/SPEC_APP_DESIGN_QUICKREF.md).
[`design/DESIGN_SYSTEM.md`](design/DESIGN_SYSTEM.md) is the spec — read it, not a summary.

---

## 8. Phase Roadmap

⚠️ **Reality (`App/app/src`, 2026-10-22):** the "Deferred" labels on Phase 2
detail/playback/watchlist/settings no longer match the source — those screens, the Room favorites
DB, and `PlaybackService` all exist and are wired into `NavGraph.kt`. What is missing is
verification, not implementation.

| Phase | What to build | Status |
|---|---|---|
| **Phase 0** | Gradle project skeleton + CI | ✅ Complete |
| **Phase 1** | Server setup → metadata catalog → search | 🚧 Implemented; CI/device verification pending |
| **Phase 2** | Detail pages, playback, watchlist, settings | 🚧 Code implemented; unverified; the season/episode + `is_temporary` model mismatches in §6 block correct series playback |
| **Phase 3** | Chromecast, multi-server, Android TV | ⏳ Future |

---

## 10. Signing Configuration

This section previously printed a sample `app/build.gradle.kts` does not contain:
`android.util.Base64.decode(...)` is an **Android runtime API, not on the Gradle classpath**, so
that block could never have configured a build. What actually runs
(`App/app/build.gradle.kts:110-126`, verified at `a51c0c4`):

```kotlin
signingConfigs {
    create("release") {
        val keystoreBase64 = System.getenv("KEYSTORE_BASE64") ?: ""
        val storePassword  = System.getenv("KEY_STORE_PASSWORD") ?: ""
        val keyAlias       = System.getenv("KEY_ALIAS") ?: ""
        val keyPassword    = System.getenv("KEY_PASSWORD") ?: ""

        if (keystoreBase64.isNotEmpty() && storePassword.isNotEmpty()) {
            val keystoreFile = File(layout.buildDirectory.asFile.get(), "radd-release.jks")
            keystoreFile.parentFile?.mkdirs()
            keystoreFile.writeBytes(Base64.getDecoder().decode(keystoreBase64))  // java.util, imported at :3
            storeFile = keystoreFile
            this.storePassword = storePassword
            this.keyAlias = keyAlias
            this.keyPassword = keyPassword
        }
    }
}
```

Two consequences to know before spending a release run:

- Applied **only when both** `KEYSTORE_BASE64` and `KEY_STORE_PASSWORD` are non-empty; the keystore
  is written under `app/build/`, never the source tree, never committed.
- `Base64.getDecoder()` is the strict **basic** codec: no line breaks, and a value whose length is
  not a whole base64 quantum throws. Measured:
  `java.lang.IllegalArgumentException: Last unit does not have enough valid bits` at
  `build.gradle.kts:120`, `BUILD FAILED in 4s` — it dies during **configuration**, before any Kotlin
  compiles, so no compile or lint error is reached. That exception is the *stored secret* being
  malformed, not this code: the VM's keystore re-encodes cleanly
  (`/home/ubuntu/raddstream-release.jks`, 2,752 bytes → 3,672 base64 chars ending `==`, strict
  round-trip OK). **Fix it by re-entering the secret, not by editing this block** —
  `getMimeDecoder()` would silently accept a truncated keystore instead of refusing it.

**One-time keystore generation** (GitHub Codespaces terminal — no local install):
```bash
# Codespaces terminal:
keytool -genkey -v \
  -keystore radd-release-key.jks \
  -keyalg RSA -keysize 2048 \
  -validity 10000 \
  -alias radd-key \
  -dname "CN=RADD Stream, O=RADD, C=US"

# Encode for the Secret:
base64 -w 0 radd-release-key.jks

# GitHub: Settings → Secrets → Actions:
#   KEYSTORE_BASE64 = (paste output above)
#   KEY_STORE_PASSWORD = (the password you chose)
#   KEY_ALIAS = raddstream
#   KEY_PASSWORD = (the key password you chose)
```

> **Status (measured 2026-10-30):** all 4 release signing secrets are active in GitHub Actions
> Secrets; the keystore is backed up on the Oracle VM at `/home/ubuntu/raddstream-release.jks`.
> A `v*.*.*` tag triggers `.github/workflows/release.yml`: build, sign, verify, publish APKs + AABs.

---

## 11. Git and Credential Safety

Use the repository's Git workflow; do not use GitHub's Contents API to write files one at a time. Never put a GitHub token in source, shell arguments, a checked-in
script, chat, or logs. Authenticate through the workspace's secret-backed Git credential flow;
never persist the token in the repository.

### Oracle backend connection

- The brand's primary address is `https://raddstream.duckdns.org`; the session fallback is
  `http://92.4.95.252`; SSH is `ubuntu@92.4.95.252:22` — see the secret-safe process in
  [`../ORACLE_DEPLOYMENT.md`](../ORACLE_DEPLOYMENT.md).
- The app calls `/api/v1/stats`, `/api/v1/posts`, `/api/v1/posts/{id}`, `/api/v1/stream` (§5);
  not `/api/v1/rules`.
- Cleartext is permitted per named host only, never globally: do not relax Android network security
  to make a release work over HTTP.
  ⚠️ **Reality (TLS measured 2026-11-02; code re-verified against `viewer.py`/`redact.py`
  2026-10-30):** the catalog answers `200` over https on `raddstream.duckdns.org` (Let's Encrypt,
  to 2027-01-31) **and** over plain HTTP on the IP — so the brand ships the TLS name as default and
  the plain IP as a fallback a session uses, never saves. The catalog routes take no API key or
  session; nothing behind them is private. Two
  claims this bullet used to make are now false of the code and must not be repeated: no wildcard
  CORS (`CORS_ALLOW_ORIGINS` is an empty `frozenset`; a refused origin gets no header) and no
  un-throttled API (`_public_gate()` returns 429 with `Retry-After` and the `RateLimit-*` triple —
  honour 429 instead of retrying immediately).
- The user's permanent choice: `ORACLE_SSH_KEY` and `GITHUB_TOKEN` are Replit Configurations
  environment variables, not Secrets. Verify presence by name only; never reveal values, ask to
  move them, or put either in the APK, Actions logs/artifacts, or Oracle environment.
- GitHub Actions discovers workflows only from the repo-root `.github/workflows/`;
  `App/.github/workflows/` files are not discovered.

---

## 13. Critical Rules for App Agents

1. **No local Android Studio** — GitHub Actions is the build environment
2. **Kotlin only** — no Java files
3. **Compose only** — no XML layouts
4. **Every screen is a Composable function** — no Activities except MainActivity
5. **All API calls via Retrofit + coroutines** — no raw `HttpURLConnection` in UI
6. **All state via StateFlow/ViewModel** — no mutable state in Composables directly
7. **Test every network model** — a JSON deserialization test per new data class
8. **Keep APK under 15 MB** — no bundled video assets; lazy-load everything
9. **Minimum SDK 21** — guard anything below API 21 with Build.VERSION_CODES
10. **Always update this AGENTS.md** with your session log before ending

---

## Moved out (reference prose, verbatim)

- 5. REST API Contract (Verified Against viewer.py) → [`../docs/SPEC_APP_API_CONTRACT.md`](../docs/SPEC_APP_API_CONTRACT.md) (214 lines) — endpoint contract
- 9. Phase 0 Implementation Notes (Historical) → [`../docs/SPEC_APP_PHASE0_NOTES.md`](../docs/SPEC_APP_PHASE0_NOTES.md) (74 lines)
- 12. Session Log — Append Here → [`docs/SESSION_HISTORY.md`](docs/SESSION_HISTORY.md) (19 lines) — session log
- 14. Session Log → [`docs/SESSION_HISTORY.md`](docs/SESSION_HISTORY.md) (235 lines) — session log (cont.)
- 15. Re-Skinning From ONE File (`/brand.properties`) → [`../docs/SPEC_APP_RESKIN_BRAND_PROPERTIES.md`](../docs/SPEC_APP_RESKIN_BRAND_PROPERTIES.md) (1686 lines) — re-skin reference
- 1a. The nine arm64-excluded Robolectric tests → [`../docs/SPEC_APP_ROBOLECTRIC_ARM64.md`](../docs/SPEC_APP_ROBOLECTRIC_ARM64.md)
- 2. Build System Architecture → [`../docs/SPEC_APP_BUILD_ARCHITECTURE.md`](../docs/SPEC_APP_BUILD_ARCHITECTURE.md)
- 4. Current Source Folder Structure → [`../docs/SPEC_APP_SOURCE_LAYOUT.md`](../docs/SPEC_APP_SOURCE_LAYOUT.md)
- 6. Screens Reference → [`../docs/SPEC_APP_SCREENS.md`](../docs/SPEC_APP_SCREENS.md)
- 7. Design System Quick Reference → [`../docs/SPEC_APP_DESIGN_QUICKREF.md`](../docs/SPEC_APP_DESIGN_QUICKREF.md)

### Gating-lane note — APK builds moved to GitHub Actions, permanently (2026-11-01)

**Owner order, standing:** every APK build happens on GitHub Actions. No agent on this VM runs
`./gradlew` — not `assembleDebug`, not `testDebugUnitTest`, not `lintDebug` — unless the owner
reopens local builds. This one-vCPU box serves the live API; a Gradle daemon is exactly
what the Session 28 and 31 load holds were written to prevent. The App gate is now a **hosted
run**: read `App/**`'s `ci.yml` result and step count, not a local XML.

**How to get an artifact without any secret:** push a branch that touches `App/**`.
`ci.yml` (`🔨 CI — Android Build & Test`) runs `:app:assembleDebug :app:testDebugUnitTest
:app:lintDebug` and uploads the **debug APK** on a green run — debug-signed, installable, needing
none of the four keystore variables. Debug's
`App/app/src/debug/res/xml/network_security_config.xml` permits cleartext to whatever machine the
developer aims at, while a **release** build reads
`brand.properties:215 network.release_cleartext_for_default_host=false` and so speaks plain HTTP
only to the loopback/emulator names plus `network.fallback_server_url`, and reaches the TLS default
over https. Never a wildcard, never a global switch.

**How to get a signed release:** push a `v*.*.*` tag → `release.yml`. It needs
`KEYSTORE_BASE64`, `KEY_STORE_PASSWORD`, `KEY_ALIAS`, `KEY_PASSWORD`. Measured cause of every
release failure so far, recorded in the `signingConfigs` block itself: the stored
`KEYSTORE_BASE64` is **malformed** — the strict-decode failure measured in §10; the tolerant MIME
decoder throws identically on the same input, so this is a corrupt secret value, not a Gradle bug. The block now refuses
*before* signing, printing only the value's shape (length, index, code point, decoded byte count,
keystore alias count) and never its contents. The correct export is `base64 -w 0 <keystore-file>`
pasted straight into Settings → Secrets and variables → Actions, replacing the stored value.
