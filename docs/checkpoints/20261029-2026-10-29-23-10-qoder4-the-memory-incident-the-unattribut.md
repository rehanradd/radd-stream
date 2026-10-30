# 2026-10-29 23:10 — QODER4: the memory incident, the unattributed restart, and what we did about it

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-29 23:10 — QODER4: the memory incident, the unattributed restart, and what we did about it

**Measured sequence, not a narrative.**

| Time | Measurement |
|---|---|
| 22:34 | service `MainPID=1361081`, **VmRSS 6.66 GiB**, 15 threads, **18 fds** (so not leaked connections), box at 10 GiB used / **755 MiB MemAvailable**, swap 4.7 of 6.0 GiB |
| ~2 min earlier | same unit measured 5.38 → 6.05 GiB, i.e. **+0.67 GiB per 2 min, monotonic** |
| 23:02:45 | unit restarted. `NRestarts=0`, new `MainPID=1556462` — **a manual restart, not the OOM path** |
| 23:04:23 | `VmRSS 0.05 GiB`, **7.8 GiB MemAvailable**. Pressure was relieved instantly by the restart |
| 23:03–23:05 | `/api/v1/stats` answered **200 in 22.5 s** (cold full scan of `cat_works`), `/api/v1/posts?limit=1` answered **200 in 20.3 s**, 687 bytes, `total 135731` — the adult-filtered count, so redaction survived the restart |

**Who restarted it: I did not, and I am not going to pretend to know.** `NRestarts=0` means a manual
`systemctl` action; no log on this box attributes it (`auth.log` shows nothing for 23:00–23:04), and I
read `dmesg`/`kern.log`/`syslog` for an OOM line and found none, which also means I cannot prove the
6.66 GiB process was *not* killed. The one hard fact pointing at an actor: an interactive `agy`
(Antigravity CLI) process has been running since ~21:47 **inside a code-server terminal**
(`1485321 ← 1485037 /bin/bash --init-file …/code-server/…`), i.e. somebody has shell access through
the web IDE. A human-driven restart is the most consistent explanation and it is not evidence of
misuse — the box had 755 MiB free. Recorded as **unattributed** because that is what the logs say.

**Root cause of the growth, ours.** It was demand we generated, not traffic: `/api/data` materializes
the entire ledger (150,799 rows, a 2.5 MB response that measured 46.6 s) inside the serving process,
and with 15 threads' glibc arenas freed memory is not returned to the kernel — so each read ratchets
RSS up and never brings it down. At 22:34 I also caught an **in-process**
`viewer.fetch_database_payload('', full=True)` running as a child of that `agy` session (30 MB and
climbing), which does the same damage to whichever process calls it. Cold `/api/v1/stats` costs the
same 22 s scan.

**Actions taken.** Fleet-wide rule delivered to q2 (23:09) and q5, and carried into q3's and q1's
briefs: no live `/api/data` and no `full=True` against the production catalog, exactly-one live read
if unavoidable, no `/api/v1/stats` polling, nothing heavy above load 4, **never restart the unit** —
report climbing memory to me instead, which is the thing that would have made this visible earlier.
Merge batch 4 (#9) stays held. I ran no Gradle all evening and no gate since 22:20.

**Still true and now re-shown:** the restarted service runs `/opt/radd-stream` at **`bf9e565` with 60
dirty paths**, not the pushed tip `c7526ae`. Production code cannot be reproduced from the pushed
tree; that is task #19 and it remains the owner's call, mine being to keep saying it out loud rather
than quietly fixing it.

**Recovered and shipped while this was happening** (all pushed to `master` and `main`):
`9859b8a` (q3's admin/usage landing — CI's real 17-module list, **791 tests, 0 failures**, and GitHub's
hosted runner independently `completed success` on both refs for `9859b8a` and `6f7e3a0`),
`6f7e3a0` (`docs/RADD_RELAY_AND_AUTH_ARCHITECTURE.md` — the Antigravity plan recovered from outside
Git, verbatim in Appendix A under rulings R1–R9; plus `docs/ADMIN_PANEL_ACCESS.md` and §6 of
`IDENTITY_AND_TRIAL_ABUSE.md`), `5c331d6` (tunnel prerequisites measured), `c7526ae`
(`AGENTS.md`/inventory gate numbers corrected: 17 CI modules not 15+2 importers, `test_database` 133
not 124/76, 68 Python test modules not 66/60/44, and Android green on `master` while the live lane
branch `q1-ad-cadence` is **red** at `99472e0`). Tasks #28–#32 opened for the recovered plan.

### 2026-10-30 00:40–01:45 — `/api/data` bounded, and the v2 rebuild proved read-only but not yet finished `[Q2-LEDGER]`

- **Half 1 landed and CI-green at `b2c102d`** (branch `q2-bounded-ledger`). `/api/data` now clamps
  `limit` to 200 (default 50), pages with one-extra-row `has_more` (no COUNT), and answers counters
  from `cat_projection_meta` by default — `stats=full` is an explicit operator act and a typo falls
  back to the stamp. The dashboard sends `q`/`limit`/`page` and renders `—` for unstamped counters
  instead of `0`. Route stays operator-only on both the process and nginx.
- **Audit correction, recorded so it is not re-quoted:** the 93 s / 112 s / 1012 s timings from the
  earlier audit were taken at `nice 19` on a saturated box; warm at normal priority the same queries
  are 0.35 s (adult) and 0.01 s (posts). The 46.6 s end-to-end `/api/data` answer is the number that
  matters, and it was real.
- **Half 2:** `Fast_Fetch/project_readonly.py` rebuilds into a new file from an ATTACHed `mode=ro`
  ledger; `test_project_readonly.py` proves the source is byte-identical afterwards and that no link
  is dropped. Measured before: **150,799 posts / 1,780,121 releases / 4,073,865 links**, 15,068 adult
  rows, against a stale stamp of 116,922 works / 1,383,752 releases / 3,783,959 links at 130,016 posts.
- **The rebuild was stopped at 01:45 under the orchestrator's load guardrail, not finished.** It
  reached 129,457 works, then entered the link pass; CPU share was 0.4 % at `nice 19`/`ionice -c3`
  and ~9 % after relaunching at `nice 5`/`ionice -c2 -n6` on a 1-vCPU box already at load 8.7–10.2.
  Heavy work is frozen above load 4, and `catalog_v2.project()` has no resume point, so the 195 MB
  partial output was discarded rather than mistaken for a result. Memory was never the trigger
  (4.8 GB available, 3.0 GB swap free, cgroup 60 MB — all above the floors). **The exact relaunch
  command, expected cost (~5–6 CPU-hours) and the numbers wanted are queued in CONTINUITY.md for a
  quiet window. No after-numbers are reported because none exist**; acceptance stays
  `walked_links == 4,073,865`, zero orphans, every uncarrying source row's URL present, five safe
  stamps written.
- **Landed:** `db81220`, hosted Backend CI green (run `40953382031`), fast-forwarded to `master` and
  `main` at 21:01Z; the fleet's next tip `396e476` contains it. The projection half remains queued.
- **Merge-order warning:** the console branch `q2-dashboard` is not in `master`; both it and this
  branch edit `fetch_database_payload` and `DASHBOARD_HTML`.

**MovieBox closed out (q4, 2026-10-30, task #33).** Antigravity's untracked
`import_themoviebox.py` is finished, tested and **landed** — pushed to
`q4-moviebox-20261030`, then fast-forwarded onto `master` and `main`. The scout
blueprint that seeded it was wrong on three of four claims (sitemap, cms,
`rest_api.usable`) and is now corrected in place with the measured values.
Live bounded pilot: 44 works staged, **0 releases and 0 sources by design**, 6
detail pages crawled in 39 s with no print on any of them. The site is a
**periodic metadata top-up, not a crawlable catalog** — `subjectType` is ignored
server-side, 100 feed items gave 84 duplicates against a 44-row vault, and the
only filtering endpoint is authenticated, whose client token we do not
reverse-engineer. Full detail in `Fast_Fetch/SITES.md` §25 and the q4
CONTINUITY entry. Nothing else on this lane is pending; the app lane (#25) and
the projection/`/api/data` bound (#10) are the real remaining work.

**Three measurements the orchestrator took at 00:30–00:35, because nobody else had.**

1. **The two "never-pushed local commits" are not a continuity risk after all.** I
   compared `5446771` ("the 9 hosted test failures and all 23 lint errors") and
   `bf9e565` file-by-file against `origin/master`: **18 of the 19 paths `5446771`
   touched are byte-identical on the tip** (only `docs/SESSION_CHECKPOINT.md`
   differs, because the tip has newer appends), and `App/AGENTS.md` on the tip is a
   superset of `bf9e565` except for a 17-line narrative about a push that was
   blocked at the time. That narrative is now obsolete — pushes work, I fast-
   forwarded `master` and `main` twice tonight — so I am deliberately **not**
   resurrecting it. The Android CI fixes and the docs corrections are in the pushed
   tree; task #19's real remaining problem is only that the live checkout is at
   `bf9e565` with dirty paths, not that work is unpushed.
2. **A filtered read of the production `posts` table costs 26.46 s.** Measured,
   read-only, `nice`d: `SELECT COUNT(*) FROM posts` → 0.91 s (150,799 rows);
   `SELECT COUNT(*) FROM posts WHERE is_18_plus = 1` → **26.46 s** (15,068 rows).
   There is no index that makes that predicate cheap, and the table's rows are
   wide. This is the same physics that makes `/api/data` a 46.6 s / 2.5 MB read, and
   it is why any admin counter must be a pre-computed row, not a scan. It also means
   **my own probes count against the box**: the adult twin-exposure retry I wanted
   to run (`clean_title LIKE '%4 Play%'`) did not finish in 90 s and I killed it
   rather than re-run it, with the service live and the box at load 7.9.
3. **So the exposure question stays open, honestly stated.** AGENTS.md now claims
   the invariant is "measured against the code and pinned by tests"
   (`test_redact.py::AdultDenialOnBothPortsTests`,
   `test_database.py::KeyLevelAdultIdentityTests`) — that is defensible for the
   *code*, and the key-level reconciliation is in Git at `20f5fcc`. What is **not**
   re-measured on production since that reconciliation is the row count: whether any
   `canonical_key` still carries both a flagged and an unflagged row in
   `merged_catalog_20261025.db`. Do it in a quiet window with an indexed query, not
   a `LIKE` scan, and never at load above 4.
