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

1. Go to `github.com/radddao/radd-stream/actions`
2. Click the latest successful build
3. Download `app-debug.apk` from the Artifacts section
4. Send to phone via WhatsApp / Telegram / email / Google Drive
5. On phone: enable **"Install from unknown sources"** in settings
6. Open the APK file and install

For releases: go to **Releases** tab → click **app-release.apk** → download directly on phone browser

---

## Caching Strategy (keeps builds fast)

GitHub Actions caches the Gradle build cache and Android SDK between runs:
- First build: ~8–10 minutes (downloads everything)
- Subsequent builds: **~2–4 minutes** (cache hit)

---

## Pipeline Status

```
The Android project and root-level CI workflow are in place. CI runs
`test`, `lint`, and `assembleDebug` for pushes and pull requests. The release
workflow builds and publishes a signed APK for version tags, once the signing
secrets are configured.
```

---

## What "Write Code → Push → Get APK" Looks Like

```
Push app changes → CI tests and builds the debug APK
Download the CI artifact → install and test on an Android device
...
v1.0.0 tag → signed release APK (after signing secrets are configured)
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
