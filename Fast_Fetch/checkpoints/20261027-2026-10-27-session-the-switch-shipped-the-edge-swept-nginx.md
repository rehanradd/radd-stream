# 2026-10-27 — Session: the switch shipped, the edge swept, nginx was the blocker (Qoder)

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-27 — Session: the switch shipped, the edge swept, nginx was the blocker (Qoder)

- **Operator switch deployed.** `radd-stream.service` was still running a process that predated the
  payment ledger, so `/api/v1/app/remote-config` served only three flags. Restarted; it now serves
  `feature_flags.quality_gate = false` — the decided shape: the 1080p/4K charge exists in `/admin`
  and is off, because withholds catalog content rather than a feature a viewer was free to use.
- **The real production blocker was nginx, not code.** The installed site proxied only
  `/api/v1/posts`, `/api/v1/stats`, `/api/v1/stream`, and `location ^~ /api/ { return 403; }`
  swallowed everything else — so from outside, every `/api/v2/account*` route and
  `/api/v1/app/remote-config` answered **403**. The app had been written against endpoints no
  viewer could reach. Added those two locations (accounts allow POST/PUT/DELETE because the server
  authenticates them itself with its bearer key), kept the catch-all deny, backed up the previous
  file to `/etc/nginx/radd-stream.pre-v2.bak`, `nginx -t` before reload. Verified publicly:
  `remote-config` 200, `account/entitlement` 401 with its own problem body, `account/payment`
  POST 401 without a key, `/api/v2/health` and `/api/admin` still 403.
- **`sweep_public_edge.py` run for real, on a snapshot.** Built `/tmp/edge_snapshot.db` (31 MB:
  15 posts per site × 18 sites including 18+ rows, plus only the `releases`/`download_sources`/
  `post_sources`/`cat_*` rows those posts join to) rather than copying the 6.2 GB live catalog;
  the live file was opened read-only and never written. Two things it needed to be told: the v1↔v2
  bridge is `cat_work_sites.post_id` (not `canonical_key` ↔ `work_key`, which match nothing), and
  `cat_work_sites` must be copied once, by post id, or its unique `(work_id, page_url)` trips.
- **Finding, and the fix.** The sweep exits 0 while printing a hand-review list, and that list was
  the value: public JSON carried `"Ozark S01E01 ModiPlay"` and `"480P [GDFlix] 1.89 GB"` in
  `release_title`, because `scrub_text()` deletes only tokens in `BASE_NEEDLES` and those four
  server names were not among them. Added `gdflix`, `modiplay`, `nxstream`, `screenscape` after the
  check the file itself requires — zero rows of `posts` contain the token in `clean_title` or
  `title`. **`"Nexus"` was left out on purpose** (it titles real films; a blanked title is worse
  than a brand left for a human), same reasoning for `"Short"` and `"Torrent"`. After the restart
  the two posts that leaked them name none of the four.
- **Mistake worth recording:** the first needle was typed `modipley`, which scrubs nothing and looks
  correct in a test that only checks the list is non-empty. The spelling that matters is the one in
  the data — `ModiPlay` → `modiplay`. Verified by scrubbing the real string, not by re-reading the
  diff.

**Checks:** `test_redact.py` 49 OK, `test_database.py` 64 OK, `test_vidout.py` 6 OK,
`test_admin_panel.py` 56 OK, `setup_check.py` all pass, `sweep_public_edge.py` exit 0 before and
after the fix. App: `:app:compileDebugKotlin :app:testDebugUnitTest` → 452 tests / 55 suites /
0 failures with `OVERLAP=NO`. Commits `fbd0000…50edcb4` pushed to `master`.

---

