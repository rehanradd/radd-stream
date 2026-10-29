# Radd Stream project map

Last updated: 2026-10-22 for the REST-surface and test-suite sections below (verified by reading `Fast_Fetch/viewer.py`, `Fast_Fetch/fast_fetch.py`, `App/app/src`, and listing `Fast_Fetch/test_*.py`). The repository/CI/server paragraphs are from 2026-10-17 and still need re-verification. Authenticated GitHub API metadata verified that `rehanradd/radd-stream` is public. Unauthenticated GitHub API/raw-file requests from this Replit workspace returned 404, while authenticated API reads and a Git clone succeeded. Use the documented temporary askpass flow for Git operations; unauthenticated 404s here do not establish that a public repository or file is missing.

## What lives where

- **Repository:** `https://github.com/rehanradd/radd-stream` (public visibility verified through authenticated GitHub API metadata on 2026-10-16). GitHub `main` is the canonical current source. The Replit `gitsafe-backup` remote is a separate internal backup, not the GitHub remote. In this workspace, use authenticated Git operations through the temporary askpass flow in `ORACLE_DEPLOYMENT.md`.
- **Python backend:** `Fast_Fetch/`. `fast_fetch.py` is the core engine/CLI; `viewer.py` provides the local API/dashboard; `config.py` configures paths. Tests are **not** just `test_database.py` and `test_vidout.py` — as of 2026-10-28 there are 60 test modules across `Fast_Fetch/test_*.py` and `Fast_Fetch/importers/test_*.py`, including per-site importer tests, `test_merge_catalogs.py`, `test_backup_manager.py`, `test_release_descriptor.py`, and `test_link_health.py`. `test_all_sites.py` is the live network audit; the others run offline. The older "36 tests / 6 tests" figures in root `AGENTS.md` describe only those two files and are not the suite total. The backend uses Python's standard library only.
- **Catalog database:** SQLite. `Fast_Fetch/fast_fetch.db` is the development default; the live
  catalog on Oracle is `RADD_DB_PATH=/home/ubuntu/radd-stream-data/merged_catalog_20261025.db`, the
  file the running `radd-stream` unit serves (`WorkingDirectory=/opt/radd-stream`,
  `ExecStart=/usr/bin/python3 -S /opt/radd-stream/Fast_Fetch/fast_fetch.py serve --host 127.0.0.1
  --port 8080`). Per project rule every site is scraped into its own staging vault and merged with
  `Fast_Fetch/merge_catalogs.py` — **always pass `--target-db`**, because omitting it silently targets
  `Fast_Fetch/fast_fetch.db`. Measured 2026-10-29 05:12 with index paths only (never a full scan or
  `PRAGMA integrity_check` on this 6.4 GB file at `nproc=1`): **150,799 posts / 1,780,121 releases /
  4,073,865 download_sources / 309,558 post_sources across 31 distinct `source_site`**, of which
  **15,020 posts carry `is_18_plus = 1`** and the public list route answers `total=135,779` —
  exactly posts minus flagged. **Re-measured read-only at 21:35 against the same file (its mtime is
  still 10:52:37): posts 150,799 (unchanged), `is_18_plus=1` 15,068 (+48), browsable `total` 135,731.**
  The 48-row shift is a *tightening*, not a merge or a leak, and it is fully audited:
  `/home/ubuntu/radd-stream-backups/adult_flip_rollback_journal.txt` records 10:52:37 "rolled back 407
  of 455 key-reconciliation flips / kept (true adult evidence): 48 / public total 135324 -> 135731",
  with the preimage in `adult_flip_preimage_20261029_104859.json` (455 rows) and the named root cause
  in the journal itself — `ADULT_TITLE_PATTERNS` contains `\buncut\b` and `\bunrated\b`, which are
  version labels and not adult evidence. So the sequence is 135,779 (05:12) → 135,324 (the 10:48 flip
  of all 455) → 135,731 (407 undone at 10:52).
  Sixteen vaults have been merged in two campaigns: ten on 2026-10-28/29 (levidia, 5movierulz,
  dramacool, kisskh, moviecok, moviesmela, aryplus, filmiyin, animahd, desiserials) taking the
  catalog from 130,016 posts, then batch 3 on 2026-10-29 (pagalmovies +3,642 posts, filmyhit +935,
  filmywap +46). Rollback artifacts: `/home/ubuntu/radd-stream-backups/premerge_20261028_232902.db`
  (posts=130,016 — pre-dates batch 3, so it is NOT an acceptable rollback today) and
  `prebatch4_20261029_051444.db` (6,396,899,328 bytes, online `Connection.backup()` in 394.5 s,
  verified posts=150,799) which is the current rollback point. **Merging is authorized by the owner
  (2026-10-28 23:00).** Still unmerged: `mp4moviez.db` (29,848 posts, 54,267 unresolved `dl.php`
  redirect stubs, schema-incompatible — `merge_catalogs.py` raises `ValueError` because there is no
  `canonical_key` and no `sources` table, so a converter comes first; qoder2 has it in flight) and
  `kuttymovies.db` (0 posts). `katmoviehd_refreshed.db` and `multimovies_full_20261022.db` are
  superseded snapshots of sites already in the catalog, not new sites. Newest staging vault detail:
  `aryplus.db` — 481 titles (264 series, 217 single videos), 10,860 public HLS sources on
  `vod.aryzap.com`, its 538 parked sitemap ids proven **unpublished 307-to-homepage shells, not
  404s** (`f8cdcd5`).
- **Android app:** `App/`, a Kotlin/Jetpack Compose Gradle app. App code/tests are under `App/app/`; the Gradle project is rooted at `App/`.
- **Replit entrypoint:** `.replit` is local-only configuration and may contain sensitive values. Keep it ignored and untracked; do not inspect its values or commit it. Historical commits still contain prior versions; the user chose to leave them intact. Its settings do not prove an API server is running.
- **Instructions and handoff:** root `AGENTS.md` and `SESSION.md`; `Fast_Fetch/AGENTS.md` and `Fast_Fetch/CONTINUITY.md` for backend work; `App/AGENTS.md` for Android work; `ORACLE_DEPLOYMENT.md` for server and credential procedures; `docs/AI_HANDOFF_PROMPT.md` is the short starter and `docs/AGENT_BOOTSTRAP.md` contains onboarding steps. Long-term strategy: `docs/MASTER_ARCHITECT_DIRECTIVE.md` (20-year multi-VM federation blueprint), `docs/SENIOR_MENTOR_DIRECTIVE_QODER.md` (agent mentorship & smart methods), and `docs/SITE_SCOUT_SPEC.md` (automated scraper reverse-engineering engine).

## Git branches and Android CI

Re-read against the live remote on 2026-10-27 (every claim below is an API/git answer, not a
recollection — this is the section that had gone stale twice running).

- **Resolved 2026-10-27 by the owner: `main` was fast-forwarded to `master`.** Both heads are now
  `095c3c7`, and the push was `master:main` — a pure fast-forward, no force, no history rewrite, so
  nothing that was on `main` was discarded (`main..master` was 25 commits, `master..main` was zero).
  **`AGENTS.md`'s rule is now operative as written: push verified, tested milestones to `main`.**
  `master` is not retired and is not to be deleted; keep it pointing at the same commit as `main`
  when you push, and never let the two drift again without saying so here.
- Root workflows, verified present on `master`: `.github/workflows/ci.yml`, `release.yml`,
  `backend-ci.yml` (all three `state: active`). The copies still sitting in `App/.github/workflows`
  are inert — GitHub only discovers repo-root `.github/workflows/`.
- **CI HAS run, and it is running now — every claim to the contrary in this file's history was
  wrong and is retired here.** Re-measured 2026-10-29 03:54 (host time) with the `GITHUB_TOKEN`
  askpass flow: `/actions/permissions` → `{"enabled": true, "allowed_actions": "all"}`,
  `/actions/runs` → `total_count: 40`, and all three root workflows report `state=active`
  (`🐍 Backend CI — Stdlib Python Tests`, `🔨 CI — Android Build & Test`,
  `🚀 Release — Sign & Publish APK + AAB`). The paragraph below had asserted "CI has never run",
  `actions/runs → total_count: 0` and "the account-level switch sits above it and turns nothing on
  here"; that was a stale reading of a repository that had not yet pushed a compliant commit, not a
  property of the account. Do not repeat it.
- ⚠️ **CORRECTED 2026-10-30 — this bullet was true when written and is now false.** It read
  "What is actually true today: **CI is red on both sides**", with backend failing from
  `test_evidence_writeback.py` onward and Android at `636 tests completed, 9 failed` plus
  `lintDebug — Lint found 23 errors, 145 warnings` (first at `RenditionFailover.kt:137`).
  Both sides are green. **Re-measured 2026-10-30 01:2x host time by the qoder3 lane**, token read from `os.environ` inside a `python3 -S` heredoc (never in argv, never in a URL), against `/repos/rehanradd/radd-stream/actions/workflows/<id>/runs?per_page=10`; the API prints UTC. Workflow ids: backend `398476976` (93 runs), Android `398476977` (28 runs), Release `398476978`. Backend `398476976` is `completed success` on **both** `master` and `main` at `87b7b6f` (19:42:59Z / 19:43:00Z) and at `1aafddb`. Android `398476977` is `completed success` on `main` and `master` at `9859b8a` (17:00Z), and every app-lane run after it is green: `217e8cd` (17:21:50Z) — the retry that retired the only recent failure, `99472e0` at 17:08:19Z — then `bc2e534`, `e6482e9`, `a3c34ff`, `bd45ba0`, `9a590bb`, and the newest run of any branch, `5e74aa2` on `q1-identity-fix` at 19:22:09Z. **There is no red app lane.** The authoritative backend gate is **25 `🧪` modules — it was 17 /
  791 tests at `9859b8a` and it has grown since; read `.github/workflows/backend-ci.yml`, do not
  trust any count quoted in prose**. CI run `40954291359` at `396e476` is the evidence for 25:
  `completed success` with every step green, and the three newest (`test_bounded_ledger.py`,
  `test_project_readonly.py`, `test_admin_panel.py`) each finishing in 1 s on the hosted runner. The trap that bullet described is still true and still matters: `ScreenSnapshotTest`
  and `PosterCardProvenanceTest` are excluded from every local arm64 run (Robolectric ships no ARM
  runtime, robolectric/robolectric#9166), so a green local Gradle build proves nothing about those
  nine — only the hosted runner judges them, and it now passes them.
- `tags: 0` and `releases: 0` are still true: no signed APK has ever been published, and the only
  APK anyone has installed is the hand-placed debug build in `/var/www/download/`.
- ⚠️ **CORRECTED 2026-10-30** (it read "…while the tree is red the offline suites … remain the only
  verification that is actually passing. Restore green before claiming a milestone"). The tree is not
  red: **Re-measured 2026-10-30 01:2x host time by the qoder3 lane**, token read from `os.environ` inside a `python3 -S` heredoc (never in argv, never in a URL), against `/repos/rehanradd/radd-stream/actions/workflows/<id>/runs?per_page=10`; the API prints UTC. Workflow ids: backend `398476976` (93 runs), Android `398476977` (28 runs), Release `398476978`. Backend `398476976` is `completed success` on **both** `master` and `main` at `87b7b6f` (19:42:59Z / 19:43:00Z) and at `1aafddb`. Android `398476977` is `completed success` on `main` and `master` at `9859b8a` (17:00Z), and every app-lane run after it is green: `217e8cd` (17:21:50Z) — the retry that retired the only recent failure, `99472e0` at 17:08:19Z — then `bc2e534`, `e6482e9`, `a3c34ff`, `bd45ba0`, `9a590bb`, and the newest run of any branch, `5e74aa2` on `q1-identity-fix` at 19:22:09Z. **There is no red app lane.** A hosted green run is not merely reachable, it is the current state of both
  trunk refs. Keep the offline suites as the pre-push gate because they cost this box minutes and a
  hosted run costs this box nothing — but no lane owes a "restore green" step before landing a
  milestone, and a docs-only push legitimately triggers zero backend runs (path filter
  `Fast_Fetch/**`), which is not a red gate.
- Expected Android output *if* CI ever runs: a debug APK as a downloadable artifact; version-tag
  release builds additionally need `KEYSTORE_BASE64`, `KEY_STORE_PASSWORD`, `KEY_ALIAS`,
  `KEY_PASSWORD` present as repository Actions secrets (verified only by name, never by value).
- The separate `radddao-work` branch (`95b74a2`) contains additional Android MVP work, is divergent
  from `main`, and stays unmerged; review differences before merging and do not merge it wholesale.
  Six `agent/*` branches are also still on the remote (`7starhd-importer-deployment-20261018`,
  `multimovies-full-import`, `multimovies-import-regression-fix`, `portable-context`,
  `replit-bootstrap-access-fix`, `staging-merge-approval-gate-20261018`). Whether any of them is
  already merged was not checked here, so leave them alone rather than pruning them.
- **Push credentials, re-checked 2026-10-29 05:00: they work, and the entry this one replaces was
  stale.** `GITHUB_TOKEN` is present in the environment and **works**: `ls-remote` over the
  explicit clean URL through the temporary askpass helper succeeded, `POST`-free REST calls with
  `Authorization: Bearer $GITHUB_TOKEN` returned `/actions/runs` payloads, qoder5 pushed `34f22c6` to
  `master` and `main` at ~05:05 with hosted Backend CI going green on both refs, and I pushed `e96bf84`
  to both refs minutes later. The 2026-10-28 21:40 reading — `401 Bad credentials` on
  `api.github.com/user` plus `remote: Invalid username or token` — was real at that moment; the token
  was evidently re-issued or re-enabled between then and now. Two facts that did NOT change and still
  hold: there is no `gh` CLI and no GitHub SSH key on this VM, so the askpass flow is the only push
  path, and `origin`'s stored URL still embeds the owner's older leaked credential, so **push to the
  explicit `https://github.com/rehanradd/radd-stream.git`, never to `origin`**, and never print the
  value. If a push ever does fail with `Invalid username or token` again, record the failure and the
  next step in the checkpoint rather than concluding the whole lane is dead — that is exactly the
  mistake this paragraph previously made.
- **Push credentials, re-checked again 2026-10-29 18:51: still alive, and I learned *why* the last
  false alarm was possible.** `GITHUB_TOKEN` (40 characters, never printed) returned **200** on
  `api.github.com/user`, on `/repos/rehanradd/radd-stream/commits/e2fe36a`, and on
  `/actions/permissions`, and `e2fe36a` is on both `master` and `main`. Twelve minutes earlier that
  same token produced `remote: Invalid username or token` on a push — because I had generated the
  askpass helper with `printf` instead of the documented heredoc, which expands the inner `%s` away
  and sends an empty password. So the sentence above is now backed by a named, reproducible cause:
  **an `Invalid username or token` from a `printf`-built helper is a bug in the helper, not news
  about the token.** The heredoc in `ORACLE_DEPLOYMENT.md` is the only approved form.

## Verified REST surface (2026-10-22, re-read against `Fast_Fetch/viewer.py`)

Routes that exist in `do_GET()` (viewer.py): `/api/data`,
`/api/sitemap`, `/api/fetch`, `/api/m3u`, `/api/health-check`, `/api/heal`,
`/api/v1/posts`, `/api/v1/posts/{id}`, `/api/v1/stream`, `/api/v1/rules`,
`/api/v1/stats`, `/favicon.ico`, `/client`, `/mobile`, `/`. There is **no
`/api/v1/sync`** and no `do_POST` handler at all — any doc or roadmap item that
reads like a sync/heal-over-HTTP capability is a proposal, not an endpoint.

**As of the Phase 1 redaction work (`Fast_Fetch/redact.py`), the route list splits by
port.** `/api/data`, `/api/sitemap`, `/api/fetch`, `/api/health-check`, `/api/heal` and
`/api/v1/rules` answer on the operator loopback port (`RADD_INTERNAL_PORT`, default 8081)
and `404` on the public port; every other route answers on both, but the public one is a
projected view with no `source_site`/`service`/`final_url` and signed opaque handles where
a row id used to be. Provenance is suppressed at the HTTP edge only — the SQLite ledger is
unchanged by design (API_V2.md §16.9).

Three facts worth carrying across accounts because they have repeatedly misled
agents and app developers:

- **`?type=anime` is answered by the server as of 2026-10-28** (this bullet said
  "zero rows" and is now stale). A loopback check that day returned
  `GET /api/v1/posts?type=anime&limit=3` → 200, `total` 5,307, first row
  *Avatar: Seven Havens* with `is_animated=1`. The app consumes the flag through
  `Post.isAnimated`; `displayTypeLabel` in `CatalogEnums.kt` now distinguishes
  anime from the `content_type` family in `PosterCard`, `HeroCarousel` and
  `DetailScreen`.
- **`/api/heal` is routed but broken.** The handler builds a payload and never
  writes it to the socket (viewer.py:2100-2108); `protocol_version` is `HTTP/1.1`,
  so clients hang. Use the `fast_fetch.py heal` CLI.
- **The API is entirely unauthenticated and unencrypted.** No API key, token,
  session, or rate limiting exists anywhere in `viewer.py`; `send_json()` emits
  `Access-Control-Allow-Origin: *` (viewer.py:2037), `start_server()` defaults to
  `0.0.0.0` (viewer.py:2211), and the Oracle host serves plain HTTP with no TLS.
  Nothing behind this API should be described as private or secured. **Two claims in this
  paragraph were stale and are corrected from the code as it stands at `e96bf84`:** `send_json()` no
  longer emits `Access-Control-Allow-Origin: *` — it calls `cors_headers_for()` (viewer.py:3009), and
  `CORS_ALLOW_ORIGINS` is an **empty** `frozenset` (redact.py:1283), so a refused origin gets no
  header at all; and `start_server()` defaults to `host="127.0.0.1"`, not `0.0.0.0`
  (viewer.py:3558). What remains true is the exposure that matters: the public edge is plain HTTP
  with no TLS, no API key, no session and no rate limit. On `/api/v1/stats`, commit `34f22c6` made the
  projection stamp an adult-excluded family (`works_safe`, `adult_works`, `releases_safe`,
  `links_safe`, `links_active_safe`, `links_resumable_safe`) beside the unfiltered counters and stopped
  publishing `active_sources` equal to `sources` while `links_by_state` still said 3,456,460 links were
  `unchecked`. The **running process still serves the old shape** (`{"posts": 116922, ...,
  "active_sources": 3783959}` measured 05:12) because that is code, not data, and activation is
  `systemctl restart radd-stream` — an action the owner reserved. Data changes, by contrast, reach the
  live API with no restart: I watched `total` move 134,815 → 135,779 as merges landed.
  **Both halves of that paragraph are superseded as of 2026-10-29 19:14:31.** The unit was
  OOM-killed and systemd's auto-restart brought it back *on the then-dirty `/opt/radd-stream` tree*,
  which is not a deploy path anyone authorized (see the incident note in
  `docs/SESSION_CHECKPOINT.md`). Measured on loopback at 21:35 with no restart by me:
  `/api/v1/stats` → `{"posts": 103580, "releases": 1648807, "sources": 3705474, "active_sources": 0,
  "resumable_sources": 0, "temporary_sources": 195842, "sources_by_state": {"dead": 21, "unchecked":
  3696910, "unknown": 8543}}` in 4.9 ms — i.e. the **adult-excluded stamped shape is live now**, and
  `posts` there is `COUNT(cat_works WHERE adult_clause)` (`_counted_stats` in `viewer.py`), 116,922
  works minus 13,342 flagged = **103,580**, verified read-only against the catalog at 21:35. That is
  why `stats.posts` (103,580, works) and `/api/v1/posts` `total` (135,731, posts) are *different
  numbers on purpose*: one counts canonical works, the other counts post rows. They are not a
  discrepancy and no filter is missing. The same restart also made the live response carry the
  `subtitled` field, so production code is currently ahead of, and different from, every sha on
  `master`/`main` — it cannot be reproduced from the pushed tree.

## Oracle Ubuntu backend

- Oracle is intended to host the **Python backend/API and persistent SQLite data**. Android APKs are built on GitHub Actions; the Android app is not an Oracle server process.
- A read-only check on 2026-10-17 found `radd-stream.service`, Nginx, and Supervisor active; the backend listens on `127.0.0.1:8080` behind Nginx on port 80. `/opt/radd-stream` has no `.git` metadata, and its deployed source does not match the 11 fetched Git revisions compared. See `ORACLE_DEPLOYMENT.md` and `docs/SESSION_CHECKPOINT.md`; its host-key record is TOFU, not OCI Console verified.
- The runbook describes a planned layout of Nginx on port 80 proxying to the API on loopback port 8080, with SQLite data outside the code checkout. Recheck the host before relying on this layout. Public API routes need the documented allowlist; do not expose the resolver/fetch routes or port 8080.
- Do not deploy from an agent branch or directly copy untested edits to a live server. A production deployment requires a verified host key, the runbook's setup checklist, a tested deployment process, health checks, and a recovery route.

### Scheduled jobs (re-read 2026-10-28 20:05 PKT)

- `radd-backup-hf.timer` (installed and enabled 2026-10-28) runs daily at 03:40 PKT plus up to
  10 min random delay: `/usr/local/bin/backup-hf` → `Fast_Fetch/backup_manager.py --dir
  /home/ubuntu/radd-stream-data --hf` → HF dataset `radddao/radd-stream-backups`. The unit supplies
  `HF_DATASET_REPO` (the wrapper only prints a default; `backup_manager.py` skips the upload when the
  variable is empty) and loads `HF_TOKEN` by running under `bash -ic`, because `~/.bashrc` exports it
  after its non-interactive guard. `Nice=19` + idle IO keep it off the API's back. Archives land in
  `/home/ubuntu/radd-stream-backups` (~1.8 GB each) and are **not rotated** — 131 GB was free on
  2026-10-28, so a month of dailies fits with room; revisit retention before that.
- `radd-autocrawl.timer` (6-hourly fleet sync → `merge_fleet.py` → HF backup) was found installed and
  **stopped on 2026-10-28 20:01** to keep the frozen production DB untouched and the single vCPU free
  for agent gates. Its merge target is `merged_catalog_20261025.db` and every site logs
  "already merged, skipping", but step 1's `fast_fetch.py sync --site all` can write sitemap/domain
  metadata into `fast_fetch.db`. Re-enable with `sudo systemctl enable --now radd-autocrawl.timer`
  only after the owner lifts the freeze. A drop-in (`20-hf-env.conf`) now runs it under `bash -ic` so
  its backup step sees `HF_TOKEN`; a second drop-in adds `Nice=10`.

## Cross-agent save and resume

1. Start with root `AGENTS.md`, `SESSION.md`, `CHANGELOG.md`, and this map; then read the relevant subsystem guide and continuity log. Preserve `Fast_Fetch/DAO.md` unless the user explicitly asks to change it.
2. Work in an agent/task branch. Keep changes focused and verify each coherent milestone.
3. After every tested milestone, update `docs/SESSION_CHECKPOINT.md`, stage only reviewed paths, inspect the staged diff, commit, and push the branch. If checks cannot finish before the session ends, push a clearly labeled WIP checkpoint to the task branch and record pending checks; do not wait for a quota warning.
4. Never stage or push `.replit`; it is local-only and ignored. Use the temporary Git askpass procedure in `ORACLE_DEPLOYMENT.md`. Do not run or restore `push.py`, `github_push.py`, or `emergency_push.py`; their former versions used broad per-file GitHub API writes and could target `main`, and the warning stubs that replaced them have since been deleted from the tree.
5. On push failure, preserve the local commit and checkpoint, report the exact failure, and do not claim synchronization.

## Secrets

The user's permanent choice is to configure `GITHUB_TOKEN` and `ORACLE_SSH_KEY` as environment variables in Replit Configurations, not Replit Secrets. Verify presence by name in each workspace; never read or print values, ask to move them, place them in Git URLs/arguments/logs/files, or copy them to Oracle. These variables do not automatically transfer to another account or to GitHub Actions. GitHub Actions needs its own repository/environment secrets for any signed APK or automated Oracle workflow.

## Research sources

- [AGENTS.md](https://agents.md/) — portable repository instructions for coding agents.
- [GitHub Actions secrets](https://docs.github.com/en/actions/security-for-github-actions/security-guides/using-secrets-in-github-actions) and [workflow artifacts](https://docs.github.com/en/actions/tutorials/store-and-share-data).
- [GitHub Gradle build/test guidance](https://docs.github.com/en/actions/tutorials/build-and-test-code/java-with-gradle) and [deployment environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/control-deployments).
- [Oracle Ubuntu compute example](https://docs.oracle.com/en-us/iaas/Content/developer/apache-on-ubuntu/01oci-ubuntu-apache-summary.htm).
