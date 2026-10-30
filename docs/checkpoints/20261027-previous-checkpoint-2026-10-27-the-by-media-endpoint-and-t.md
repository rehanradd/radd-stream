# Previous checkpoint — 2026-10-27 (the by-media endpoint, and the APK that was still stale)

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## Previous checkpoint — 2026-10-27 (the by-media endpoint, and the APK that was still stale)

- **Goal:** close the two decided-but-unbuilt items that did not need a phone: the
  identify-a-file search (`/api/v1/search/by-media`) and the debug APK the public
  `download/` link was still serving from an older tree.
- **APK republish (task 5, now closed).** `:app:assembleDebug` from `04126e7` finished
  `GRADLE_EXIT=0`, `OVERLAP=NO`, `apksigner verify` clean on v1+v2 (Android Debug cert).
  Published over `/var/www/download/radd-stream.apk`: public 200, 22 738 552 bytes,
  md5 `9ace0279…`, byte-identical to the built artifact. The superseded build was
  **moved out of the web root** to `/home/ubuntu/radd-stream-data/radd-stream.apk.pre-04126e7`
  rather than deleted — it had been publicly fetchable at a stable URL, and a stale APK
  anyone can install is a worse state than a backup nobody can.
- **New endpoint.** `Fast_Fetch/media_search.py` + the `/api/v1/search/by-media` route in
  `viewer.py`, tested by `Fast_Fetch/test_media_search.py` (21 tests). The design decisions,
  because they are not guessable from the code:
  1. **Hints are evidence, not keywords, and are reported three ways** — `matched_on` /
     `mismatched_on` / `unknown_on`. A runtime the ledger does not hold is `unknown`, never a
     silent agreement; the live catalog answers `runtime_minutes: null` for most works, so this
     is the common case, not a corner.
  2. **A title is required; no title is a 400.** 130 016 works, thousands of them ~120-minute
     480p films — duration plus rung cannot discriminate, and ranking all of them to say
     "here are 10 of possibly 10 000" would be a lie at 1 vCPU.
  3. **The v1↔v2 join is `cat_work_sites.post_id`.** `posts.canonical_key` ↔ `cat_works.work_key`
     matches **zero rows** (a slug against an `imdb:` id); a test now pins both facts, so the
     bridge cannot silently rot back into an empty answer.
  4. `docs/ADVANCED_VIDEO_SEARCH_ARCHITECTURE.md` was **not** implemented as sketched: it asks
     for an FTS5 `catalog` table and columns the ledger does not have. This is the design that
     fits the real schema.
- **Verified:** `test_database` 64, `test_media_search` 21, `test_redact` 49, `test_api_v2` 46,
  `test_admin_panel` 56, `test_catalog_api` 114, `test_provenance_stamping` 12,
  `test_operator_isolation` 22 — 364 tests, all OK, one module per invocation.
- **Edge sweep now covers the new route** (`sample_titles` probes, three hidden-adult probes,
  the no-title 400, the garbage-duration 200). Run on `/tmp/edge_snapshot.db`: **OK — no site,
  no hoster, no upstream host across 48 sampled posts and every route**; hosts named inside
  public bodies were only `image.tmdb.org` and `m.media-amazon.com`.
- **Deployed:** service restarted (8 polls to 200 — it takes ~70 s to boot, do not trust a fast
  000), `= /api/v1/search/by-media` added to nginx before the `^~ /api/` deny (GET/HEAD only,
  `burst=20`, 30 s read timeout), `nginx -t` ok, reloaded. Backup of the old config:
  `/etc/nginx/radd-stream.pre-bymedia.bak`. Public checks: GET answers 200 with the three-way
  report, POST → 403, and `/api/v2/health` 403 / `/admin` 401 / `/api/data` 403 unchanged.
  Live query cost measured: **0.37 s** for a five-candidate title.
- **What is NOT verified:** still no device and no emulator, so the *client* half of
  M-SRCH-01 (permissions, `DeviceMediaScanner`, the screen, the Room mapping) is deliberately
  not started rather than half-written; nginx's rate shedding was not re-proved here (the 26
  request loop stayed inside the burst), and the app's own per-path limiter is the backstop.
- **Repo hygiene, found while staging this session's work:** commit `04126e7` — a docs commit
  of mine — swept in another account's `Fast_Fetch/CONTINUITY.md` entry asserting
  `importers/test_filmiyin_import.py` 38 OK, while `Fast_Fetch/importers/` is still **untracked**.
  The filmiyin importer is therefore not in the repository and its tests do not run from a fresh
  clone. A correction is now written into `CONTINUITY.md` itself; the untracked
  `importers/`, `dispatch_worker.py`, `openrouter_*.py`, `prompt_worker*.txt`, `android_tasks.md`
  and `filmiyin_task.md` are deliberately **not** staged by this session — reviewing someone
  else's unfinished work is not a side effect of committing my own.
- **Next action:** task 4's remaining half — the VIP shortener waterfall in the app
  (`cat_shortened_links` exists and is empty; `link_shorteners` already reaches
  `VipRemoteConfig`) — then the M-SRCH-01 client pass, which needs a phone.

