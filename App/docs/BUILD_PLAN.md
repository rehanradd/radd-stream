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

> **Retired 2026-11-06 (Session 67):** the blocker below is fixed. The owner
> re-entered the four keystore secrets and release `v1.0.4` published with a
> signed APK + AAB + SHA256SUMS (run `41323174024`, `completed success`,
> 2026-11-01). The diagnosis chain is preserved here as the record of what
> was wrong; nothing below describes the current release flow.

**Symptom, read from the API on 2026-10-31 (not inferred from the docs):** `GET /releases` returns
`[]`, and every one of the four runs in the history of
`🚀 Release — Sign & Publish APK + AAB` is `completed / failure` — `40876596427`, `41102348096`,
`41104217171`, `41104231187`. A fifth, `41233720264` (dispatched from the tag `v1.0.1` at `0a1894d8`),
is measured below and fails the same way, so the count is now five for one cause. In the newest one the failing step is
`🏗️ Build signed release APK + AAB`; `🧪 Unit tests gate the release` passed, and everything after the
build (`apksigner` verify, checksums, staging, publish) is `skipped`. **No signed APK or AAB has ever
existed for this product.** The tag `v1.0.0` exists in the repo, and resolves to `6a441ec77` — a
trunk point that predates the adult merge-time fold `4a8c163`, so re-running *that* tag would ship
pre-law code.

**Cause, read from the hosted log of run `41233720264` / job `124633000210` (qoder1, 2026-11-01):**
steps 1-9 `SUCCESS` — including `🧪 Unit tests gate the release` — step 10
`🏗️ Build signed release APK + AAB` `FAILURE`, steps 11-14 `skipped`; the job ran 19:20:07 →
19:23:01Z and the Gradle block itself says **`BUILD FAILED in 7s`** (the older run `41104231187` said
4s — both are the same death, and neither is a build). The error is
`java.lang.IllegalArgumentException: Last unit does not have enough valid bits` at
`App/app/build.gradle.kts:120`, and the stack frames are `Build_gradle$3$2$1.execute(build.gradle.kts:120)`
→ `signingConfigs` → `CommonExtensionImpl.signingConfigs` → `ExtensionsStorage.configureExtension` →
`Build_gradle.<init>`. That is **configuration time, inside `create("release")`** — no task executed, no
Kotlin compiled, no `.apk` byte written. Line 120 as it stands at `0a1894d8` is
`keystoreFile.writeBytes(Base64.getDecoder().decode(keystoreBase64))`, and
`java.util.Base64.getDecoder()` is the strict *basic* codec: it accepts no line breaks and throws on a
value whose length is not a whole base64 quantum.

**Read the message for what it is.** `Last unit does not have enough valid bits` is a
**length/padding** fault — a truncated or character-losing string, e.g. trailing `=` padding trimmed
between the terminal and the secret field. It is not a wrapped secret: an embedded newline in the basic
decoder fails with `Illegal base64 character 0a`, a different message, so the stored value is short of
a whole base64 quantum (or has lost tail characters), and it is not line-broken. And because the throw
is at configure time, **no signing password has
ever been exercised by CI** — not `KEY_STORE_PASSWORD`, not `KEY_PASSWORD`, not the alias. A
`keytool -list -keystore … -storepass …` experiment answers a question this release never got to ask,
and the preflight step (`release.yml:53`, name-only) proves only that `KEYSTORE_BASE64` is *non-empty*.

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
chat message, because each of those is a place trailing `=` padding gets trimmed. (`/home/ubuntu/`
holds exactly one keystore, `raddstream-release.jks`; the `radd-release-key.jks` name earlier in this
file is the *generation* snippet's example, not a second key.)

**Check the stored value before re-pasting it, without ever printing it.** In the owner's own shell,
with the current secret in `$KB64`:

```bash
printf '%s' "$KB64" | wc -c        # must be a multiple of 4
printf '%s' "$KB64" | base64 -d | wc -c   # must equal the keystore's own byte count
stat -c%s /home/ubuntu/raddstream-release.jks   # the number the line above must match
```

A first command that is not a multiple of 4, or a second that disagrees with the third, is the fault
itself — and `base64 -w 0`, one line, no trailing newline, is the re-mint that fixes it.
**Nothing secret may ever leave the owner's shell:** not the keystore bytes, not `KEYSTORE_BASE64`, not
a password, not a decoded dump — not into a file, a log, a commit, a chat message, or a documentation
example. The commands above print counts only; keep it that way.

Then re-run the
release workflow: `release.yml:34` accepts `workflow_dispatch`, so **no new tag is needed**, and
re-dispatching is better than re-tagging anyway — `v1.0.0` (`6a441ec`) predates the adult
reconciliation fold and `v1.0.1` (`0a1894d`) is already behind trunk, so both are stale as release
points. The proof is a published Release carrying a
real `.apk` and `.aab`; a green build step alone is not the proof, and moving or re-cutting a tag is an
owner action that no agent may take. Verified on this host: that keystore is 2,752 bytes,
`base64 -w 0` renders 3,672 characters ending `==`, and a strict decode returns 2,752 bytes
byte-identical to the file — so **the keystore is sound and only the stored string is damaged.**

**Do not relax the decoder — that is the one change this failure rules out.** The tempting swap,
`Base64.getMimeDecoder()` for `getDecoder()`, was measured on this host against a single JVM and does
not even address the symptom: our error is `Last unit does not have enough valid bits`, which means the
stored value's final base64 group is malformed, and the tolerant decoder **throws the identical message
on that exact input**. What the swap does change is the case the strict decoder currently tolerates — a
secret that is one character short decodes fine under either decoder — so adopting it would accept a
truncated keystore, after which the app either fails to load as a keystore or, worst case, signs with a
damaged key whose consequence is that every later upgrade is rejected by the first install. A
whitespace filter (`filter { !it.isWhitespace() }`) is the same weakening in another form: it makes a
wrapped secret look valid instead of telling the operator to re-paste it. The strict decoder refusing a
malformed input is the code working as designed.

What the run lacked was not a looser decoder but a sentence an operator could act on, so
`App/app/build.gradle.kts` was changed in the opposite direction: the signing block now refuses loudly
*before* it decodes and *before* it writes — length must be a multiple of four, the value must contain
only the base64 alphabet (the first offender reported by index and code point), `KEY_ALIAS` and
`KEY_PASSWORD` must be present, then the strict decode, then the bytes must parse as a `JKS` or
`PKCS12` keystore under the stored store password, then the alias must exist, must be a private-key
entry, and must actually be unlocked by `KEY_PASSWORD`. Each message prints the **shape** of the
credential — length, index, decoded byte count — and never the credential itself, because a build log
is read by more people than the secret is. Against the real 2,752-byte keystore: an extra trailing
character now reads `3673 chars, not a multiple of 4` instead of a stack trace, a missing character is
refused (which the decoder alone did not do), and a 76-column wrap is refused at `index 76 (0xa)`.
`KeystorePreflightGuardTest` pins the strict decoder's presence, the ordering, and the no-value rule.

**What that preflight does and does not prove — stated plainly, because it is easy to over-read.**
It has **never executed on CI, not once.** Every release run to date dies at `build.gradle.kts:120`
inside `signingConfigs`, and the block above now refuses *before* the decode — so on a still-broken
secret the next dispatch will print a named refusal instead of a stack trace, but nothing after the
first refusal line has ever run on a runner either, and the store-password load, the `containsAlias`
check and the `getKey` unlock have certainly not. Two consequences follow. (1) The 0-byte-keystore
path is unreachable by construction: `writeBytes` is the last statement, so a configure-time death
never produces a keystore file at all — which is also why no password has ever been tested. (2) What
hosted CI *did* prove is narrower than it looks: run `41236922263` on `1efadf2` is `completed success`
and its `:app:testDebugUnitTest` executed `KeystorePreflightGuardTest`, but that test reads the script
text to pin ordering and the no-value rule — it is a test **about** the block, not an execution **of**
it. Reasoning is not evidence. The first real evidence will be a line printed by the block itself in a
`workflow_dispatch` log, and the only proof that matters is a published Release with a signed `.apk`
and `.aab`.

**Two records this section now contradicts, deliberately.** Tags exist: `refs/tags/v1.0.0` → `6a441ec7`
and `refs/tags/v1.0.1` → `61d88d04`, which peels to the trunk commit `0a1894d8` (measured by
`git merge-base --is-ancestor` — the tag is on trunk). So any document still asserting
"tags: 0, releases: 0, no release has ever been made" is false, and the App-side rule that the *first*
tag waits for green Android CI has already been crossed by someone other than this lane. `v1.0.1`
being on trunk is also why re-dispatching beats re-tagging: the tag already points at code trunk
contains, it just points at code trunk has moved past.

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
