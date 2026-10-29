# 🤖 AGENTS.md — Root Project Guide for All AI Agents

> **READ THIS ENTIRE FILE FIRST** before touching anything.
> This is the single top-level source of truth for the `radd-stream` monorepo.
> Every AI agent (Antigravity, Replit Agent, Copilot, Cursor, Claude, GPT, Gemini — all of you) must follow this.
> For current cross-account state, also read `docs/PROJECT_MAP.md` and `docs/SESSION_CHECKPOINT.md`.

---

## 🗺️ Repo Map

```
radd-stream/                        ← repo root
│
├── AGENTS.md                       ← THIS FILE — start here
├── README.md                       ← public-facing project description
├── DISCLAIMER.md                   ← legal / framing notice
├── setup_check.py                  ← system sanity check for backend
├── run.sh / run.bat                ← one-command launchers (backend)
├── requirements.txt                ← empty (zero pip deps)
├── .gitignore                      ← excludes local .replit, databases, build and cache files
├── ORACLE_DEPLOYMENT.md             ← Oracle access, GitHub auth, and deployment runbook
├── docs/
│   ├── AI_HANDOFF_PROMPT.md         ← short prompt to resume in another AI tool/account
│   ├── AGENT_BOOTSTRAP.md           ← project context and safe onboarding steps
│   ├── PROJECT_MAP.md               ← verified locations, branches, CI, and server status
│   └── SESSION_CHECKPOINT.md        ← concise cross-agent progress and next action
│
├── Fast_Fetch/                     ← 🐍 PYTHON BACKEND (data engine + REST API)
│   ├── AGENTS.md                   ← deep backend-specific agent guide (read this for backend work)
│   ├── DAO.md                      ← eternal mission directive
│   ├── CONTINUITY.md               ← session log + milestone tracker (update every session)
│   ├── API_V2.md                   ← catalog v2 data model + REST contract (read before designing any endpoint)
│   ├── SITES.md                    ← per-site scraping reference
│   ├── SETUP.md                    ← setup instructions for backend
│   ├── ANDROID_INTEGRATION.md      ← how Android app consumes the backend
│   ├── fast_fetch.py               ← MAIN ENGINE (6,513 lines, stdlib only)
│   ├── viewer.py                   ← REST API + dashboard HTTP server
│   ├── config.py                   ← project-level constants
│   ├── test_database.py            ← 124 offline unit tests (measured 2026-10-29)
│   ├── test_vidout.py              ← 6 VIDOUT-specific tests
│   └── test_all_sites.py           ← live 10-site audit
│
└── App/                            ← 📱 ANDROID APP (Kotlin + Jetpack Compose)
    ├── AGENTS.md                   ← deep app-specific agent guide (read this for app work)
    ├── README.md                   ← app architecture overview
    ├── .github/workflows/          ← nested here; GitHub requires repo-root .github/workflows
    ├── docs/
    │   ├── PLAN.md                 ← 3-phase feature roadmap
    │   ├── TECH_STACK.md           ← Kotlin/Compose/Media3 rationale
    │   └── BUILD_PLAN.md           ← full CI/CD strategy (no local Android Studio needed)
    ├── design/
    │   ├── DESIGN_SYSTEM.md        ← colors, fonts, spacing, components
    │   └── SCREENS.md              ← ASCII wireframes for 7 screens (NavGraph registers 13 routes)
    └── app/src/                    ← Gradle Android app source (Kotlin)
```

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
  flagged row. Enforced today by `redact.adult_clause` (`Fast_Fetch/redact.py:1073`) inside
  `api_v1_get_posts` (`Fast_Fetch/viewer.py:2534`), by the per-post bail at `viewer.py:709` and
  `:2710`, by `redact.link_is_adult` (`redact.py:1079`) on the stream/download redirectors — which
  answers True for an unknown link id so a typo cannot play either — and by nginx, which allow-lists
  only the public routes. To a public client a flagged row is indistinguishable from a row that never
  existed: the same `not_found`, the same status code, no hint that a flag caused the denial.
  Proved live on this host: `/api/v1/posts/159` (a flagged post) is 404 on loopback and at the public
  edge, `/api/m3u?id=159` returns 0 bytes where `/api/m3u?id=158` returns a real playlist, and
  `/api/m3u` is 403 at the edge.
  **One exception, deliberately, and it is not a user-facing display surface:** the operator panel.
  `DASHBOARD_HTML` (`viewer.py:739`) reads `/api/data`, which this process 404s on the public port,
  is served only on the loopback operator port, and 403s at the public edge; the trust boundary there
  is the loopback interface, not `RADD_ADMIN_TOKEN` (the token guards `/admin`, and `/` answers 200 on
  `8081` without it — measured 2026-10-29 05:47, see the table below). `fetch_database_payload`
  (`viewer.py:494`) documents `full` as "the operator-only mode (loopback port): raw ledger rows", and
  the panel renders a `18+ ADULT` badge (`viewer.py:1681`) because an operator auditing flag coverage
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
  `Fast_Fetch/backfill_adult_key.py` reconciles rows written before the law existed (report, then
  `--apply`, then `--apply --projection`) and prints the public total before and after, refusing to
  commit unless the total dropped by exactly the number of rows it flipped.
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
  **The 7,663 is the wide measure; the ledger-text measure is narrower, and the difference matters
  to anyone reading a candidate list.** One read-only pass over `posts` on the production catalog
  (2026-10-29, `audit_adult_flags.classify`, no vaults) splits the 15,068 flagged rows into
  **9,069 true-adult in their own stored text, 4,246 version-word-only, 1,753 with no pattern
  evidence in the ledger at all** across 14,931 distinct `canonical_key`s. Only the 4,246 are
  un-flag candidates — the rest of the owner's 7,663 count adult words that live outside
  `title`/`clean_title`/`slug`/`url` (tags, `raw_meta`, site-wide rules), which the ledger alone
  cannot see. Freeing them leaves **39 mixed keys** (one copy served, one still hidden) and 4 rows
  are blocked by a true-adult sibling.
  **Four patterns still hide mainstream works, and none of them was touched** because the standing
  instruction was to weaken nothing else: `\bhunters\b` (128 rows, 127 matched by nothing else —
  e.g. *KPop Demon Hunters*, *Transformers Prime: Beast Hunters – Predacons Rising*),
  `\brabbit\b` (61, 56 — *Wallace & Gromit: The Curse of the Were-Rabbit*, *1001 Rabbit Tales*),
  `\bnaughty\b` (169, 149) and `\badult\b` (1,480, 82 — *Shin-chan: The Adult Empire Strikes Back*).
  By the rule above, a version word may not be a pattern; these four are not version words either,
  but they name a genre noun, not a person, studio, or act, and each has a title in the catalog that
  proves the false positive. Removing one is the owner's exposure decision, not an agent's — and
  `audit_adult_flags.py` reports what each one hides before anyone writes.
  Nothing in this section weakens the public rule. A test that reaches a flagged row through any public
  route, or a flagged link through stream or download on either port, is P0.

---

## 🔐 Secrets & Credentials

| Credential variable | Where to find it | What it does |
|---|---|---|
| `GITHUB_TOKEN` | Replit Configurations (environment variable; user says not Secrets) | GitHub access from Replit; use the temporary Git askpass flow in `ORACLE_DEPLOYMENT.md` |
| `ORACLE_SSH_KEY` | Replit Configurations (environment variable; user says not Secrets) | SSH private key for `ubuntu@92.4.95.252`; use only via a temporary 0600 file |
| `KEYSTORE_BASE64` | ⚠️ **NOT CONFIGURED — measured, see note below** | Android signing keystore (base64 encoded) |
| `KEY_STORE_PASSWORD` | ⚠️ **NOT CONFIGURED** | Keystore file password |
| `KEY_ALIAS` | ⚠️ **NOT CONFIGURED** | Key alias inside keystore |
| `KEY_PASSWORD` | ⚠️ **NOT CONFIGURED** | Key password |

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

**Backend agents**: use `GITHUB_TOKEN` for GitHub operations and `ORACLE_SSH_KEY` only when connecting to Oracle. Read [`ORACLE_DEPLOYMENT.md`](ORACLE_DEPLOYMENT.md) first.
**App agents**: the debug build needs no secrets; the *signed release* needs the 4 keystore secrets, which are **currently absent** (measured above).
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
- Do **not** recreate or restore `push.py`, `github_push.py`, `emergency_push.py`, `push_github.py`, or `safe_push.sh`. They were GitHub Contents API uploaders that could write broad file sets directly to `main`; `safe_push.sh` additionally staged every path it found (`git add -u` plus all untracked files), committed without a test gate, and pushed through the `origin` remote whose URL still carries the owner's unrevoked token. All five were reduced to no-op warning stubs and have now been deleted from the tree — their history stays in Git, their danger stays retired. A local commit remains recoverable if a normal push fails—record the failure and next step in the checkpoint rather than claiming it synced.
- Oracle deployment is separate from a GitHub branch push. Only deploy through a verified, tested release path after CI passes; do not copy untested or WIP code to the live host.

---

## 📋 Agent Continuity Protocol (BOTH sub-projects)

Every agent — no matter how short the session — MUST do this before ending:

### For Backend Sessions:
1. Run CI's **17-module** list, one invocation each (791 tests, 0 failures at `9859b8a`).
2. `test_database.py` alone is **133** at the tip and `test_vidout.py` is 6/6 — but do not substitute that 3-module quick gate for item 1.
3. Append a session log to `Fast_Fetch/CONTINUITY.md`
4. Push with Git over HTTPS using the temporary askpass helper in [`ORACLE_DEPLOYMENT.md`](ORACLE_DEPLOYMENT.md); do not use the legacy per-file API push scripts

**Run the gate in a worktree at the tip, not in `/opt/radd-stream`.** Measured 2026-10-29 18:55: the
live tree is checked out at its own `bf9e565` and its `Fast_Fetch/test_database.py` contains **76**
`def test_` methods, while the pushed tip (`6e54909`) contains **124**. Same command, two different
gates, because `/opt/radd-stream` is a diverged older draft carrying other lanes' uncommitted edits
(56 dirty paths right now, `AGENTS.md` staged). A "green" from the live tree is a weaker claim than
CI's, and can silently test deleted code.

### For App Sessions:
1. Ensure Gradle builds pass locally OR wait for GitHub Actions green check
2. Append a session log to `App/AGENTS.md` (Session History section)
3. Push with Git over HTTPS using the temporary askpass helper in [`ORACLE_DEPLOYMENT.md`](ORACLE_DEPLOYMENT.md)
4. Tag a release with `git tag vX.Y.Z && ...` if a milestone is complete

---

## 🚦 Current Project Status

| Component | Status | Phase |
|---|---|---|
| Backend: ingestion, SQLite catalog, resolver, REST API | ✅ **Deployed and running on this host** — `systemctl is-active radd-stream` → `active`, `fast_fetch.py serve --host 127.0.0.1:8080` behind Nginx | Complete |
| Android App: server setup, metadata catalog, search | ✅ Implemented; device verification pending | Phase 1 |
| Android App: details and playback | ✅ Implemented (Media3 playback, favorites, keeps, VIP screen); device verification pending | Phase 2 |
| GitHub Actions | ✅ **Enabled and running** — `/repos/rehanradd/radd-stream/actions/permissions` returns `{"enabled": true, "allowed_actions": "all"}` (measured 2026-10-29 03:54 host time; 40 runs recorded). The earlier "⛔ disabled at the account level" line in this file was **wrong** and is retired. All three repo-root workflows are `state=active`: `🐍 Backend CI`, `🔨 CI — Android Build & Test`, `🚀 Release — Sign & Publish APK + AAB`. The copies under `App/.github/workflows` are inert (GitHub only reads repo-root). | Gate is live |
| CI health (both sides) | 🐍 **Backend CI is GREEN** — `completed success` on both `master` and `main` at `f0c1ca3`, and green on every adult-fix commit (`ab78849`, `8ad9862`, `6b28e48`, `f6637c9`, `c4a1302`). 🔨 **Android CI IS NOW GREEN — FIRST TIME EVER** — measured 2026-10-29 at `2caadb3`, `completed success` on **both** `master` and `main` (run `40874380668`); all 14 steps green, including the single combined `./gradlew :app:assembleDebug :app:testDebugUnitTest :app:lintDebug` step, `BUILD SUCCESSFUL in 7m 2s`, `:app:testDebugUnitTest` executed, no lint errors emitted. The previous "still RED: 636 tests / 9 failed / 23 lint errors" line was a **misdiagnosis**: every fix for it existed in `5446771`, but that commit was **local-only on a `master` that had diverged** from `origin/master` (`git merge-base --is-ancestor 5446771 origin/master` → NO; 2 local-only vs 26 remote-only) and `ci.yml` triggers on `App/**`, so nothing had fed it since `11742e0` (2026-10-28T21:21, failure). **It was unfed, not red** — I cherry-picked it onto `f0c1ca3` as `2caadb3` and pushed to both refs. The trap that hid this stays true: `ScreenSnapshotTest` and `PosterCardProvenanceTest` are excluded from every local arm64 run (Robolectric #9166), so only the hosted runner can judge them. `tags: 0`, `releases: 0` still, and signing is genuinely blocked on the four absent keystore secrets (see the measured note in Secrets above) — a debug APK is available from CI meanwhile. **Re-measured 2026-10-29 22:5x via `/actions/runs?per_page=6`** (91 runs total): 🐍 Backend CI is `completed success` on **both** `master` and `main` at `9859b8a` and at `6f7e3a0` — i.e. green on the 17-module list this file now documents, judged by the hosted runner and not only by this box. 🔨 Android is green on `master` (`2caadb3`) but **red on the live app lane**: branch `q1-ad-cadence` failed its combined Gradle step at `99472e0` (run `40917741872`, step `🏗️🧪🔍 Gradle: debug APK + unit tests + lint (single invocation)`, no annotations attached — read the job log, not the summary) with a retry `in_progress` at `217e8cd`. A green `master` does not mean the app lane is safe to merge. | Release blocked on owner secrets only |

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

---

## ⚡ Quick Commands Reference

### Backend
```bash
# From repo root: /opt/radd-stream  (Oracle VM)

# Run offline tests — one module per invocation; this runner ignores extra names.
# There are 68 `test_*.py` modules under Fast_Fetch/ and Fast_Fetch/importers/ — 48 at the
# Fast_Fetch/ root and 20 in importers/ (measured 2026-10-29 at `5c331d6` with
# `find . -name 'test_*.py' -not -path './.git/*' | wc -l`; re-measure it, do not trust this
# number, it has already gone stale twice in one day).
# These three are the standing *quick* gate — they are NOT what CI judges.
python3 -S Fast_Fetch/test_database.py    # 133 tests at the tip (was 124, was 76 — re-count)
python3 -S Fast_Fetch/test_vidout.py      # 6 tests
python3 -S Fast_Fetch/importers/test_host_resolvers.py   # 171 tests

# The REAL gate is exactly what backend-ci.yml runs — 17 modules, one per invocation. As of
# `9859b8a` those 17 are CI's own list; the two extra suites the older version of this block
# described (`importers/test_host_resolvers.py`, `importers/test_convert_mp4moviez.py`) are NOT
# in CI and the 17th slot is not what this file used to claim:
#   test_database test_vidout test_catalog_v2 test_release_descriptor test_link_health
#   test_link_state test_evidence_writeback test_api_v2 test_redact test_tiers
#   test_catalog_api test_provenance_stamping test_merge_catalogs test_site_scout
#   test_backup_manager test_usage_stats test_operator_isolation
# Measured 2026-10-29 at `9859b8a`: 17/17 rc=0, **791 tests, 0 failures**, and GitHub's own
# `🐍 Backend CI — Stdlib Python` reported `completed success` on both `master` and `main` for
# that sha and for `6f7e3a0` — so this list and this count are corroborated by the runner, not
# just by a local box. `test_usage_stats.py` is 94 tests and `test_operator_isolation.py` is 28;
# run them with `RADD_USER_STATE_DB` pointed at a fixture, never the live state file.
# Measured earlier the same day: the 3-module quick gate stayed green while CI was red for five
# pushes, because it omits test_evidence_writeback.py and test_merge_catalogs.py. Run CI's list.
# Note `test_all_sites.py` is deliberately excluded from CI (`backend-ci.yml:33`) — it is a live
# 10-site network audit, not an offline test.

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
# GitHub only discovers workflows under the repository-root .github/workflows/.
# Root now carries ci.yml, release.yml and backend-ci.yml; the copies still sitting
# in App/.github/workflows are inert and are being retired.

# To create a signed release:
# 1. Tag the commit
git tag v1.0.0
# 2. Push the tag with Git using the temporary askpass helper in ORACLE_DEPLOYMENT.md,
#    against the explicit clean URL — never `origin`, whose stored remote still
#    embeds a leaked credential until the owner revokes it:
git push https://github.com/rehanradd/radd-stream.git v1.0.0
# → GitHub Actions builds signed APK + creates Release automatically

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
