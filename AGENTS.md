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
  (`Fast_Fetch/fast_fetch.py:4598`), so an unlabelled adult title still gets flagged.
  **The invariant, measured against the code and pinned by tests**
  (`Fast_Fetch/test_redact.py::AdultDenialOnBothPortsTests`,
  `Fast_Fetch/test_database.py::KeyLevelAdultIdentityTests`): no public surface may list *or play* a
  flagged row. Enforced today by `redact.adult_clause` (`Fast_Fetch/redact.py:1077`) inside
  `api_v1_get_posts` (`Fast_Fetch/viewer.py:2780`), by the per-post bail at `viewer.py:887` and
  `:2956`, by `redact.link_is_adult` (`redact.py:1083`) on the stream/download redirectors — which
  answers True for an unknown link id so a typo cannot play either — and by nginx, which allow-lists
  only the public routes. To a public client a flagged row is indistinguishable from a row that never
  existed: the same `not_found`, the same status code, no hint that a flag caused the denial.
  **One exception, deliberately, and it is not a user-facing display surface:** the operator panel.
  `DASHBOARD_HTML` (`viewer.py:917`) reads `/api/data`, which this process 404s on the public port,
  is served only on the loopback operator port, and 403s at the public edge; the trust boundary there
  is the loopback interface, not `RADD_ADMIN_TOKEN` (the token guards `/admin`, and `/` answers 200 on
  `8081` without it — measured 2026-10-29 05:47, see the table below). `fetch_database_payload`
  (`viewer.py:557`) documents `full` as "the operator-only mode (loopback port): raw ledger rows", and
  the panel renders a `18+ ADULT` badge (`viewer.py:1919`) because an operator auditing flag coverage
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
  **Cross-key twins that already exist are reconciled at each merge, on evidence only:**
  `merge_catalogs.reconcile_adult_on_merge()` folds a work's flagged row onto its siblings only
  when `is_adult_title()` still reproduces the flag from the source row's own text — a raw key-level
  `MAX` would have hidden 407 mainstream works — and journals every flip in `adult_fold_journal`,
  which `backfill_adult_key.py --undo` reverses; `--audit` reports how much of a catalog rests on
  flags no rule can reproduce. The catalog-wide pass is the owner's call.
  **Residual, measured 2026-10-29 on the production catalog:** 953 works are flagged in the projection
  while 1,190 distinct ledger rows for the same title and year are still public under a *different*
  key. No key-level law can reach those; they need the re-key migration, which is planned and not
  attempted here. Under the correct identity (`generate_canonical_key(clean_title, year)`) that
  residual is **2,600 keys carrying both a flagged and an unflagged row, 3,486 publicly served rows
  under those keys, and a 69,773-row re-key blast radius** (measured 2026-10-29); the earlier
  442-keys / 455-rows figures describe the slug-keyed catalog before that reconciliation. The
  per-site concentration and the key-pair examples moved verbatim to
  [`docs/ARCHIVE_ROOT_AGENTS_20261101.md`](docs/ARCHIVE_ROOT_AGENTS_20261101.md).
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
| `KEYSTORE_BASE64` | ⚠️ **CONFIGURED; build step fails** (run 41233720264) | Android signing keystore (base64 encoded) |
| `KEY_STORE_PASSWORD` | ⚠️ **CONFIGURED, never exercised** | Keystore file password |
| `KEY_ALIAS` | ⚠️ **CONFIGURED, never exercised** | Key alias inside keystore (`raddstream`) |
| `KEY_PASSWORD` | ⚠️ **CONFIGURED, never exercised** | Key password |

**Measured 2026-10-29 17:55 — this retires the claim that the four keystore variables are "GitHub
Repo Secrets".** `GET /repos/rehanradd/radd-stream/actions/secrets` returns
`{"total_count": 0, "secrets": []}`, from a lane whose repo `permissions` are
`{admin: true, push: true}`, so it is a real answer and not a permission artifact. Proof by
execution: `workflow_dispatch` on `🚀 Release — Sign & Publish APK + AAB` (workflow `398476978`,
run `40876596427`) ended `failure` after **10 s**, against the **7m 02s** `BUILD SUCCESSFUL` the
Android build takes (measured on run `40874380668`), so it died at the
`🗝️ Verify signing secrets are present` preflight (`release.yml:53`) and never reached a build,
a signature check, or the publish step — nothing was released. That preflight is why exercising this
is safe. **Consequence:** CI cannot produce a signed release APK/AAB until the owner adds all four
values under GitHub → Settings → Secrets → Actions. **Do not generate a replacement keystore to work
around it** — a different signing key makes every later upgrade incompatible with the first install,
and there is no installed base to protect yet, so the owner's key is the only correct one.
**Available today with no secret at all:** `🔨 CI — Android Build & Test` uploads a **debug APK** on
every green run (`📤 Upload debug APK` succeeded at `2caadb3`) — debug-signed and installable for the
device verification every doc still marks "pending".

**UPDATE (measured 2026-10-30 22:53, re-measured 2026-10-31 07:5x):** the repository owner generated
all four release-signing secrets, backed the keystore up on the Oracle VM
(`/home/ubuntu/raddstream-release.jks`), and configured them in GitHub Actions Secrets — confirmed by
execution: run `41104217171` cleared the `🗝️ Verify signing secrets are present` preflight that had
killed the 2026-10-29 attempt in 10 s. **What that sentence did *not* earn is retired: the workflow is
not producing signed artifacts.** `GET /releases` is `[]`, every release run in history is a
`failure`, `tag v1.0.0` resolves to a trunk point that predates the adult merge-time fold.
**No signed APK or AAB has ever existed for this product.** The read cause, from the run log:
`java.util.Base64` refusing the **stored `KEYSTORE_BASE64` value** (length not a clean base64
quantum — padding lost in the paste), failing during *configuration* in `signingConfigs`
(`App/app/build.gradle.kts:120`, `BUILD FAILED in 4s`) before any Kotlin compiled; the keystore file
itself round-trips. **So the fix is owner-side secret re-entry, not a build-script edit.**
**Moving or re-cutting a tag is an owner action: no agent may create, move or delete a tag.**
Per-run receipts: [`docs/SPEC_AGENTS_MEASURED_NOTES.md`](docs/SPEC_AGENTS_MEASURED_NOTES.md).

**Backend agents**: use `GITHUB_TOKEN` for GitHub operations and `ORACLE_SSH_KEY` only when connecting to Oracle. Read [`ORACLE_DEPLOYMENT.md`](ORACLE_DEPLOYMENT.md) first.
**App agents**: the debug build needs no secrets; the *signed release* needs the 4 keystore secrets above **and** a release workflow that builds — which it does not have. A task that needs an installable build today takes the **debug APK** from `🔨 CI — Android Build & Test`.
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
   a git tag (and it cannot succeed anyway — `/actions/secrets` is `[]`); never commit from or
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
2. **Quote a test count from the log that executed it, or from `git show <sha>:Fast_Fetch/<module> | grep -cE '^\s+def test_'` — never from prose here.** This line read 76, then 124, then 133 inside a week; the counts, the shas and the run ids that produced them are in [`docs/SPEC_AGENTS_MEASURED_NOTES.md`](docs/SPEC_AGENTS_MEASURED_NOTES.md). Naming two modules is a quick gate, not item 1.
3. Append a session log to `Fast_Fetch/CONTINUITY.md`
4. Push with Git over HTTPS using the temporary askpass helper in [`ORACLE_DEPLOYMENT.md`](ORACLE_DEPLOYMENT.md); do not use the legacy per-file API push scripts

**Run the gate in a worktree at the tip, never in `/opt/radd-stream`** — the live tree is a
diverged older draft, and a "green" measured in it is a weaker claim than CI's.

### For App Sessions:
1. Ensure Gradle builds pass locally OR wait for GitHub Actions green check
2. Append a session log to `App/AGENTS.md` (Session History section)
3. Push with Git over HTTPS using the temporary askpass helper in [`ORACLE_DEPLOYMENT.md`](ORACLE_DEPLOYMENT.md)
4. ~~Tag a release~~ **superseded by Fleet Resource Guardrail rule 5: no agent creates, moves or
   pushes a tag — the owner's call alone — and CI cannot sign one today.**

---

## 🚦 Current Project Status

| Component | Status |
|---|---|
| Backend: ingestion, SQLite catalog, resolver, REST API | ✅ **Deployed and running on this host** |
| Android App: Phase 1 (catalog/search) and Phase 2 (details/playback) | ✅ Implemented; device verification pending |
| GitHub Actions | ✅ Enabled and running; repo-root workflows `state=active` |
| Release signing | ❌ No signed artifact has ever existed; `GET /releases` is `[]` — installable bytes = the CI debug APK |

The per-sha receipts behind those four rows — the CI verdicts per trunk ref, the never-discovered
duplicates under `App/.github/workflows` and the PR-gate line numbers, the five failed release runs
and where each one died — moved verbatim to
[`docs/ARCHIVE_ROOT_AGENTS_20261101.md`](docs/ARCHIVE_ROOT_AGENTS_20261101.md). A status row that
quotes a run id is stale the moment another lane pushes; the row that survives is the claim, and the
evidence belongs where it can age without contradicting anyone.

The current Oracle host and its HTTP-only limitations are documented in
[`ORACLE_DEPLOYMENT.md`](ORACLE_DEPLOYMENT.md). The backend is **already deployed there and is the
running system** — do not treat it as hypothetical, and never copy untested or WIP code onto it.

**Do not misread an empty CI run list.** `backend-ci.yml`'s push trigger is `branches: ["**"]` with
`paths: ["Fast_Fetch/**", ".github/workflows/backend-ci.yml"]`, so a push that touches neither feeds
no backend run — that is the path filter working, not the account. `.github/workflows/ci.yml`
triggers on `App/**`, so a push editing `App/AGENTS.md` also starts the ~7-minute hosted Android
build; that is CI's cost on a hosted runner, not this box's. **The rule is the method, not the
shape: read the workflow's own trigger block before predicting whether CI will run** — a
`total_count: 0` run list is evidence about the filter, never about the account. If you need to know
whether CI can run, query `/actions/permissions` and print what it says. The two measurements behind
this paragraph (the 2026-10-29 permissions reading, the 2026-10-30 `dc73ac7` trigger re-measure, and
the `paths-ignore` variant that could not be reproduced against the tree or the object store) are in
[`docs/ARCHIVE_ROOT_AGENTS_20261101.md`](docs/ARCHIVE_ROOT_AGENTS_20261101.md) — which is precisely
why the method above is the law and not a quoted shape.

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
# ⛔ NO AGENT CREATES OR PUSHES A TAG — Fleet Resource Guardrail rule 5, the owner's call alone.
# A tag publishes nothing today anyway: the release workflow cannot sign (`/releases` is `[]`).
# An installable build right now = the debug APK from the 🔨 CI — Android Build & Test artifacts.
# GitHub discovers workflows only under the repository-root .github/workflows/; the duplicates that
# sat under App/.github/workflows were never discovered and are deleted.
```

The five failed release runs and which step killed each one moved verbatim to
[`docs/ARCHIVE_ROOT_AGENTS_20261101.md`](docs/ARCHIVE_ROOT_AGENTS_20261101.md).

---

## 🔗 Key Links

| Resource | URL |
|---|---|
| GitHub Repo | https://github.com/rehanradd/radd-stream |
| GitHub Actions | https://github.com/rehanradd/radd-stream/actions |
| GitHub Releases | https://github.com/rehanradd/radd-stream/releases |
| Oracle HTTP host (measured 2026-10-29) | `http://92.4.95.252/` — plain HTTP, and `location /` proxies **code-server** (the web IDE), not the app |
| Backend REST API (publicly reachable) | `http://92.4.95.252/api/v1/posts` — nginx allow-lists only `/api/v1/posts`, `/api/v1/stream`, `/api/v1/stats`, `/api/v1/download`, `/api/v1/search/by-media`, `/api/v1/app/remote-config`, `/api/v2/account*`, and static `/download/`; `^~ /api/` 403s everything else, including all v2 catalog routes and `/api/data` |
| Operator panel | **loopback-only, not token-gated** — `fast_fetch.py serve` binds `127.0.0.1:8080` and `127.0.0.1:8081`, nginx forwards neither, the token guards `/admin` alone, and `/` answers 200 on `8081` with no token at all. Do not describe the dashboard as token-gated; describe it as loopback-only, which is what is true. Route-by-route access law: [`docs/ADMIN_PANEL_ACCESS.md`](docs/ADMIN_PANEL_ACCESS.md); the 2026-10-29 05:47 measurement moved verbatim to [`docs/ARCHIVE_ROOT_AGENTS_20261101.md`](docs/ARCHIVE_ROOT_AGENTS_20261101.md) |
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
