# 🏗️ Build System Plan — GitHub Actions CI/CD for RADD Stream Android App

## Core Concept

> **You never need Android Studio, a powerful PC, or Replit compute.**
> Write code → Push to GitHub → GitHub's servers build the APK → Download and install.

```
┌──────────────┐     git push      ┌─────────────────────┐
│  You (code   │ ────────────────► │   GitHub Repository  │
│  in any      │                   │   radddao/radd-stream│
│  editor)     │                   └────────┬────────────┘
└──────────────┘                            │ triggers
                                            ▼
                                   ┌─────────────────────┐
                                   │  GitHub Actions      │
                                   │  Ubuntu Runner       │
                                   │  (free, powerful)    │
                                   │                      │
                                   │  1. Setup JDK 17     │
                                   │  2. Setup Android SDK│
                                   │  3. ./gradlew build  │
                                   │  4. Sign APK         │
                                   │  5. Upload artifact  │
                                   └────────┬────────────┘
                                            │
                                            ▼
                                   ┌─────────────────────┐
                                   │  GitHub Releases     │
                                   │  app-release.apk     │ ← download on phone
                                   │  (signed, ready)     │
                                   └─────────────────────┘
```

---

## Where You Write Code

You have 3 options — pick whichever feels easiest:

### Option A — GitHub Web Editor (zero setup)
- Go to `github.com/radddao/radd-stream`
- Press `.` (period key) → opens VS Code in the browser
- Edit any `.kt` / `.xml` / `build.gradle.kts` file
- Commit → Actions triggers automatically

### Option B — GitHub Codespaces (full VS Code in browser)
- Click **Code → Codespaces → New codespace** on the repo
- Full VS Code in browser with terminal
- Pre-configured with JDK + Kotlin syntax highlighting
- Free 60 hours/month on GitHub Free plan

### Option C — Replit (what you have now)
- Edit files in Replit workspace (they're already synced)
- Commit and push through the repository's configured Git workflow
- Actions triggers on every push

---

## GitHub Actions Workflows (2 workflows)

### Workflow 1 — `ci.yml` (runs on every push / PR)
**Purpose**: Fast feedback — did the code compile? Do tests pass?
- Sets up JDK 17
- Sets up Android SDK
- Runs `./gradlew assembleDebug` (builds debug APK)
- Runs `./gradlew test` (unit tests)
- Uploads debug APK as a build artifact (available for 7 days)

### Workflow 2 — `release.yml` (runs when you push a version tag like `v1.0.0`)
**Purpose**: Build and publish a production-ready signed APK
- Builds release APK (`./gradlew assembleRelease`)
- Signs the APK using keystore stored in GitHub Secrets
- Creates a GitHub Release with the signed APK attached
- Anyone can download and sideload the APK from the Releases page

The CI workflow runs for both pushes and pull requests, so no separate PR
workflow or PR-comment bot is needed.

---

## GitHub Secrets Required

Store these in **Settings → Secrets → Actions** on the repo:

| Secret Name | What it is | How to get it |
|---|---|---|
| `KEYSTORE_BASE64` | Base64-encoded Android signing keystore | Generated once with `keytool` command |
| `KEY_STORE_PASSWORD` | Password for the keystore file | You choose when generating |
| `KEY_ALIAS` | Alias name inside the keystore | You choose when generating |
| `KEY_PASSWORD` | Password for the key itself | You choose when generating |

**One-time keystore generation** (run once on any machine with Java, or GitHub Codespaces):
```bash
keytool -genkey -v \
  -keystore radd-release-key.jks \
  -keyalg RSA -keysize 2048 \
  -validity 10000 \
  -alias radd-key \
  -dname "CN=RADD Stream, OU=App, O=RADD, L=Unknown, ST=Unknown, C=US"

# Then encode it for GitHub Secrets:
base64 -w 0 radd-release-key.jks > keystore_base64.txt
# Copy the content of keystore_base64.txt into the KEYSTORE_BASE64 secret
```

### Release signing — the one measured blocker, and its one-line remedy

**Symptom, read from the API on 2026-10-31 (not inferred from the docs):** `GET /releases` returns
`[]`, and every one of the four runs in the history of
`🚀 Release — Sign & Publish APK + AAB` is `completed / failure` — `40876596427`, `41102348096`,
`41104217171`, `41104231187`. In the newest one the failing step is
`🏗️ Build signed release APK + AAB`; `🧪 Unit tests gate the release` passed, and everything after the
build (`apksigner` verify, checksums, staging, publish) is `skipped`. **No signed APK or AAB has ever
existed for this product.** The tag `v1.0.0` exists in the repo, and resolves to `6a441ec77` — a
trunk point that predates the adult merge-time fold `4a8c163`, so re-running *that* tag would ship
pre-law code.

**Cause, from the run log:** `java.lang.IllegalArgumentException: Last unit does not have enough valid
bits` at `App/app/build.gradle.kts:120`, `BUILD FAILED in 4s`. Gradle dies during
**configuration**, inside `signingConfigs`, before a single Kotlin file compiles. Line 120 is
`keystoreFile.writeBytes(Base64.getDecoder().decode(keystoreBase64))`, and
`java.util.Base64.getDecoder()` is the strict *basic* codec: it accepts no line breaks and throws on a
value whose length is not a whole base64 quantum. The stored `KEYSTORE_BASE64` is such a value —
padding lost between the terminal and the secret field.

**Why the debug CI is green while the release is red, on the same commit:** the four secrets are
mapped into `env:` on exactly two steps — the preflight (`release.yml:53-58`) and the release build
(`release.yml:122-126`). The unit-test step (`release.yml:116-118`) carries no `env:`, so there
`System.getenv("KEYSTORE_BASE64") ?: ""` is empty, the `if (keystoreBase64.isNotEmpty() && …)` guard
skips the decode entirely, and configuration succeeds. A green test run therefore says nothing about
the keystore, and a red release run says nothing about the tests.

**The remedy is owner-side and is one line:** re-set
GitHub → Settings → Secrets → Actions → `KEYSTORE_BASE64` to the output of

```bash
base64 -w 0 /home/ubuntu/raddstream-release.jks
```

pasted **straight from the terminal into the secret field** — no intermediate file, no editor, no
chat message, because each of those is a place trailing `=` padding gets trimmed. Then run the release
workflow against a tag that is at or after current trunk. The proof is a published Release carrying a
real `.apk` and `.aab`; a green build step alone is not the proof, and moving or re-cutting a tag is an
owner action that no agent may take. Verified on this host: that keystore is 2,752 bytes,
`base64 -w 0` renders 3,672 characters ending `==`, and a strict decode returns 2,752 bytes
byte-identical to the file — so **the keystore is sound and only the stored string is damaged.**

**Do not "fix" `App/app/build.gradle.kts`.** The tempting change —
`Base64.getMimeDecoder()` instead of `getDecoder()` — would end the exception by *accepting a
truncated keystore*, and a truncated keystore either fails to load as a keystore or, worst case, signs
with a damaged key whose consequence is that every later upgrade is rejected by the first install.
That trades a loud 4-second configuration failure for a silently broken signing identity. The strict
decoder refusing a malformed input is the code working as designed; `getMimeDecoder()` would advertise
tolerance the signing path must not have.

---

## Folder Structure (what we build in App/src/)

```
Repository root:
├── .github/workflows/
│   ├── ci.yml               ← tests, lint, debug APK on push and PR
│   └── release.yml          ← signed APK on version tag
└── App/                     ← Android Gradle project
    ├── app/                 ← Android app module
    │   └── src/
    │       ├── main/kotlin/com/raddstream/app/
    │       │   ├── ui/      ← Compose screens and components
    │       │   ├── viewmodel/
    │       │   ├── repository/
    │       │   ├── data/    ← DataStore preferences
    │       │   ├── network/ ← Retrofit API and models
    │       │   └── MainActivity.kt
    │       └── test/        ← JVM unit tests
    ├── build.gradle.kts
    ├── settings.gradle.kts
    ├── gradlew
    └── gradle/wrapper/
        ├── gradle-wrapper.jar
        └── gradle-wrapper.properties
```

---

## Build Time Estimates (GitHub Actions free tier)

| Workflow | Trigger | Build Time | Cost |
|---|---|---|---|
| Debug CI | Every push | ~4–6 min | Free (2,000 min/month) |
| Release | Version tag | ~8–10 min | Free |
| PR Check | PR opened | ~5–7 min | Free |

GitHub Free plan gives **2,000 minutes/month** on Linux runners. At 6 min/build, that's ~333 builds/month — more than enough.

---

## Development Flow (Day-to-Day)

```
1. Open GitHub web editor (press . on the repo page)
   OR open GitHub Codespaces
   OR edit in Replit + commit/push with Git

2. Edit a Kotlin file (e.g. HomeScreen.kt)

3. Commit the change (with a message like "feat: add search filter chips")

4. GitHub Actions starts automatically within 30 seconds

5. Watch the build in: github.com/radddao/radd-stream/actions

6. If GREEN ✓ → download debug APK from Actions artifacts tab
   If RED ✗ → read the error log, fix the code, push again

7. To publish a release:
   git tag v1.0.0
   git push origin v1.0.0
   → GitHub creates a Release with signed APK attached
```

---

## How to Test the APK on Your Phone

1. Go to `github.com/rehanradd/radd-stream/actions`
2. Click the latest successful `🔨 CI — Android Build & Test` run
3. Download `app-debug.apk` from the Artifacts section
4. Send to phone via WhatsApp / Telegram / email / Google Drive
5. On phone: enable **"Install from unknown sources"** in settings
6. Open the APK file and install

There is nothing to download from the **Releases** tab: it is empty (measured
2026-10-31), because the release workflow has never published an artifact. Until
"Release signing" above is executed by the owner, the debug APK from the Actions
tab is the only build this pipeline produces.

---

## Caching Strategy (keeps builds fast)

GitHub Actions caches the Gradle build cache and Android SDK between runs:
- First build: ~8–10 minutes (downloads everything)
- Subsequent builds: **~2–4 minutes** (cache hit)

---

## Pipeline Status

```
The Android project and root-level CI workflow are in place. CI runs
`test`, `lint`, and `assembleDebug` for pushes and pull requests, and uploads a
debug APK on every green run — that APK needs no secrets and is what to install
today. The release workflow does **not** publish a signed artifact: measured
2026-10-31 it has failed all four times it has ever run, for the reason in
"Release signing" above. That section is the remedy; until it is executed,
"publishes a signed APK for version tags" is a description of intent, not of
behaviour.
```

---

## What "Write Code → Push → Get APK" Looks Like

```
Push app changes → CI tests and builds the debug APK
Download the CI artifact → install and test on an Android device
...
v1.0.0 tag → intended: signed release APK. Measured: no Release has ever been
published (see "Release signing"), so today the last step is the owner re-setting
KEYSTORE_BASE64, not a tag push.
```

---

## Summary

| You need | Details |
|---|---|
| A code editor | GitHub web (`.` key), Codespaces, Replit, VS Code, Notepad — anything |
| A GitHub account | Already have (`radddao`) |
| A phone to test | Any Android 5.0+ device |
| A PC to run builds | ❌ Not needed — GitHub runs the builds |
| Android Studio | ❌ Not needed — Gradle CLI handles everything |
| Powerful hardware | ❌ Not needed — GitHub's Ubuntu runners do the work |
