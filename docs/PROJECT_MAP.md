# Radd Stream project map

Last updated: 2026-10-22 for the REST-surface and test-suite sections below (verified by reading `Fast_Fetch/viewer.py`, `Fast_Fetch/fast_fetch.py`, `App/app/src`, and listing `Fast_Fetch/test_*.py`). The repository/CI/server paragraphs are from 2026-10-17 and still need re-verification. Authenticated GitHub API metadata verified that `radddao/radd-stream` is public. Unauthenticated GitHub API/raw-file requests from this Replit workspace returned 404, while authenticated API reads and a Git clone succeeded. Use the documented temporary askpass flow for Git operations; unauthenticated 404s here do not establish that a public repository or file is missing.

## What lives where

- **Repository:** `https://github.com/radddao/radd-stream` (public visibility verified through authenticated GitHub API metadata on 2026-10-16). GitHub `main` is the canonical current source. The Replit `gitsafe-backup` remote is a separate internal backup, not the GitHub remote. In this workspace, use authenticated Git operations through the temporary askpass flow in `ORACLE_DEPLOYMENT.md`.
- **Python backend:** `Fast_Fetch/`. `fast_fetch.py` is the core engine/CLI; `viewer.py` provides the local API/dashboard; `config.py` configures paths. Tests are **not** just `test_database.py` and `test_vidout.py` — as of 2026-10-22 there are 26 `Fast_Fetch/test_*.py` modules, including per-site importer tests, `test_merge_catalogs.py`, `test_backup_manager.py`, `test_release_descriptor.py`, and `test_link_health.py`. `test_all_sites.py` is the live network audit; the others run offline. The older "36 tests / 6 tests" figures in root `AGENTS.md` describe only those two files and are not the suite total. The backend uses Python's standard library only.
- **Catalog database:** SQLite, normally `Fast_Fetch/fast_fetch.db` for the unified catalog. Per project rule, scraping is performed into isolated per-site staging databases (e.g. `multimovies.db`, `vegamovies.db`) and merged into the unified catalog with `Fast_Fetch/merge_catalogs.py`. For Oracle, the runbook specifies persistent data outside the code checkout (`/home/ubuntu/radd-stream-data/fast_fetch.db`). Always maintain a verified backup before replacing or merging.
- **Android app:** `App/`, a Kotlin/Jetpack Compose Gradle app. App code/tests are under `App/app/`; the Gradle project is rooted at `App/`.
- **Replit entrypoint:** `.replit` is local-only configuration and may contain sensitive values. Keep it ignored and untracked; do not inspect its values or commit it. Historical commits still contain prior versions; the user chose to leave them intact. Its settings do not prove an API server is running.
- **Instructions and handoff:** root `AGENTS.md` and `SESSION.md`; `Fast_Fetch/AGENTS.md` and `Fast_Fetch/CONTINUITY.md` for backend work; `App/AGENTS.md` for Android work; `ORACLE_DEPLOYMENT.md` for server and credential procedures; `docs/AI_HANDOFF_PROMPT.md` is the short starter and `docs/AGENT_BOOTSTRAP.md` contains onboarding steps.

## Git branches and Android CI

- The current GitHub `main` snapshot has root `.github/workflows/ci.yml` and `release.yml`; additional workflows remain under `App/.github/workflows/`. Only root-level workflows are discovered automatically by GitHub Actions.
- The separate `radddao-work` branch contains additional Android MVP work and is divergent from `main`; review differences before merging and do not merge it wholesale.
- The latest Actions run was not checked in this session. Verify the current run status before relying on CI.
- Expected Android output: GitHub Actions builds a debug APK as a downloadable artifact; version-tag release builds require signing secrets configured in GitHub Actions.

## Verified REST surface (2026-10-22, re-read against `Fast_Fetch/viewer.py`)

Routes that exist in `do_GET()` (viewer.py:2039-2190): `/api/data`,
`/api/sitemap`, `/api/fetch`, `/api/m3u`, `/api/health-check`, `/api/heal`,
`/api/v1/posts`, `/api/v1/posts/{id}`, `/api/v1/stream`, `/api/v1/rules`,
`/api/v1/stats`, `/favicon.ico`, `/client`, `/mobile`, `/`. There is **no
`/api/v1/sync`** and no `do_POST` handler at all — any doc or roadmap item that
reads like a sync/heal-over-HTTP capability is a proposal, not an endpoint.

Three facts worth carrying across accounts because they have repeatedly misled
agents and app developers:

- **`?type=anime` returns zero rows.** `content_type` is matched by exact SQL
  equality (viewer.py:1898) and the writers only produce `movie`, `series`,
  `complete_season`, `ongoing_season` (`classify_media()`,
  fast_fetch.py:1613-1622). Anime is expressed by `posts.is_animated` /
  `posts.industry`, neither of which the API filters on yet.
- **`/api/heal` is routed but broken.** The handler builds a payload and never
  writes it to the socket (viewer.py:2100-2108); `protocol_version` is `HTTP/1.1`,
  so clients hang. Use the `fast_fetch.py heal` CLI.
- **The API is entirely unauthenticated and unencrypted.** No API key, token,
  session, or rate limiting exists anywhere in `viewer.py`; `send_json()` emits
  `Access-Control-Allow-Origin: *` (viewer.py:2037), `start_server()` defaults to
  `0.0.0.0` (viewer.py:2211), and the Oracle host serves plain HTTP with no TLS.
  Nothing behind this API should be described as private or secured. `/api/v1/stats`
  additionally counts `is_18_plus = 1` rows that `/api/v1/posts` hides, so stats
  totals will always exceed the browsable catalog.

## Oracle Ubuntu backend

- Oracle is intended to host the **Python backend/API and persistent SQLite data**. Android APKs are built on GitHub Actions; the Android app is not an Oracle server process.
- A read-only check on 2026-10-17 found `radd-stream.service`, Nginx, and Supervisor active; the backend listens on `127.0.0.1:8080` behind Nginx on port 80. `/opt/radd-stream` has no `.git` metadata, and its deployed source does not match the 11 fetched Git revisions compared. See `ORACLE_DEPLOYMENT.md` and `docs/SESSION_CHECKPOINT.md`; its host-key record is TOFU, not OCI Console verified.
- The runbook describes a planned layout of Nginx on port 80 proxying to the API on loopback port 8080, with SQLite data outside the code checkout. Recheck the host before relying on this layout. Public API routes need the documented allowlist; do not expose the resolver/fetch routes or port 8080.
- Do not deploy from an agent branch or directly copy untested edits to a live server. A production deployment requires a verified host key, the runbook's setup checklist, a tested deployment process, health checks, and a recovery route.

## Cross-agent save and resume

1. Start with root `AGENTS.md`, `SESSION.md`, `CHANGELOG.md`, and this map; then read the relevant subsystem guide and continuity log. Preserve `Fast_Fetch/DAO.md` unless the user explicitly asks to change it.
2. Work in an agent/task branch. Keep changes focused and verify each coherent milestone.
3. After every tested milestone, update `docs/SESSION_CHECKPOINT.md`, stage only reviewed paths, inspect the staged diff, commit, and push the branch. If checks cannot finish before the session ends, push a clearly labeled WIP checkpoint to the task branch and record pending checks; do not wait for a quota warning.
4. Never stage or push `.replit`; it is local-only and ignored. Use the temporary Git askpass procedure in `ORACLE_DEPLOYMENT.md`. Do not run or restore `push.py`, `github_push.py`, or `emergency_push.py`; their former versions used broad per-file GitHub API writes and could target `main`, while the current files are warning stubs.
5. On push failure, preserve the local commit and checkpoint, report the exact failure, and do not claim synchronization.

## Secrets

The user's permanent choice is to configure `GITHUB_TOKEN` and `ORACLE_SSH_KEY` as environment variables in Replit Configurations, not Replit Secrets. Verify presence by name in each workspace; never read or print values, ask to move them, place them in Git URLs/arguments/logs/files, or copy them to Oracle. These variables do not automatically transfer to another account or to GitHub Actions. GitHub Actions needs its own repository/environment secrets for any signed APK or automated Oracle workflow.

## Research sources

- [AGENTS.md](https://agents.md/) — portable repository instructions for coding agents.
- [GitHub Actions secrets](https://docs.github.com/en/actions/security-for-github-actions/security-guides/using-secrets-in-github-actions) and [workflow artifacts](https://docs.github.com/en/actions/tutorials/store-and-share-data).
- [GitHub Gradle build/test guidance](https://docs.github.com/en/actions/tutorials/build-and-test-code/java-with-gradle) and [deployment environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/control-deployments).
- [Oracle Ubuntu compute example](https://docs.oracle.com/en-us/iaas/Content/developer/apache-on-ubuntu/01oci-ubuntu-apache-summary.htm).
