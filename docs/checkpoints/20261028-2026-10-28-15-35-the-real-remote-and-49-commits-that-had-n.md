# 2026-10-28 15:35 — the real remote, and 49 commits that had never landed

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-28 15:35 — the real remote, and 49 commits that had never landed

- **Canonical repo is `https://github.com/rehanradd/radd-stream`.** The credential
  authenticates as `rehanradd`, which owns the repo with push access; `radddao/radd-stream`
  answers 404 to both anonymous and authenticated requests. `git ls-remote` is the only proof
  that a push landed — earlier "GitHub master = <sha>" lines in this file described pushes
  that are not on this repo.
- At this writing remote master was `bc2bc0e`, **49 commits behind** local HEAD. Gate at
  `590b6a1` in a clean worktree: 23 backend modules green — host_resolvers 107, moviesmela
  179, database 65, vidout 6, kisskh 129, pagalmovies 54, filmiyin 38, media_search 23,
  api_v2 46, catalog_api 114, admin_panel 56, redact 49, provenance 12, operator_isolation
  22, catalog_v2 91, accounts 61, accounts_api 38, link_state 28, link_health 57,
  merge_catalogs 5, download_endpoint 18, release_descriptor 24, tiers 23.
- The 49-commit diff was scanned for secret-like strings and for `.db`/`.apk`/`.keystore`
  paths: none found.
- App evidence accepted: 73 unit-test XMLs all written 08:41:08, 0 failures; last app commit
  `590b6a1` at 08:51.
- Pushed `bc2bc0e..590b6a1` (fast-forward) to `rehanradd/radd-stream` master; `ls-remote`
  confirmed `590b6a1`.
- MoviesMela staging re-counted read-only: 16,677 posts / 20,770 releases / 57,818 sources /
  20,888 cache rows; 50 pkembed + 47 mxdrop rows active on a real 206; 19 adult-flagged posts.
- Production untouched: `fast_fetch.db` 7,647,232 B, mtime 2026-10-27T01:59; service active
  since 2026-10-27 19:47 — no restart, no live-API change.

