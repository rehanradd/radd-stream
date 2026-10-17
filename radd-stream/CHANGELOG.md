# 📋 CHANGELOG — radd-stream History

> Git commit history is authoritative. The table below is a historical summary.
> Do not use legacy API uploader scripts to write changes; use reviewed Git commits on a task branch.
> The "Known Mistakes" section records historical failures and current guidance.

---

## 📊 Change Log

| UTC Timestamp | Agent | Files Changed | Message |
|---|---|---|---|
| 2026-10-15T12:01Z | Emergency Push | `App/app/src/main/kotlin/com/raddstream/app/network/ApiProvider.kt`, `App/app/src/main/kotlin/com/raddstream/app/ui/components/PosterCard.kt`, `App/app/src/main/kotlin/com/raddstream/app/data/ServerSettingsRepository.kt`, `App/app/src/main/kotlin/com/raddstream/app/repository/CatalogRepository.kt` +21 more | emergency_push.py — AI agent cutoff recovery `7850c28` |
| 2026-10-14T17:54Z | Antigravity | `push.py`, `App/build.gradle.kts`, `App/gradle.properties`, `App/gradlew.bat` +39 more | feat(app): Phase 0 — Gradle skeleton complete: gradlew, icons, unit tests, all source files `7dd7182` |
| 2026-10-14T17:41Z | Antigravity | `emergency_push.py` | feat: add emergency_push.py — AI agent cutoff recovery script `877e9e4` |
| 2026-10-14T17:39Z | Antigravity | `push.py` | fix: use timezone-aware datetime in push.py (no more deprecation warning) `96778f4` |
| 2026-10-14T17:38Z | Antigravity | `push.py`, `CHANGELOG.md`, `SESSION.md` | chore: bootstrap auto-push tracking system (push.py v2, CHANGELOG, SESSION) `c71d4d8` |
| 2026-10-14T17:35Z | Antigravity | `push.py`, `CHANGELOG.md`, `SESSION.md` | chore: bootstrap auto-push tracking system v2 |
| 2026-10-14T17:26Z | Antigravity | `AGENTS.md`, `App/AGENTS.md`, `App/.github/workflows/ci.yml` +5 more | feat(app): App folder — planning docs, design system, CI/CD workflows, agent guides |
| 2026-10-14T16:43Z | Antigravity | `Fast_Fetch/viewer.py`, `Fast_Fetch/ANDROID_INTEGRATION.md`, `Fast_Fetch/CONTINUITY.md` | Milestone 4: mobile PWA client, HTML5 player modal, Android integration guide |
| 2026-10-14T16:35Z | Antigravity (Gemini Flash) | `Fast_Fetch/fast_fetch.py`, `Fast_Fetch/viewer.py`, `Fast_Fetch/test_database.py`, `Fast_Fetch/SITES.md` | Milestone 3: greenmotors + direct_cloud bridge resolvers `a65d528` |
| 2026-10-14T12:45Z | Antigravity | `Fast_Fetch/fast_fetch.py`, `Fast_Fetch/viewer.py`, `Fast_Fetch/test_database.py` | Milestones 1+2: JIT resolver, healing daemon, REST API v1, 10-site ingestion |
| 2026-10-14T11:00Z | Antigravity | `Fast_Fetch/fast_fetch.py`, `Fast_Fetch/test_database.py` | Session 6: category crawling HDHub4u + SSRMovies, 28 tests `beca84a` |
| 2026-10-14T10:13Z | Replit Agent | `Fast_Fetch/fast_fetch.py`, `Fast_Fetch/test_database.py` | Session 5: post_sources catalog, deduplication, 22 tests `beca84a` |
| 2026-10-14T09:57Z | Replit Agent | `Fast_Fetch/fast_fetch.py`, `Fast_Fetch/test_vidout.py`, `github_push.py` | Session 4: VIDOUT HLS unwrapping, GITHUB_TOKEN fix, 6 tests `994415b` |
| 2026-10-13T18:20Z | Antigravity | `README.md`, `DAO.md` | Session 3: historical framing change (superseded by accurate project descriptions) `cd1b32d` |
| 2026-10-13T17:58Z | Antigravity | `Fast_Fetch/fast_fetch.py`, `Fast_Fetch/AGENTS.md` | Session 2: MultiMovies deep-dive, 7 embed servers, episode crawling `072d5d2` |
| 2026-10-13T17:38Z | Antigravity | ALL | Session 1: initial project — 10 sites, SQLite schema, GitHub repo created `49aad24` |

---

## ⚠️ Known Mistakes — Read Before Coding

> Every mistake we made is recorded here. Future agents MUST read this before writing code.

---

### MISTAKE-001 — Regex quote escaping `FIXED`
**Symptom:** `SyntaxError` in Python regex patterns containing both `"` and `'`.
**Root cause:** Used `r'href=[\"\\'](url)[\"\\']]'` — backslash-escaped quotes in raw strings don't work.
**What broke:** 3 CDN unwrapper functions crashed on import.

```python
# ❌ BROKEN — causes SyntaxError
links = re.findall(r'href=[\"\\'](https?://...)[\"\\']', html)

# ✅ CORRECT — always triple-quote raw strings with mixed quotes
links = re.findall(r"""href=["'](https?://...)[\"']""", html)
```
**Rule → always use `r"""..."""` for regex patterns.**

---

### MISTAKE-002 — Legacy GitHub API uploaders missed files and targeted the wrong branch
**Symptom:** New files created during a session were never pushed to GitHub. Discovered next session when context was lost.
**Root cause:** `github_push.py` had an internal hardcoded list of known files only. Any file not on that list was silently ignored.
**What broke:** `App/.github/workflows/*.yml`, `App/AGENTS.md`, and `App/design/*.md` were created locally but never reached GitHub — took a separate API script to recover.

**Historical workaround:** `push.py` discovered more files, but it also wrote files one-by-one through the GitHub Contents API and defaulted to `main`; the emergency variant skips tests. All three API uploaders are now legacy and must not be run.

**Current rule:** use Git, stage only reviewed paths, create a normal commit on a task/agent branch, and push using the temporary askpass procedure in `ORACLE_DEPLOYMENT.md`.

---

### MISTAKE-003 — Pushing untested code `FIXED`
**Symptom:** A broken parser was pushed. The next agent pulled and tests failed immediately.
**Root cause:** No pre-push test gate. Old `github_push.py` never ran tests.

**Current rule:** run the relevant checks before a completed milestone push. If time is short, a clearly labeled WIP commit may be pushed to the task branch with pending checks recorded; never merge or deploy it until checks pass.

---

### MISTAKE-004 — viewer.py not smoke-tested after HTML edits `FIXED`
**Symptom:** Large DASHBOARD_HTML and MOBILE_CLIENT_HTML template strings were edited; an unclosed `{` in an f-string caused a silent SyntaxError that only appeared at runtime.
**Root cause:** No import check after viewer.py edits.

**Current rule:** run `python -c "import sys; sys.path.insert(0,'Fast_Fetch'); import viewer; print('OK')"` after any edit to `viewer.py`.

---

### MISTAKE-005 — Commit SHA logged as "Latest" `FIXED`
**Symptom:** Multiple CONTINUITY.md session rows had "Latest" as SHA, making git bisect impossible when regressions appeared.
**Root cause:** Agents didn't know the SHA at time of writing and used a placeholder.

**Current rule:** use `git rev-parse HEAD` for the exact local commit SHA. Never write "Latest".

---

### MISTAKE-006 — Hardcoded OS-specific absolute paths `FIXED`
**Symptom:** `C:\Users\...` path in DB config broke all Linux/Replit instances.
**Root cause:** An agent developed locally on Windows and hardcoded their path.

**Fix:** All paths use `pathlib.Path(__file__).parent / "fast_fetch.db"`.
**Rule → never hardcode absolute paths. Use `BASE_DIR = pathlib.Path(__file__).parent`.**

---

### MISTAKE-007 — `import requests` attempted `FIXED`
**Symptom:** Agent tried to add the `requests` library. Replit had it, but Ubuntu VPS and fresh Replit forks did not.
**Root cause:** Habit from other Python projects.

**Fix:** Immediately reverted. All HTTP uses `urllib.request`.
**Rule → `import requests` must NEVER appear in `Fast_Fetch/**/*.py`. Zero pip. Always stdlib.**

---

### MISTAKE-008 — Large `database_view.html` bloating GitHub `FIXED`
**Symptom:** 7.8 MB HTML file (embedded JSON dump of entire DB) was committed multiple times, bloating repo history significantly.
**Root cause:** Old push script had no file size limit.

**Current rule:** do not commit generated snapshots or files over 5 MB. Regenerate `database_view.html` locally with `python fast_fetch.py export-html`; do not rely on an uploader's size filter as protection.

---
