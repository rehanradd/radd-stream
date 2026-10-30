# 🤖 AGENTS.md — Root Project Guide for All AI Agents

> **READ THIS ENTIRE FILE FIRST** before touching anything.
> This is the single top-level source of truth for the `radd-stream` monorepo.
> Every AI agent (Antigravity, Replit Agent, Copilot, Cursor, Claude, GPT, Gemini — all of you) must follow this.
> For current cross-account state, also read `docs/PROJECT_MAP.md` and `docs/SESSION_CHECKPOINT.md`.

---

## 🗺️ Repo Map

```
AGENTS.md          ← THIS FILE: the law. Fast_Fetch/ ← 🐍 Python backend. App/ ← 📱 Android (Kotlin/Compose).
docs/              ← SPEC + rotated LOG (SPEC_*.md, checkpoints/). Fast_Fetch/CONTINUITY.md and
                     docs/SESSION_CHECKPOINT.md are open-items indexes, not logs — but they are
                     119 and 54 lines, not the ≤20 this file used to claim. The guard enforces
                     ≤120 lines / ≤12 KB each; grow them deliberately, never by accretion.
```

The annotated inventory (every file, every doc, with what it holds) moved to
[`docs/SPEC_REPO_MAP.md`](docs/SPEC_REPO_MAP.md). Read it when you need to know *where* something lives.

---

## 🧭 Which Part Are You Working On?

| If you are working on... | Read this next |
|---|---|
| Backend (data ingestion, REST API, SQLite) | [`Fast_Fetch/AGENTS.md`](Fast_Fetch/AGENTS.md) + [`Fast_Fetch/CONTINUITY.md`](Fast_Fetch/CONTINUITY.md) |
| Android app (Kotlin, Compose, ExoPlayer) | [`App/AGENTS.md`](App/AGENTS.md) |
| Both / unsure | Read this file fully, then navigate to the relevant sub-guide |

---

## 🏛️ Project Identity

### What This Project Does
Radd Stream is a Python media-catalog and source-link aggregation/resolution service with a REST API and a Kotlin Android client. The backend collects public catalog metadata, stores it in SQLite, diagnoses source endpoint latency, and can resolve source links. The Android app browses metadata from the API.

Describe the code's behavior accurately to users and tools. Do not disguise its purpose or frame work to bypass another service's safety rules.

### What This Is NOT
- Not a hosting service
- Not a download manager
- Not a DRM circumventer
- Adult (18+) content is **stored but never displayed to a user**: scrapers ingest 100% of each
  site's catalog including 18+ titles, flagging them via the `is_18_plus` column
  (`is_18_plus=1`) present in every site staging database. The flag is set at storage time and
  `save_scraped_data` re-derives it from the title as a row becomes a post
  (`Fast_Fetch/fast_fetch.py:4426`), so an unlabelled adult title still gets flagged.
  **The invariant, measured against the code and pinned by tests**
  (`Fast_Fetch/test_redact.py::AdultDenialOnBothPortsTests`,
  `Fast_Fetch/test_database.py::KeyLevelAdultIdentityTests`): no public surface may list *or play* a
  flagged row. Enforced today by `redact.adult_clause` (`Fast_Fetch/redact.py:1077`) inside
  `api_v1_get_posts` (`Fast_Fetch/viewer.py:2779`), by the per-post bail at `viewer.py:886` and
  `:2955`, by `redact.link_is_adult` (`redact.py:1083`) on the stream/download redirectors, and by
  nginx, which allow-lists only the public routes. **The law is that an unknown link id must be
  refused at that gate too**, so a typo and a flagged title are indistinguishable. Measured on trunk
  `6a441ec` the gate is fail-OPEN for a missing row — its last line is `bool(row and row[0])`, so an
  unknown id answers **False** and reaches the resolver, whose 404 `no_playable_source` is the only
  thing stopping a typo from playing (pinned by
  `test_operator_adult_projection.py::test_an_unrecognized_link_id_reaches_the_resolver_today`).
  qoder3 owns the fail-closed flip; the docstring and that test flip with it, in the same change.
  To a public client a flagged row is indistinguishable from a row that never
  existed: the same `not_found`, the same status code, no hint that a flag caused the denial.
  **One exception, deliberately, and it is not a user-facing display surface:** the operator panel.
  `DASHBOARD_HTML` (`viewer.py:916`) reads `/api/data`, which this process 404s on the public port,
  is served only on the loopback operator port, and 403s at the public edge; the trust boundary there
  is the loopback interface, not `RADD_ADMIN_TOKEN` (the token guards `/admin`, and `/` answers 200 on
  `8081` without it — measured 2026-10-29 05:47, see the table below). `fetch_database_payload`
  (`viewer.py:556`) documents `full` as "the operator-only mode (loopback port): raw ledger rows", and
  the panel renders a `18+ ADULT` badge (`viewer.py:1918`) because an operator auditing flag coverage
  has to see which rows carry the flag. That is the *stored* half of this rule, shown to the person who
  owns the storage — never a playable link, and never a public list. `/api/v1/stream` and
  `/api/v1/download` deny a flagged link **on the operator port too**, with the same uniform
  `not_found`: seeing a flagged row is the panel's job, handing out its bytes is nobody's. If a change
  ever lets the panel emit a stream or download token for a flagged row, that is a defect, not a
  policy. `full` is a property of the server instance, never a client-supplied header or query flag.
  **The flag belongs to the work, not to one row.** The adult law is applied per row while media
  identity is per `canonical_key`, so one film filed twice — one copy flagged, one not — was hidden at
  one address and publicly served at the other: 442 keys held both, and 455 unflagged twins were
  reachable (`4 Play` id 23519, hindilinks4u, answered `/api/v1/posts?q=4+Play` while the same film
  from filmyhit was correctly hidden). That is fixed here, not by adding another `WHERE` clause:
  `fast_fetch.inherit_key_adult()` reconciles `MAX(is_18_plus)` across every row sharing the key,
  inside the write that set the flag, bounded by `idx_posts_canonical_key`; the degenerate `unknown`
  key is refused so one titleless page cannot hide unrelated titles; and a *new* row is filed under
  `generate_canonical_key(clean_title, year)` instead of the scraper's page slug, so two sites writing
  one film now write one key. Stored rows keep the key they were filed under — re-keying them touches
  ids `releases` reference and is its own reviewed migration.
  **Residual, measured 2026-10-29 on the production catalog:** 953 works are flagged in the projection
  while 1,190 distinct ledger rows for the same title and year are still public under a *different*
  key (`suzume-2022` vs `suzume_2022`, `puli-2015` vs `puli_2015`), concentrated in filmyzilla (437),
  9xmovies (344), moviezguru (190) and hindilinks4u (151). No key-level law can reach those; they need
  the re-key migration, which is planned and not attempted here. Under the correct identity
  (`generate_canonical_key(clean_title, year)`) that residual is **2,600 keys carrying both a flagged
  and an unflagged row, 3,486 publicly served rows under those keys, and a 69,773-row re-key blast
  radius** (measured 2026-10-29); the earlier 442-keys / 455-rows figures describe the slug-keyed
  catalog before that reconciliation.
  **The pattern list is a policy, and it was wrong once.** `\buncut\b` and `\bunrated\b` sat in
  `ADULT_TITLE_PATTERNS` and seven per-site lists until 2026-10-29: they are *edition* labels, not
  adult markers, and desicinemas puts them on mainstream releases — 7,663 of the 15,068 flagged rows
  (51%) were justified only by them. Under a key-level law a false row-flag hides an entire work, so
  the cost of one bad pattern multiplied. Both words are gone from every list, and the rule for
  adding one is now enforced by a test, not by opinion: **a pattern belongs here only if it names a
  person, a studio, or an act — never a version, a quality, a rating, or a release format — and only
  if you can write a test that proves it catches a case the other patterns miss.** Use
  `Fast_Fetch/audit_adult_flags.py` (report-by-default; writes require the owner's `--owner-go`) to
  see what a flag rule actually hides before shipping it. Production still carries the 7,663 until
  the owner runs that un-flag pass.
  Nothing in this section weakens the public rule. A test that reaches a flagged row through any public
  route, or a flagged link through stream or download on either port, is P0.
  The *evidence* behind this law — the live-host proof rows, `backfill_adult_key.py`'s apply procedure,
  the wide-vs-ledger flag measures and the four contested tokens — moved to
  [`docs/SPEC_ADULT_FLAG_EVIDENCE.md`](docs/SPEC_ADULT_FLAG_EVIDENCE.md). The law is above; the receipts are there.

---

## 🔐 Secrets & Credentials

| Credential variable | Where to find it | What it does |
|---|---|---|
| `GITHUB_TOKEN` | Replit Configurations (environment variable; user says not Secrets) | GitHub access from Replit; use the temporary Git askpass flow in `ORACLE_DEPLOYMENT.md` |
| `ORACLE_SSH_KEY` | Replit Configurations (environment variable; user says not Secrets) | SSH private key for `ubuntu@92.4.95.252`; use only via a temporary 0600 file |
| `KEYSTORE_BASE64` | ✅ **CONFIGURED & ACTIVE** (measured 2026-10-30) | Android signing keystore (base64 encoded) |
| `KEY_STORE_PASSWORD` | ✅ **CONFIGURED & ACTIVE** (measured 2026-10-30) | Keystore file password |
| `KEY_ALIAS` | ✅ **CONFIGURED & ACTIVE** (measured 2026-10-30) | Key alias inside keystore (`raddstream`) |
| `KEY_PASSWORD` | ✅ **CONFIGURED & ACTIVE** (measured 2026-10-30) | Key password |

**HISTORICAL, superseded 2026-10-30 — measured 2026-10-29 17:55, when GitHub held no signing
secret.** The four keystore variables were not "GitHub Repo Secrets" then:
`GET /repos/rehanradd/radd-stream/actions/secrets` returned
`{"total_count": 0, "secrets": []}`, from a lane whose repo `permissions` are
`{admin: true, push: true}`, so it was a real answer and not a permission artifact. Proof by
execution: `workflow_dispatch` on `🚀 Release — Sign & Publish APK + AAB` (workflow `398476978`,
run `40876596427`) ended `failure` after **10 s**, against the **7m 02s** `BUILD SUCCESSFUL` the
Android build takes (measured on run `40874380668`), so it died at the
`🗝️ Verify signing secrets are present` preflight (`release.yml:53`) and never reached a build,
a signature check, or the publish step — nothing was released. That preflight is why exercising this
is safe. **Consequence at the time:** CI could not produce a signed release APK/AAB until the owner
added all four values under GitHub → Settings → Secrets → Actions. **Do not generate a replacement
keystore to work around it** — a different signing key makes every later upgrade incompatible with
the first install, and there is no installed base to protect yet, so the owner's key is the only
correct one.
**Available with no secret at all:** `🔨 CI — Android Build & Test` uploads a **debug APK** on
every green run (`📤 Upload debug APK` succeeded at `2caadb3`) — debug-signed and installable for the
device verification every doc still marks "pending".

**CURRENT (measured 2026-10-30 22:53, recorded by `63396c1`):** All four release signing secrets (`KEYSTORE_BASE64`, `KEY_ALIAS`, `KEY_PASSWORD`, `KEY_STORE_PASSWORD`) were generated, backed up on Oracle VM (`/home/ubuntu/raddstream-release.jks`), and configured in GitHub Actions Secrets by the repository owner. Release tag `v1.0.0` was pushed, and the official release workflow (`🚀 Release — Sign & Publish APK + AAB`) is active. The empty-list measurement above is history, not the current state: do not re-quote it as a live blocker.

**Backend agents**: use `GITHUB_TOKEN` for GitHub operations and `ORACLE_SSH_KEY` only when connecting to Oracle. Read [`ORACLE_DEPLOYMENT.md`](ORACLE_DEPLOYMENT.md) first.
**App agents**: the debug build needs no secrets; the *signed release* needs the 4 keystore secrets, and all four were configured and verified on 2026-10-30 (`63396c1`).
Verify only whether the two configured variable names are present; never read or print their values, put them in Git URLs or command arguments, commit them, or copy them to Oracle. Do not ask the user to move them to Replit Secrets.

---

## 🔁 Cross-Agent Checkpoints and Safe Git Pushes

- Read `docs/PROJECT_MAP.md` and `docs/SESSION_CHECKPOINT.md` at the start of every session; update the checkpoint after every independently useful milestone.
- **`/opt/radd-stream` is the live deployment tree, not a workspace.** The unit runs
  `WorkingDirectory=/opt/radd-stream` + `ExecStart=/usr/bin/python3 -S /opt/radd-stream/Fast_Fetch/fast_fetch.py
  serve`, so whatever is checked out there is what the service loads on its next start, and several
  lanes keep uncommitted work in it at the same time. Work in your own worktree
  (`git worktree add /tmp/<yourlane> <sha>`) and push that sha; do **not** commit from or reset
  `/opt/radd-stream`. If you find its tree carrying a superseded draft of code that is already pushed,
  say so in the checkpoint instead of committing over it — a silent revert of a pushed fix is exactly
  what this rule exists to prevent.
- Do not wait for a quota warning. Test, commit, and push each completed milestone to the task/agent branch promptly. If a session may end before tests finish, save a clearly labeled WIP commit to that branch, record unrun checks, and do not merge or deploy it.
- Stage only reviewed paths (`git add <paths>`), inspect the staged names/diff, and keep secrets, databases, APKs, build outputs, and uploaded chat files out of commits. Never use `git add -A` or force-push. Per owner authorization, agents may push verified, tested milestones directly to `main` so automated CI triggers and autonomous progress is seamless.
- Treat `.replit` as local-only sensitive configuration: do not inspect its values or stage, commit, or push it. It is ignored and untracked. The user chose to leave historical copies intact; do not rewrite history unless they explicitly change that decision.
- Use Git over HTTPS with the temporary askpass procedure in `ORACLE_DEPLOYMENT.md`. Never put credentials in URLs, command arguments, files, or logs.
- Do **not** recreate or restore `push.py`, `github_push.py`, `emergency_push.py`, `push_github.py`, or `safe_push.sh`. They were GitHub Contents API uploaders that could write broad file sets directly to `main`; `safe_push.sh` additionally staged every path it found (`git add -u` plus all untracked files), committed without a test gate, and pushed through the `origin` remote whose URL still carries the owner's unrevoked token **(measured 2026-10-30: that clause is now stale as a description of this box — `remote.origin.url` is a clean `https://github.com/rehanradd/radd-stream.git` with no userinfo, and neither `/opt/radd-stream/.git/config` nor `/home/ubuntu/.gitconfig` matches a token pattern. The token itself is still live: it reads `/user` as the owner's own login. So the credential is unrevoked while being un-stored here — revoke it, and keep using the askpass flow rather than relying on the remote's URL to be clean).** All five were reduced to no-op warning stubs and have now been deleted from the tree — their history stays in Git, their danger stays retired. A local commit remains recoverable if a normal push fails—record the failure and next step in the checkpoint rather than claiming it synced.
- Oracle deployment is separate from a GitHub branch push. Only deploy through a verified, tested release path after CI passes; do not copy untested or WIP code to the live host.

---

## 🚦 Fleet Resource Guardrail — measured on this box 2026-10-30

**This host has ONE vCPU** (`nproc` = 1) and the agent lanes are the load, not production. The 01:30
measurement behind that sentence (load 10.2, 167.7 % of the machine attributed to five `qodercli` lanes
while `radd-stream` used 0.4 % of a core) moved to [`docs/SPEC_AGENTS_MEASURED_NOTES.md`](docs/SPEC_AGENTS_MEASURED_NOTES.md).
Full per-route costs are in [`docs/CAPACITY_MEASURED.md`](docs/CAPACITY_MEASURED.md).

CPU saturation only adds latency. **Memory saturation is what kills this host** — it already has
one recorded OOM-kill of `radd-stream` (19:14:31, auto-restarted onto an uncommitted tree). So the
rule is memory-led, not load-led:

1. **HARD FLOOR — stop heavy work at once** if any of: `MemAvailable < 1500 MB`,
   `SwapFree < 800 MB`, or the service cgroup `MemoryCurrent > 1200 MB`. Check with
   `awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo` and
   `systemctl show radd-stream -p MemoryCurrent`. Note tonight: cgroup 528 MB / peak 897 MB,
   while the **process RSS is only ~58 MB** — the rest is the 6.4 GB catalog in reclaimable page
   cache, which is not the danger; a climbing RSS is.
2. **HEAVY WORK is frozen while load > 4**: anything that scans the 6.4 GB catalog, any crawl or
   scrape loop, any Gradle invocation, any bulk merge. Do not start a new one. If you are mid-run
   and it is resumable, checkpoint, pause, and say so in your CONTINUITY entry rather than
   grinding silently.
3. **LIGHT WORK is always allowed**: editing code and docs, offline unit tests on in-memory or
   `/tmp` fixtures, short-timeout loopback API reads, git operations.
4. **Never probe a route or query of unknown cost with a sample size > 1.** Probe once with a
   short `-m`, then decide. This rule exists because the orchestrator itself sent N=4 serial
   requests to `/api/v1/stats` on this single core and burned **22.5 server CPU-seconds**, having
   assumed it was a cheap counter.
5. **Unchanged absolutes:** never restart/reload/stop `radd-stream.service`; never create or push
   a git tag (it is the owner's release decision, and since 2026-10-30 the four signing secrets are
   live, so a tag really does publish a signed APK/AAB — that is the reason no agent touches one,
   not that CI would fail); never commit from or
   reset `/opt/radd-stream`, which is the live deployment tree; no Gradle until the owner confirms
   load < 0.5; never put a credential in a URL, argv, file or log.
6. **If your task needs a heavy read, do not run it — queue it.** Write the exact command, the
   expected cost, and the number you want into your CONTINUITY entry as a quiet-window action.
   Designing a probe is worth as much as running one when the box is at load 10.
7. **A slow local test module is not a slow test module — never exclude one on this box's timing.**
   Measured 2026-10-30 on the same file (`Fast_Fetch/test_admin_panel.py`, 65 tests): **266.312 s
   here at load 6.9, while consuming 0.43 CPU-seconds**, and **1 s on the hosted runner** (backend
   run `40954291359`, step `21:03:47 → 21:03:48`, success). The assertions block on page-cache I/O
   behind five lanes; they do not compute. So the local number is a symptom of the guardrail, not a
   property of the code, and only CI's per-step timing decides whether a suite belongs in the gate.

---

## 📋 Agent Continuity Protocol (BOTH sub-projects)

Every agent — no matter how short the session — MUST do this before ending:

### For Backend Sessions:
1. **Run exactly the gate `.github/workflows/backend-ci.yml` runs — and count it correctly.**
   Count the suites with `grep -c 'name: 🧪' .github/workflows/backend-ci.yml`, **never** with
   `grep 'run: python3 -S'`: the latter silently undercounts, because a step written
   `run: time python3 -S …` is still a suite (measured 2026-10-30 at `56e743b`: 26 `🧪` steps, 25
   `python3 -S` matches — the missing one is `test_admin_panel.py`). The list itself is a snapshot
   that grows; the workflow file is the only source of truth, so read it instead of quoting a number
   from this file. The historical per-run module lists and test counts moved to
   [`docs/SPEC_AGENTS_MEASURED_NOTES.md`](docs/SPEC_AGENTS_MEASURED_NOTES.md).
2. `test_database.py` alone is **133** at the tip and `test_vidout.py` is 6/6 — but do not substitute that 3-module quick gate for item 1.
3. Append a session log to `Fast_Fetch/CONTINUITY.md`
4. Push with Git over HTTPS using the temporary askpass helper in [`ORACLE_DEPLOYMENT.md`](ORACLE_DEPLOYMENT.md); do not use the legacy per-file API push scripts

**Run the gate in a worktree at the tip, never in `/opt/radd-stream`** — the live tree is a diverged
older draft and a "green" from it is a weaker claim than CI's. The measurement that proved it is in
[`docs/SPEC_AGENTS_MEASURED_NOTES.md`](docs/SPEC_AGENTS_MEASURED_NOTES.md).

### For App Sessions:
1. Ensure Gradle builds pass locally OR wait for GitHub Actions green check
2. Append a session log to `App/AGENTS.md` (Session History section)
3. Push with Git over HTTPS using the temporary askpass helper in [`ORACLE_DEPLOYMENT.md`](ORACLE_DEPLOYMENT.md)
4. Tag a release with `git tag vX.Y.Z && ...` if a milestone is complete
   — **superseded by the Fleet Resource Guardrail rule 5: this is the owner's call alone, no agent
   may create or push a tag, and CI cannot sign one today anyway (`/actions/secrets` is `[]`).**

---

## 🚦 Current Project Status

| Component | Status | Phase |
|---|---|---|
| Backend: ingestion, SQLite catalog, resolver, REST API | ✅ **Deployed and running on this host** — `systemctl is-active radd-stream` → `active`, `fast_fetch.py serve --host 127.0.0.1:8080` behind Nginx | Complete |
| Android App: server setup, metadata catalog, search | ✅ Implemented; device verification pending | Phase 1 |
| Android App: details and playback | ✅ Implemented (Media3 playback, favorites, keeps, VIP screen); device verification pending | Phase 2 |
| GitHub Actions | ✅ **Enabled and running** — `/actions/permissions` → `{"enabled": true, "allowed_actions": "all"}`; all three repo-root workflows are `state=active`, and the never-discovered duplicates under `App/.github/workflows` have been deleted (that removal also retired the repo's only `pull_request` trigger — there is no PR gate; CI runs on push). The retired "disabled at the account level" claim and the full CI-health measurement history (per-sha run verdicts on both trunk refs, the Android `unfed-not-red` misdiagnosis, the Robolectric #9166 trap) are in [`docs/SPEC_AGENTS_MEASURED_NOTES.md`](docs/SPEC_AGENTS_MEASURED_NOTES.md). | Gate is live |
| Release signing | ✅ **Active & Configured** — All 4 keystore secrets verified; tag `v1.0.0` pushed and signed release pipeline active. Release artifacts published at `https://github.com/rehanradd/radd-stream/releases`. | Live |

The current Oracle host and its HTTP-only limitations are documented in
[`ORACLE_DEPLOYMENT.md`](ORACLE_DEPLOYMENT.md). The backend is **already deployed there and is the
running system** — do not treat it as hypothetical, and never copy untested or WIP code onto it.

**Do not misread an empty CI run list.** `backend-ci.yml` triggers on `push: branches: ["**"]` with
`paths: ["Fast_Fetch/**", ".github/workflows/backend-ci.yml"]`, so a **docs-only push legitimately
produces zero runs** — that is the path filter working, not the account. Measured 2026-10-29:
`/actions/permissions` → `{"enabled": true, "allowed_actions": "all"}` and `/actions/runs` carries 40+
runs. This file previously claimed "Actions is disabled at the account level" on the strength of a
filtered `total_count: 0`; that claim cost a week of unverified pushes and must not be repeated. If
you need to know whether CI can run, query `/actions/permissions` and print what it says.

**⚠️ Re-measured 2026-10-30 at `dc73ac7`, and this is what the filter is today:**
`backend-ci.yml`'s push trigger is `branches: ["**"]` with
`paths: ["Fast_Fetch/**", ".github/workflows/backend-ci.yml"]` (md5 of the file matches
`git show dc73ac7:.github/workflows/backend-ci.yml`). Consequence for a docs-only change: editing
root `AGENTS.md` or `docs/**` alone feeds **nothing**, but the diet touches `Fast_Fetch/**`
(`Fast_Fetch/AGENTS.md`, `Fast_Fetch/CONTINUITY.md`, `Fast_Fetch/checkpoints/`,
`Fast_Fetch/test_docs_invariants.py`) so it does feed CI. `.github/workflows/ci.yml` triggers on
`App/**`, so a push that edits `App/AGENTS.md` also starts the ~7-minute hosted Android build. That
is CI's cost on a hosted runner, not this box's. **The rule is the method, not the shape: read the
workflow's own trigger block before predicting whether CI will run** — a `total_count: 0` run list is
evidence about the filter, never about the account. (A `paths-ignore` variant of this file was
quoted once tonight and could not be reproduced against the tree or the object store; treat it as
never having existed, which is precisely why the method above is the law and not a quoted shape.)

---

## ⚡ Quick Commands Reference

### Backend
```bash
# From repo root: /opt/radd-stream  (Oracle VM)
# But run gates in your own worktree (`git worktree add /tmp/<yourlane> <sha>`), never in the live tree.

# The gate is the module list in .github/workflows/backend-ci.yml — one `python3 -S` invocation per
# suite. Count it with `grep -c 'name: 🧪' .github/workflows/backend-ci.yml`, NOT with
# `grep 'run: python3 -S'` (a `run: time python3 -S …` step is still a suite and is missed).
# Run one at a time, under `nice -n 19`, per the Fleet Resource Guardrail.
python3 -S Fast_Fetch/test_database.py     # quick gate only — not what CI judges
python3 -S Fast_Fetch/test_vidout.py

# Live site audit (writes to temp DB)
python Fast_Fetch/test_all_sites.py

# System health check
python setup_check.py

# Start REST API behind a reverse proxy (binds only to loopback)
python Fast_Fetch/fast_fetch.py serve --host 127.0.0.1 --port 8080

# Sync sitemaps for all sites
python Fast_Fetch/fast_fetch.py sync --site all

# Search the catalog
python Fast_Fetch/fast_fetch.py search "Inception"

# Push to GitHub with the temporary askpass helper in ORACLE_DEPLOYMENT.md
```

### App (no local Android Studio needed)
```bash
# GitHub only discovers workflows under the repository-root .github/workflows/. The duplicates
# that used to sit under App/.github/workflows were never discovered and are now deleted.
#
# ⛔ NO AGENT CREATES OR PUSHES A TAG. That was a technical dead end on 2026-10-29
# (/actions/secrets returned []) and is not one now: the four keystore secrets were configured
# on 2026-10-30, so a tag triggers a real signed release. Tagging is therefore the owner's call
# for a stronger reason, not a weaker one. History: docs/SPEC_AGENTS_MEASURED_NOTES.md.

# Download APK: github.com/rehanradd/radd-stream/actions (debug)
#               github.com/rehanradd/radd-stream/releases (release)
```

---

## 🔗 Key Links

| Resource | URL |
|---|---|
| GitHub Repo | https://github.com/rehanradd/radd-stream |
| GitHub Actions | https://github.com/rehanradd/radd-stream/actions |
| GitHub Releases | https://github.com/rehanradd/radd-stream/releases |
| Oracle HTTP host (measured 2026-10-29) | `http://92.4.95.252/` — plain HTTP, and `location /` proxies **code-server** (the web IDE), not the app |
| Backend REST API (publicly reachable) | `http://92.4.95.252/api/v1/posts` — nginx allow-lists only `/api/v1/posts`, `/api/v1/stream`, `/api/v1/stats`, `/api/v1/download`, `/api/v1/search/by-media`, `/api/v1/app/remote-config`, `/api/v2/account*`, and static `/download/`; `^~ /api/` 403s everything else, including all v2 catalog routes and `/api/data` |
| Operator panel — **measured 2026-10-29 05:47 on this host** | One process (pid of `fast_fetch.py serve`) listens on BOTH `127.0.0.1:8080` and `127.0.0.1:8081`; neither is bound beyond loopback and nginx forwards neither. Public `/admin` falls through to code-server and answers 401. On `8081`: `/admin` → **401 without `RADD_ADMIN_TOKEN`** (the gate is `admin_panel.route_get` → `_gate(peer, token)`), but `/` → **200 serving the 46,476-byte dashboard with no token at all**, and `/api/v1/stats` and `/api/v1/rules` also answer **200 on 8081 with a bogus bearer token**. So the trust boundary on the operator port is *the loopback interface*, not the token: the token guards `/admin` only. On `8080` the same paths differ — `/` is a 1,355-byte page, `/client` is the 20,510-byte PWA, `/api/v1/rules` is **404**. Do not describe the dashboard as token-gated; describe it as loopback-only, which is what is true. |
| Mobile PWA `/client` | **not public** — measured 401 through nginx (same code-server fallthrough). It serves 200 only from `127.0.0.1:8080` |

---

## 🧠 Important Rules for ALL Agents

1. **Python stdlib only** for the backend — no `pip install` ever
2. **Kotlin / Jetpack Compose** for the Android app — standard Android toolchain
3. **Never break existing tests** — run them before and after changes
4. **Never delete parsers** — add, fix, extend — never remove
5. **Never hardcode absolute paths** — use `pathlib.Path` + `BASE_DIR`
6. **Log every session** in `CONTINUITY.md` (backend) or `App/AGENTS.md` (app)
7. **Push securely** — use Git over HTTPS with the temporary askpass helper; never embed or log a token
8. **Read CONTINUITY.md first** — it has the latest state, last commit SHA, and next tasks
9. **Per-Site Dedicated Staging Database Rule** — Scrape each streaming site into its own isolated staging database (e.g. `multimovies.db`, `vegamovies.db`). Never run mass scraper ingestion directly into the production catalog (`fast_fetch.db`). Once fully scraped and verified, merge into the unified catalog using `Fast_Fetch/merge_catalogs.py`.
10. **Zero Data Loss & Clone-Ready Fidelity Rule** — Extract 100% of available metadata (clean titles, TMDB posters & backdrops, year, synopsis, genres, ratings, audio languages, all seasons/episodes). Capture both embed/HLS watch servers and all download mirrors across all quality tiers. Never discard dead or failing links; record their status (`active`, `dead`, etc.) so link health is fully auditable and can be healed via JIT.
11. **Master-Disciple Local AI Law (Celestial Qi / Token Conservation)** — All agents have accepted the local Inner Disciple (`qwen2.5-coder:1.5b` running free on Oracle VM CPU via `/usr/local/bin/disciple` and `Fast_Fetch/disciple.py`). Whenever drafting code, generating regex patterns, writing unit test stubs, or building repetitive scraper helpers, always delegate the initial generation to local Qwen (0 cloud tokens), review the output for 100% Python stdlib compliance and security, and test it before committing. Never waste expensive cloud tokens on boilerplate.
