# 2026-10-28 21:40 — 6a8072a is green on both sides, and the push credential is now dead

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-28 21:40 — 6a8072a is green on both sides, and the push credential is now dead

- **Backend gate at 6a8072a** (clean worktree `/tmp/wt_gate_2115`, one interpreter per module):
  `GATE=GREEN`, 23/23 modules, plus `importers/test_animahd_import.py` 31/31. That covers
  `test_host_resolvers.py` 171 and `test_database.py` 75 — the two modules in
  `/tmp/task_qoder2_gate.txt`.
- **App gate at 6a8072a** (`/tmp/qbuild.sh :app:testDebugUnitTest --rerun`): `GRADLE_EXIT=0`,
  `OVERLAP=NO`, `FOREIGN_BUILD_PIDS_SEEN` empty; 77 XMLs all written 21:15:24–25, **612 tests,
  0 failures / 0 errors / 0 skipped**. `EmbedWebViewScreen.kt` reviewed and approved: JS+DOM on,
  file/content access off, popups off, no `addJavascriptInterface`, permissions denied,
  http/https/about scheme allowlist, no `DownloadListener`, no interception, no SSL override.
- **The push path is dead, and this is now the top blocker.** `GITHUB_TOKEN` is present (40 chars,
  `ghp_` prefix) but `GET api.github.com/user` answers **401 Bad credentials**, and qoder1's push
  through the `/tmp/gitenv.sh` askpass returns `remote: Invalid username or token. Password
  authentication is not supported`. Remote `master` stays at **`ff912c8`**; local `master` is
  **`6a8072a`**, three commits ahead (`55f9c51`, `8ba614a`, `6a8072a`). There is no alternate
  route: no `gh` CLI, `~/.ssh` holds only the Oracle key, and `origin` is now a clean URL with no
  embedded credential. **An owner-issued token is required before anything can be pushed.**
  `git ls-remote` still works anonymously because the repository is public — do not mistake that
  for write access.
- **qoder3 found a real crash before the pilot:** `import_animahd._queue_json` iterated
  `wp:term` groups incorrectly (a group is a list of dicts; the inner loop yields strings) →
  `AttributeError: 'str' object has no attribute 'get'`. Reproduced against a live fixture; the
  fix and its tests land before the pilot, so no AnimaHD crawl rows exist yet
  (`animahd.db` is 0 bytes from a 21:29 probe).
- **Ops:** `radd-backup-hf.timer` next fires 2026-10-29 03:44:57 PKT; `radd-autocrawl.timer` is
  inactive (last trigger 14:01) though still enabled; `radd-stream` active, PID 265554;
  `fast_fetch.db` 7,647,232 B, mtime 2026-10-27 01:59 — unchanged. Load 3.51 → 2.40 → 2.08.

