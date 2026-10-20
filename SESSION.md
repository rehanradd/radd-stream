# 🎭 SESSION.md — Agent Session Protocol

> **Every AI agent** (Antigravity, Replit Agent, Copilot, Cursor, Claude, GPT, Gemini)
> MUST follow this protocol. No exceptions.

---

## 🔴 Before You Write a Single Line of Code

Read these files **in order**:

```
1. AGENTS.md              ← repo map, what exists, current status
2. docs/PROJECT_MAP.md and docs/SESSION_CHECKPOINT.md ← portable current state
3. CHANGELOG.md           ← history + known mistakes
4. Fast_Fetch/CONTINUITY.md   ← backend session log + next task
   AND/OR App/AGENTS.md       ← app session log + next task
```

Then run the health check:

```bash
python setup_check.py
python -S Fast_Fetch/test_database.py    # expected: 36+ tests, all OK
python -S Fast_Fetch/test_vidout.py      # expected: 6 tests, all OK
```

**If any test fails at session START — do NOT proceed. Fix the issue first, then continue.**

---

## ✅ Session Start Block (Fill In)

Copy this block into your working notes at the start of each session:

```
╔══════════════════════════════════════════════════════════╗
║  SESSION START                                           ║
╠══════════════════════════════════════════════════════════╣
║  Date (UTC)  :                                           ║
║  Agent       :  [e.g. Antigravity / Replit Agent / GPT]  ║
║  Branch      :  [task/agent branch — never main]         ║
║  Working on  :  [Backend / App / Both]                   ║
║  Task        :  [one-sentence description of what you'll do] ║
║  Last SHA    :  [from Git history / checkpoint]          ║
║  Tests start :  [e.g.  36/36 DB  +  6/6 VIDOUT  = OK]   ║
╚══════════════════════════════════════════════════════════╝
```

---

## ✅ Session End Block (Fill In)

Before ending your session, update `docs/SESSION_CHECKPOINT.md` and append
the subsystem-specific note to `Fast_Fetch/CONTINUITY.md` (backend) or
`App/AGENTS.md` (app):

```
╔══════════════════════════════════════════════════════════╗
║  SESSION END                                             ║
╠══════════════════════════════════════════════════════════╣
║  Built       :  [bullet list of features/fixes added]    ║
║  Files changed: [list all modified/created files]        ║
║  Tests end   :  [e.g.  40/40 DB  +  6/6 VIDOUT  = OK]   ║
║  Branch/SHA  :  [Git branch and exact commit SHA]        ║
║  GitHub push :  [success / failed + exact reason]        ║
║  Checks      :  [pass / fail / not run]                  ║
║  Next agent  :  [ONE clear sentence — what to do next]   ║
╚══════════════════════════════════════════════════════════╝
```

---

## 🚀 Checkpoint and Push Promptly

Do this after each verified milestone, not only at session end. This reduces
the amount of work at risk if a tool stops or its usage limit is reached.

1. Update `docs/SESSION_CHECKPOINT.md` with progress, checks, and the next action.
2. Review `git status --short --branch`, `git diff --check`, and changed paths.
3. Stage only the files for this milestone and inspect the staged changes:

```bash
git add -- path/to/reviewed-file another/reviewed-file
git diff --cached --check
git diff --cached --stat
git commit -m "type: short description"
```

4. Push using the temporary Git askpass procedure in `ORACLE_DEPLOYMENT.md` (or `./safe_push.sh`). Agents are authorized to push verified milestones directly to `main` so CI runs automatically. Never force-push, use `git add -A`, or put a token in a URL or command argument.
5. If checks cannot finish before a session ends, make a clearly labeled WIP
   checkpoint commit on the task branch and list unrun checks. WIP commits must
   not be merged or deployed until checks pass.
6. If push fails, keep the local commit, record the exact failure in the
   checkpoint, and tell the next agent what to retry. Do not claim it synced.

**Do not run or restore `push.py`, `github_push.py`, or `emergency_push.py`.**
Their previous versions used broad per-file GitHub API writes and could target
`main`; the current files are no-op warning stubs. Git commits preserve an
atomic history and can be retried safely.

---

## ⚡ Quick Command Reference

### Backend
```bash
# All offline tests (required before/after changes)
python -S Fast_Fetch/test_database.py
python -S Fast_Fetch/test_vidout.py

# Live 10-site audit (~2 min, hits real URLs)
python Fast_Fetch/test_all_sites.py

# Start REST API + web dashboard (port 8080)
python Fast_Fetch/viewer.py

# Sync all site sitemaps to DB
python Fast_Fetch/fast_fetch.py sync --site all

# Fetch a single post URL
python Fast_Fetch/fast_fetch.py fetch "https://vegamovies.gallery/some-post/"

# Search the local DB
python Fast_Fetch/fast_fetch.py search "Inception"

# System health check
python setup_check.py
```

### App
```bash
# Android builds run only when a root-level .github/workflows/ workflow exists
# on the current branch. Check docs/PROJECT_MAP.md before expecting CI.
# On current GitHub main, App/.github/workflows/ is nested and not discovered.
# Debug APK:   github.com/radddao/radd-stream/actions → click run → Artifacts
# Release APK: github.com/radddao/radd-stream/releases

# Create a signed release:
# 1. Edit App/app/build.gradle.kts → bump versionName
# 2. Commit and push the reviewed change using the Git procedure above
# 3. Create and push a release tag only after its release build is verified
```

### Git checkpoint status
```bash
# Check current changes and branch before staging:
git status --short --branch
git log -5 --oneline
```

---

## 🚫 The DO-NOT List (Mistakes Already Made)

Read `CHANGELOG.md` → "Known Mistakes" for full details with code examples.

| # | Never Do This | Why |
|---|---|---|
| 001 | Regex with `r'...\\'...'` (mixed quotes in single-quoted raw string) | SyntaxError on import |
| 002 | Re-enable a legacy API uploader | Previous versions could write broad file sets to `main`; current files are no-op warning stubs |
| 003 | Push code without running tests | Breaks next agent's session |
| 004 | Edit `viewer.py` without `import viewer` smoke test | Silent SyntaxError at runtime |
| 005 | Write "Latest" as commit SHA in CONTINUITY.md | Useless for debugging regressions |
| 006 | Hardcode `C:\Users\...` or `/home/runner/...` absolute paths | Breaks cross-platform |
| 007 | `import requests` in any `Fast_Fetch/*.py` file | Zero pip policy — stdlib only |
| 008 | Commit `database_view.html` or any file >5 MB | Bloats git history |

---

## 🗂️ Agent Responsibility Cheatsheet

| Task | Backend Agent | App Agent |
|---|---|---|
| Read AGENTS.md | ✅ | ✅ |
| Read CHANGELOG.md (mistakes) | ✅ | ✅ |
| Read CONTINUITY.md | ✅ | — |
| Read App/AGENTS.md | — | ✅ |
| Run test_database.py + test_vidout.py | ✅ | — |
| Use only Python stdlib | ✅ | ❌ (app = Kotlin/Gradle) |
| Update CONTINUITY.md session log | ✅ | — |
| Update App/AGENTS.md session log | — | ✅ |
| Update `docs/SESSION_CHECKPOINT.md` and subsystem log | ✅ | ✅ |
| Commit and push the reviewed branch via `ORACLE_DEPLOYMENT.md` | ✅ | ✅ |
