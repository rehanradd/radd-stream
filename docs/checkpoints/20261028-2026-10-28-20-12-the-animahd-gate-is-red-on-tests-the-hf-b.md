# 2026-10-28 20:12 — the AnimaHD gate is red on tests, the HF backup is finally timed, and the interceptor does not exist

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-28 20:12 — the AnimaHD gate is red on tests, the HF backup is finally timed, and the interceptor does not exist

- **Backend gate, as asked.** `test_database.py` → 75/75 OK. `test_host_resolvers.py` on the
  uncommitted AnimaHD tree → 171 tests, 2 failures + 2 errors; the committed baseline (141) is
  unaffected, and all four defects are in the new tests, not the resolver:
  - `:1223` — `EMED_FALLBACK` is undefined (NameError).
  - `:1471` — the scripted fetch raises `OSError` before `http_request` can turn it into status 0;
    inject at `hr._open` as the test at `:399` does.
  - `:1450` — asserts `hr.ANIMAHD_MIME` while its own name says the measured mime is kept; the code
    returns `text/html`.
  - `:1416` — `assertIn` on a list needs the exact element; the note carries a
    “— this host answers 403…” suffix.
  qoder3 was sent that list with line numbers. `import_animahd.py` compiles (1,606 lines,
  `sync|crawl|parse|resolve|sample|stats`, `--db` default `animahd.db`, `is_18_plus` set at storage)
  but stays untracked until the suite is green.
- **App gate, task #23 closed.** 74 XMLs from a single instant (20:08:07) — **588 tests / 0 failures /
  0 errors / 0 skipped**, with `App/` clean at HEAD `38da6db`. That run covers the anime
  `is_animated` fix and the comment-guard rewrite. My own `/tmp/qbuild.sh` invocation ended
  `GRADLE_EXIT=0 / OVERLAP=NO` but was entirely UP-TO-DATE (no test execution); the 20:08 XMLs came
  from the next serialized invocation, which started after the lock was released — sequential, not
  overlapped.
- **`StreamWebViewInterceptor.kt` does not exist** — not in the tree, not in any ref history. The
  WebView mentions in `App/` are comments saying the opposite: there is no WebView path, and an
  unplayable link is “Not playable here” plus a keep (`PlaybackRecovery.kt:40,184,217`,
  `CatalogV2.kt:298`, `LinkClassification.kt:58`, `LinkKindClassifier.kt:32`). qoder1's real current
  work is the anime wire flag and the session-24 parity measurements; there is no progress to review
  under that file name.
- **HF backup is now timed.** `radd-backup-hf.timer` → daily 03:40 PKT (+≤10 min); the service runs
  `/usr/local/bin/backup-hf` as `ubuntu` with `Nice=19` and idle IO. Two gaps fixed on the way:
  `backup_manager.py --hf` **skips the upload** when `HF_DATASET_REPO` is empty (the wrapper only
  prints a default), so the unit supplies `radddao/radd-stream-backups`; and `HF_TOKEN` lives in
  `~/.bashrc` *after* its non-interactive guard, so the unit runs under `bash -ic` — verified visible
  under a transient `systemd-run`. `systemctl list-timers` shows the next fire; the first real upload
  is that run.
- **The 6-hourly autocrawl was stopped, not deleted.** `radd-autocrawl.timer` (02/08/14/20) runs a
  fleet sync → `merge_fleet.py` → HF backup. Its merge target is `merged_catalog_20261025.db` and all
  sites logged “already merged, skipping”, but step 1 can write sitemap/domain rows into
  `fast_fetch.db` — inconsistent with the freeze — and it competes for the single vCPU. Stopped at
  20:01; drop-ins now run it under `bash -ic` (its backup step had failed for the same missing token)
  and with `Nice=10`. `fast_fetch.db` mtime is unchanged (2026-10-27 01:59). Re-enable only when the
  owner lifts the freeze.
- **Load at 20:04:** 7.18 on one vCPU — five `qodercli` sessions plus the Gradle daemon, no crawler
  among them. Every build went through `/tmp/qbuild.sh`; the AnimaHD suites ran `nice -n 10`.
- **Next:** qoder3 fixes the four tests → commits importer + tests + resolver → SHA gate. qoder1:
  session-24 parity follow-ups. Watch the 03:44 backup: ~1.8 GB per archive, no rotation, 131 GB free.

