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
│   ├── fast_fetch.py               ← MAIN ENGINE (6,366 lines, stdlib only)
│   ├── viewer.py                   ← REST API + dashboard HTTP server
│   ├── config.py                   ← project-level constants
│   ├── test_database.py            ← 76 offline unit tests (measured 2026-10-29)
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
- Adult (18+) content is **stored but never displayed**: scrapers ingest 100% of each
  site's catalog including 18+ titles, flagging them via the `is_18_plus` column
  (`is_18_plus=1`) present in every site staging database. Every presentation surface
  (REST API, Android app, dashboard, M3U/stream routes) must filter out rows where
  `is_18_plus=1`. The flag is set at storage time; filtering is enforced at display time.

---

## 🔐 Secrets & Credentials

| Credential variable | Where to find it | What it does |
|---|---|---|
| `GITHUB_TOKEN` | Replit Configurations (environment variable; user says not Secrets) | GitHub access from Replit; use the temporary Git askpass flow in `ORACLE_DEPLOYMENT.md` |
| `ORACLE_SSH_KEY` | Replit Configurations (environment variable; user says not Secrets) | SSH private key for `ubuntu@92.4.95.252`; use only via a temporary 0600 file |
| `KEYSTORE_BASE64` | GitHub Repo Secrets | Android signing keystore (base64 encoded) |
| `KEY_STORE_PASSWORD` | GitHub Repo Secrets | Keystore file password |
| `KEY_ALIAS` | GitHub Repo Secrets | Key alias inside keystore |
| `KEY_PASSWORD` | GitHub Repo Secrets | Key password |

**Backend agents**: use `GITHUB_TOKEN` for GitHub operations and `ORACLE_SSH_KEY` only when connecting to Oracle. Read [`ORACLE_DEPLOYMENT.md`](ORACLE_DEPLOYMENT.md) first.
**App agents**: only need the 4 keystore secrets in GitHub → Settings → Secrets → Actions.
Verify only whether the two configured variable names are present; never read or print their values, put them in Git URLs or command arguments, commit them, or copy them to Oracle. Do not ask the user to move them to Replit Secrets.

---

## 🔁 Cross-Agent Checkpoints and Safe Git Pushes

- Read `docs/PROJECT_MAP.md` and `docs/SESSION_CHECKPOINT.md` at the start of every session; update the checkpoint after every independently useful milestone.
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
1. Run `python -S Fast_Fetch/test_database.py` (must be 76 tests passing; measured 2026-10-29)
2. Run `python -S Fast_Fetch/test_vidout.py` (must be 6/6)
3. Append a session log to `Fast_Fetch/CONTINUITY.md`
4. Push with Git over HTTPS using the temporary askpass helper in [`ORACLE_DEPLOYMENT.md`](ORACLE_DEPLOYMENT.md); do not use the legacy per-file API push scripts

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
| Android GitHub Actions | ⛔ **Actions is disabled at the account level**, so no workflow run is a gate right now. The three workflows are at repo-root `.github/workflows` (`ci.yml`, `release.yml`, `backend-ci.yml`) and are ready; the copies under `App/.github/workflows` are inert. Verification is a **local** offline Gradle run on this VM — see `App/AGENTS.md` §1a for the one-build-at-a-time rule. | Owner action needed |

The current Oracle host and its HTTP-only limitations are documented in
[`ORACLE_DEPLOYMENT.md`](ORACLE_DEPLOYMENT.md). The backend is **already deployed there and is the
running system** — do not treat it as hypothetical, and never copy untested or WIP code onto it.

---

## ⚡ Quick Commands Reference

### Backend
```bash
# From repo root: /opt/radd-stream  (Oracle VM)

# Run offline tests — one module per invocation; this runner ignores extra names.
# There are 60 `test_*.py` modules under Fast_Fetch/ and Fast_Fetch/importers/ (measured 2026-10-28);
# these three are the standing push gate.
python3 -S Fast_Fetch/test_database.py    # 76 tests
python3 -S Fast_Fetch/test_vidout.py      # 6 tests
python3 -S Fast_Fetch/importers/test_host_resolvers.py   # 171 tests

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
| Oracle HTTP host (after deployment) | `http://92.4.95.252/` (plain HTTP; see runbook) |
| Backend REST API (after deployment) | `http://92.4.95.252/api/v1/posts` |
| Mobile PWA (after deployment) | `http://92.4.95.252/client` |

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
