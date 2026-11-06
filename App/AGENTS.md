# 🤖 AGENTS.md — Android App Guide for AI Agents

> **READ THIS ENTIRE FILE before making any changes to the App** — the authoritative guide for the
> RADD Stream Android app. Read the root [`AGENTS.md`](../AGENTS.md) for project-wide context.

---

## 0. One-Line Summary

> A native Kotlin/Compose Android client for a `radd-stream` server. Verified in `App/app/src`, the
> surface covers server setup, catalog browsing, search, favorites, a detail screen, and Media3
> playback via the stream resolver. Device verification is pending; CI is green on the panel
> branch (run ids in `App/docs/SESSION_HISTORY.md`) — §5 and §6 give the exact API contract and
> the known broken spots.---

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
| **Phase 2** | Detail pages, playback, watchlist, settings | 🚧 Code implemented; device verification pending (the old season/episode + `is_temporary` model mismatch that used to block series playback was fixed in code — series play through the player now) |
| **Phase 3** | Chromecast, multi-server, Android TV | ⏳ Future |

---

## 10. Signing Configuration

The sample `signingConfigs` block, the one-time keystore generation, and the retired failure history
rotated out 2026-11-05 to [`../docs/SPEC_APP_SIGNING_RUNBOOK.md`](../docs/SPEC_APP_SIGNING_RUNBOOK.md)
under this file's byte ceiling. The law stays here:

- Release signing reads `KEYSTORE_BASE64`, `KEY_STORE_PASSWORD`, `KEY_ALIAS`, `KEY_PASSWORD`, is
  applied **only when** the first two are non-empty, and writes the keystore under `app/build/` —
  never the source tree, never committed.
- `Base64.getDecoder()` is the strict **basic** codec: no line breaks, and a value whose length is
  not a whole quantum throws. That refusal is the feature — `getMimeDecoder()` would silently accept
  a truncated keystore. **Fix a decode failure by re-entering the secret, never by editing the block.**
- **Measured 2026-11-05, unauthenticated public API: signing works.** Release `v1.0.4` is public with
  `radd-stream-1.0.4.apk`, `radd-stream-1.0.4.aab`, `radd-stream-1.0.4-SHA256SUMS.txt`; tags
  `v1.0.0`–`v1.0.4` exist; the publishing run is `41323174024` (`completed success`). Runs 1–7 of
  `release.yml` failed on the malformed secret — the state every older sentence in the guides
  describes. Those sentences are retired in place, not rewritten.
- **No agent may create, move, or delete a tag.** A `v*.*.*` tag triggers `release.yml`; cutting one
  is the owner's call, not a build step.
---

## 11. Git and Credential Safety

Use the repository's Git workflow; do not use GitHub's Contents API to write files one at a time. Never put a GitHub token in source, shell arguments, a checked-in
script, chat, or logs. Authenticate through the workspace's secret-backed Git credential flow;
never persist the token in the repository.

### Oracle backend connection

- The configured backend host is `http://92.4.95.252/` over plain HTTP; the SSH account is
  `ubuntu@92.4.95.252` on port 22. Use the secret-safe process in
  [`../ORACLE_DEPLOYMENT.md`](../ORACLE_DEPLOYMENT.md).
- The app calls `/api/v1/stats`, `/api/v1/posts`, `/api/v1/posts/{id}`, `/api/v1/stream` (§5);
  not `/api/v1/rules`.
- Cleartext HTTP is debug-build only; the release build must use HTTPS — do not relax Android
  network security globally to make a release work over HTTP.
  ⚠️ **Reality (re-verified against `viewer.py`/`redact.py` 2026-10-30):** the backend has no TLS
  at all and the host is plain HTTP, so a release build cannot legally point at
  `http://92.4.95.252/` — a deployment gap, not something to paper over by loosening network
  security. The catalog routes take no API key or session; nothing behind them is private. Two
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
10. **Session logs go in `App/docs/SESSION_HISTORY.md`, never in this file** — this file is
    instructions-only and is auto-loaded into every agent's context. (An older line here said
    to update this AGENTS.md with the session log; that line is retired by the root rule.)
11. **`vectorResource` is qualified, never top-level** — in this Compose version (BOM 2024.06.00)
    there is no top-level `androidx.compose.ui.res.vectorResource`; always call
    `ImageVector.vectorResource(id)` with `import androidx.compose.ui.graphics.vector.ImageVector`.

---

## Moved out (reference prose, verbatim)

- 5. REST API Contract (Verified Against viewer.py) → [`../docs/SPEC_APP_API_CONTRACT.md`](../docs/SPEC_APP_API_CONTRACT.md) (214 lines) — endpoint contract
- 9. Phase 0 Implementation Notes (Historical) → [`../docs/SPEC_APP_PHASE0_NOTES.md`](../docs/SPEC_APP_PHASE0_NOTES.md) (74 lines)
- 10. Signing Configuration (the sample block, the decode diagnosis, the failed runs) → [`../docs/SPEC_APP_SIGNING_RUNBOOK.md`](../docs/SPEC_APP_SIGNING_RUNBOOK.md) (80 lines) — signing runbook
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
none of the four keystore variables, and the only build that can talk to the deployed host:
`App/app/src/debug/res/xml/network_security_config.xml` sets
`cleartextTrafficPermitted="true"`, while a **release** build reads
`brand.properties:199 network.release_cleartext_for_default_host=false`, so a signed release APK
cannot reach `http://92.4.95.252` over plain HTTP at all — a deployment fact about what is
testable, not a reason to loosen release policy.

**How to get a signed release:** push a `v*.*.*` tag → `release.yml`. It needs
`KEYSTORE_BASE64`, `KEY_STORE_PASSWORD`, `KEY_ALIAS`, `KEY_PASSWORD`, **and it works**: `v1.0.4` is
public with APK + AAB + SHA256SUMS assets (measured 2026-11-05, unauthenticated API, run
`41323174024`). Runs 1–7 failed on a malformed stored `KEYSTORE_BASE64` — the strict-decode failure
in §10; the tolerant MIME decoder throws identically on the same input, so it was a corrupt secret
value, not a Gradle bug, and the owner re-entered it. The block refuses
*before* signing, printing only the value's shape (length, index, code point, decoded byte count,
keystore alias count) and never its contents. The correct export is `base64 -w 0 <keystore-file>`
pasted straight into Settings → Secrets and variables → Actions, replacing the stored value.
