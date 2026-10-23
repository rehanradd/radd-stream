# HANDOFF — App CI workflows (written by the app-CI agent, 2026-10-22)

Scope of this handoff: I own **only** `.github/workflows/**` at the repo root.
Everything below is a request for the coordinator / other fleet agents.

## What I shipped (root-level, GitHub-discoverable)

- `.github/workflows/ci.yml` — Android validation. Triggers: push to any branch
  touching `App/**`, PRs, manual. Runs
  `:app:assembleDebug :app:testDebugUnitTest :app:lintDebug` in ONE Gradle
  invocation with `--continue` so all three report in one log.
- `.github/workflows/release.yml` — tag `v*.*.*`. Hard-fails if any of the four
  keystore secrets is missing, builds signed APK **and** AAB, verifies the APK
  with `apksigner verify --print-certs` (fails loudly on unsigned), publishes
  SHA-256SUMS as a release asset.
- `.github/workflows/backend-ci.yml` — push/PR touching `Fast_Fetch/**`; runs
  the five stdlib suites with `python3 -S` and zero pip installs. I verified all
  five pass offline on this Oracle VM (python 3.12.3) before writing the file.

## CRITICAL — git/layout actions needed from the coordinator (I ran no git)

1. **Evidence of why CI "never ran":** the GitHub API reports
   **0 workflows registered and 0 workflow runs in repo history** for
   `radddao/radd-stream`. The "last run failed at Android SDK setup" line in
   AGENTS.md is not supported by any recorded run. The real root cause is file
   placement:
   - on `origin/main` the workflows live at `radd-stream/.github/workflows/`
     (a wrong extra directory) and `App/.github/workflows/` — GitHub only
     discovers `.github/workflows/` at the true repository root;
   - the correct root-level `.github/workflows/` exists only on the local
     `master` branch, which has never been pushed.
2. **Branch divergence:** local `master` (HEAD `7b03f0f`) is 13 commits ahead
   and 102 behind `origin/main` (tip `f4b19d9`) — fully diverged. Until the
   root `.github/workflows/` files land on **`main`** (the default branch;
   registration for `workflow_dispatch` and PR checks needs them there), no
   workflow will execute. Please merge/reconcile master↔main and push.
3. **Remove the inert copies** (their content is now superseded):
   `App/.github/workflows/{ci,pr-check,release}.yml` and, on `main`, the entire
   misplaced `radd-stream/.github/` directory. I am not allowed to delete them.
4. ⚠️ **The `origin` remote URL in `.git/config` embeds a GitHub token in
   plaintext.** That violates the project's own "never put credentials in Git
   URLs" rule. Ask whoever set it up to rotate that token and move it to the
   askpass/credential flow from ORACLE_DEPLOYMENT.md. (I used read-only GETs
   with it to diagnose CI and printed nothing.)

## Requests to the App/Gradle agents (I did not touch build files)

- **Defense-in-depth signing gate (optional `app/build.gradle.kts` change):**
  today an unsigned `assembleRelease` is only caught in CI by `apksigner`.
  Consider adding, inside the `release` buildType block or a final task hook:
  fail the build when `System.getenv("KEYSTORE_BASE64")` is empty for
  `assembleRelease`/`bundleRelease`. The workflow already gates this, so it is
  a nice-to-have, not blocking.
- **Version properties contract:** `app/build.gradle.kts` reads
  `VERSION_NAME`/`VERSION_CODE` from **environment variables**. The old
  release.yml passed them as `-P` project properties, which the script ignores
  — I removed the dead flags; keep using env (no source change needed).
- **What to expect red on first runs (this is the useful outcome):** the fleet
  is adding Kotlin right now, so the first green-to-Gradle run will likely show
  per-file compile errors (`e: file.kt:line:col`). That means the SDK/JDK setup
  steps PASSED and Gradle is finally talking about the Kotlin — exactly what we
  never got before. Known code-level bugs the compiler/lint will surface are
  listed in `App/AGENTS.md` §6 (Models.kt field mismatches, `isTemporary`
  Int-vs-boolean, `type=anime`); they are the app agents' work, not CI bugs.
- Unit tests run as `:app:testDebugUnitTest` only (no connected-device tasks —
  there is no `androidTest` instrumentation runner usage in CI).

## Requests to the Backend agents

- The five core suites must stay offline. `test_link_health.py` is allowed to
  bind `127.0.0.1` only; if it ever reaches an external host, fix the test, not
  the workflow.
- There are ~20 more per-site `test_*_import.py` suites. If any of you prove
  one passes offline (no network, no live DBs), request a step for it in
  `backend-ci.yml` — I will add them one step per suite so failures stay
  attributable. `test_all_sites.py` stays excluded permanently (live audit).

## How I validated (no push, no gh CLI available on this VM)

- PyYAML (`python3 -c "import yaml"` works here) parsed all three files, plus a
  custom structural check for step-output references and `uses:` ref format.
  It caught and fixed one real YAML error (unquoted `name:` containing ": ").
- `actionlint`, `yq`, `ruby`, `shellcheck`, `gh` are all **missing** on this
  host — YAML + structural lint is the ceiling of local validation.
- Every pinned action SHA was resolved live from the GitHub API and
  cross-checked against the tag (checkout v7.0.1, setup-java v6.1.0, cache
  v6.1.0, upload-artifact v7.0.2, setup-android v4.0.4,
  action-gh-release v3.0.3). `setup-android@v4`'s `packages` input was verified
  against its `action.yml`.
- Gradle task names were linted against the actual build: `:app` is the only
  module (`settings.gradle.kts`), `assembleDebug/testDebugUnitTest/lintDebug/
  assembleRelease/bundleRelease/testReleaseUnitTest` are all AGP-generated
  variant tasks for that configuration, JDK 17 matches
  `JavaVersion.VERSION_17`/`jvmTarget 17`, compileSdk 35 matches the pinned
  `platforms;android-35 build-tools;35.0.0`.
