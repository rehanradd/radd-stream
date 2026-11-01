# 2026-11-01 01:2x (gate verdict landed 01:5x) — q3 backend lane `[Q3-PREMERGE-PLAN]`: the frozen merge,
# planned to the command, costed where I measured it and marked unmeasured where I did not

Lane: **qoder3**. Tree: `/tmp/q3_coins`, branch `q3-coins-engine` at `ef91096` (first hand-off of this plan;
the corrections below are the second). **Everything up to the C3R landing is on trunk at `f12ab3f`** (main ==
master) as qoder1 replayed it; this entry adds only the landing note and the re-branch. The lane continues as
`/tmp/q3_premerge` on `q3-premerge-exec-20261101`, based on `f12ab3f`, for anything after this point.
Read that before diffing anything: `60ef341` is **not an ancestor of trunk** — qoder1 replayed the two
commits as a cherry-pick rather than merging the side branch — so `git diff 60ef341 trunk` shows trunk's
*other* content as my deletion, and that reading is wrong. qoder1 made exactly that error against an earlier
head of mine, measured it properly with `git diff --name-only $(git merge-base …)`, found this lane's
contribution to be four documentation paths and **no Python at all**, and retracted in writing. The replay
makes the question unaskable, which is the right fix; the note here is so the next lane does not re-ask it.
Requested by
`Q1 TARGET DECISION plus a CORRECTION 01:20`: prepare the sequence, the measured cost per step and the
expected row-count delta as a **queued action**, hand the sha, and do not run it — load1 was 9.91 at the
notice and 6.57 at 01:23, so the freeze holds. **Nothing in this file ran against the catalog.** The only
executions were on 8 MB staging files and a scratch db in `/tmp`, all `nice -n 19`.

## GATE VERDICT (qoder1, 01:4x, read at `ef91096`): APPROVED WITH 4 CORRECTIONS — then C3 REVERSED — still frozen

`/tmp/q1_premerge_ruling.txt`. Approved as written: the target name, `.backup` from `-readonly`, the
size+mtime+`%F` verification, vegamovies-first calibration with a pause-and-report, the exact-count
assertion, adult fold default-on with `adult_exposures_remaining != 0` == **NOT DEPLOYABLE** in those words,
no predicted merged total, and "discard, never silently re-run". qoder1 re-verified my code claims and
caught one drift of mine: the fallback is `merge_catalogs.py:478`, not `:473` (`:473` was drift — fixed
below where I cited it). The four corrections, landed into the steps they change:

| | correction | where it lands |
|---|---|---|
| **C1** | qoder1 **withdraws** "wal_checkpoint(TRUNCATE) the 5 sources first" — my crash test shows a read-write open rewrites the file, so the instruction would have written into five dbs that are not mine. Recorded **under qoder1's name**, not mine. | Step 4, unchanged in substance |
| **C2** | My Step 0 `fuser` abort is **wrong**: `fuser` returns nothing and `/proc/1835070/fd` holds **zero** `.db` files (per-request opens), so an empty `fuser` is the healthy state and my abort fired on it every time — burning the scarcest resource on the box. `fuser` is informational; the load-bearing guard is source mtime+size re-checked immediately **before and after** the `.backup`. | Step 0 + Step 2 |
| **C3** | ~~**mp4moviez EXCLUDED**~~ — **REVERSED by qoder1 at 01:5x (`/tmp/q1_c3_reversal.txt`), see C3R below.** The exclusion was ruled on four reasons, three of which the fleet's own record contradicted and the fourth of which survives only as a reporting caveat. | Step 5.5 + Step 7 + blocker 1 |
| **C3R** | **Merge all five.** mp4moviez enters through `importers/convert_mp4moviez.py` — already on trunk, already tested, reads the legacy db `mode=ro` and writes a *new* vault — last in the order, because it is the one step qoder1 has read but not executed. If its measured output disagrees with the 10-29 numbers: **stop and report the delta, do not merge the surprise.** My `--target` fix to `mp4moviez_staging_20261101.db` is **APPROVED as C3R-final**; `--force` is barred on any path outside my own new vault. | Step 5.5 + Step 7 + blocker 1 |
| **C4** | Add **Step 3.5**: `cp` the verified copy to `.db.baseline`, so a failed merge never costs a second production read. | new Step 3.5 |

**C3R, and what I measured when I checked it (all read-only, all on ≤34 MB staging files, `nice -n 19`).**
qoder1's reversal is correct on every fact I can verify and I adopt it: `convert_mp4moviez.py` is on
`origin/main` (`81cdff8` 05:53, then `eac15bb` 07:55 "conserve every legacy row and account the skipped
releases") with `test_convert_mp4moviez.py` beside it; it connects `file:<source>?mode=ro`
(`:436`), refuses `--source == --target` (`:432`), builds into a `mkstemp` sibling and `os.replace`s it onto
the target (`:453`, `:519`) — so there is no in-place write and no `DROP TABLE`/`RENAME TO`/`ALTER TABLE`
anywhere in it. Legacy `mp4moviez.db` re-measured now: **regular file, 31,354,880 B, mtime 2026-10-27
22:51:22, no `-wal`, 29,848 posts / 54,267 releases / 91 flagged / 0 NULL flags** — exactly the stat qoder1
restated. Two things, however, that measurement added and that had to be settled **before** Step 5.5 could
run — both are now settled, in qoder1's favour and against mine, by the C3R-final approval below:

1. **The command as written cannot run.** `/home/ubuntu/radd-stream-data/mp4moviez_staging.db` **already
   exists** — 34,193,408 B, mtime **2026-10-29 05:25:00**, `journal_mode=delete` — and the CLI refuses an
   existing target unless `--force` (`:548-549`: *"exists; rerun with --force to rebuild it"*). So the
   dispatch exits non-zero without converting anything. The two answers on the table were `--force` (rebuild
   in place — atomic, and the legacy source is safe either way) or a fresh target name. **APPROVED as
   C3R-final: `mp4moviez_staging_20261101.db`, with `--force` barred on any path outside my own new vault.**
   qoder1's reason for rejecting the "obvious" workaround is the better one and was not mine: `--force` would
   have overwritten the very file the 10-29 measurement depends on, while the new name keeps the 05:25 vault
   as the independent comparator for the delta report.
2. **The existing vault is a different, older output than the numbers in the ruling.** Its actual contents
   are **11,403 posts / 54,263 releases / 54,263 sources / 43 flagged**, against the 10-29 measured plan of
   **28,066 works / 54,267 releases / 54,267 sources / 88 adult rows** — a delta of **−16,663 posts, −4
   releases, −4 sources, −45 flagged**. Its mtime (05:25) precedes *both* converter commits (05:53, 07:55),
   which is the obvious cause: it was built by pre-`81cdff8` working code and never rebuilt after the
   row-conservation fix. This is precisely qoder1's stop-condition, met in advance and in writing: **if any
   lane merges the vault that is on disk tonight instead of the one the converter produces, it merges a file
   that is missing two-thirds of the works** — and 43 flagged rows where the legacy table carries 91 is an
   adult-exposure gap, the one class of error this fleet does not get to discover later. So Step 5.5
   converts, and the assertion is against the *converter's own printed accounting*, not against the file
   that happens to sit at that path.

**Q1-C3R-CONSISTENCY, and it was my bug.** qoder1 approved the `mp4moviez_staging_20261101.db` target as
C3R-final — noting the second reason I had not stated, that leaving the 05:25 vault intact gives the delta
report its independent comparator — and then caught the defect I had left behind: I applied the reversal to
the top of this file (Step 5.5) and not to its bottom (Step 7), which still said *"EXCLUDED … merged = four
sites"*. Executed as it then read, the copy would have held five sites while the report named four — a report
misstating the contents of the database it describes, which is the single failure mode this gate exists to
prevent. Step 7 is rewritten to C3R, and the sweep qoder1 asked for is done: the surviving `four` in this file
names the four *directly* merged sites and the four counted *tables*, both stated with the word that makes it
unambiguous. Their side of the exchange stands too: I was right that their dispatch could not run, and being
right about a command that fails is not the same as being right about the plan — which is why the correction
went in as a target name rather than as a refusal.

**Execution gate, explicitly not open:** qoder1 posts `SUSTAINED-UNDER4` (load1 < 4.0 for five consecutive
minutes) **and** the hard floor clears (`MemAvailable > 1,500 MB`, `SwapFree > 800 MB`). 3.45/3.99/5.08 at
read time is a dip, not a lift — and C3R *proved* it the hard way: the sub-4 window qoder1 caught at 01:52
(load1 3.48) closed at 01:55 (load1 4.85) after **about three minutes**, which is shorter than my own 3–10
minute estimate for the 6.4 GB read, so a window that size cannot hold Step 2. **Do not start the copy on a
dip of that length.** Running sequence, with the stop-and-wait points as C3R restates them:
Step 0 → 1 → 2 → 3 → **3.5** → 4 → Step 5 vegamovies → Step 6 → **STOP, report the per-post rate, wait for
go** → bolly4u, katmoviehd, filmyhit one at a time with Step 6 after each → **Step 5.5 mp4moviez** (convert,
then merge) + Step 6 → Step 7 report at `/home/ubuntu/DATABASE_MERGE_REPORT.md`. Per C3R I proceed through
copy → verify → baseline → vegamovies **without** stopping for a separate go — the 01:45 ruling's
"STOP after Step 4" is retired — and the one in-sequence gate is the per-post rate report.
Untouched by any step: the service (no restart), tags, the two `fast_fetch.db` symlinks (no repoint/delete),
`merged_catalog_20261025.db` (read-only), and all five sources (read-only). The copy and its baseline are the
only files this plan may open read-write.

## The correction I accept, and the one premise I can now retire with a measurement

Retirement accepted: qoder1 re-measured with `stat(2)`, found `type=symbolic link` and `size=56` = the
length of the target path, and retired the "56-byte empty databases" line. That is the second wrong
reason this fleet has caught on a safety gate, and the note in the notice is the right lesson: the block
was correct, the justification was not, and a bad reason on a gate is what lets the next lane talk
itself past a good one. I hold the same discipline here — the plan below states which numbers I measured
and which I did not, in the same sentence it uses them.

The premise I can retire by test, because it decides whether step 4 has to exist at all: **`cp` is the
only copy mechanism that a dirty WAL breaks.** Simulated on a scratch copy of `animahd.db` (8,269,824 B,
converted to WAL): committed 2,000 rows, then `os._exit(9)` so the process died leaving a stranded
**37,112-byte `-wal`** and a 32,768-byte `-shm` with no holder, then:

| command | result |
|---|---|
| `sqlite3 -readonly base.db ".backup dirty_copy.db"` | **rc=0**, copy = 8,294,400 B = main **+ the WAL frames** |
| `sqlite3 -readonly base.db "SELECT COUNT(*) FROM t"` | **2000** — the readonly reader sees wal+main together |
| `sqlite3 base.db "SELECT COUNT(*) FROM t"` (read-write) | 2000, and the `-wal`/`-shm` **disappeared**: the open checkpointed production-equivalent state into main (8,269,824 → 8,294,400) |

So `PRAGMA wal_checkpoint(TRUNCATE)` before reading is **not** needed for correctness under this plan:
`.backup` from a `-readonly` connection folds the WAL into the copy by construction. What the checkpoint
would actually buy is a *write to five staging catalogs* — and the third row above is the reason I want it
kept off the table: a read-**write** open silently recovers and checkpoints the file it touches, so opening
the live catalog read-write "to be safe" would itself rewrite production state. **C1: qoder1 has now
formally withdrawn the checkpoint instruction on precisely this evidence, and recorded the wrong reason
under their own name** — the gate said "wal_checkpoint(TRUNCATE) the 5 sources first"; executed, that would
have had me write into five databases that are not mine, and since `.backup` from `-readonly` folds the WAL
by construction it bought nothing and cost exposure. Controls, in order:

1. `-readonly` on every open of anything that is not mine, always, and verify after each step that the
   source's size and mtime are unchanged (measured here: `animahd.db` came out of both copy methods at
   8,269,824 B / mtime 10-28 22:57:00 with no sidecars created).
2. Still measure the five sources' `-wal` before touching them (three are 0 bytes: vegamovies 00:22:57,
   bolly4u 00:23:09, katmoviehd 00:23:11; two have no pair at all — filmyhit, mp4moviez — and `animahd.db`
   reads `journal_mode=delete`, which is what a no-sidecar db looks like rather than a WAL one). qoder1
   re-ran this stat-only at 01:43 and got the same answer (vegamovies, bolly4u, katmoviehd at **0 B**;
   filmyhit, mp4moviez **absent**), so Step 4's stop-condition is satisfied in advance — but a 0 B reading
   is a statement about that second, not about the window, so it is re-run at execution time. If any
   `-wal` is **non-zero**, that is new information and I stop and report instead of checkpointing.
3. The gap I cannot close honestly, and **C2 makes it sharper rather than closing it**: I tested a *dead*
   WAL with no writer, not `.backup` against a **live concurrent writer**, because that means writing to
   production to test it. qoder1 measured why the live case is real — the service opens a connection **per
   request and closes it**, so a writer *can* arrive mid-copy, and my "mtime hasn't moved so the window is
   narrow" reasoning understated it. The whole of my protection is therefore the source mtime/size pair
   taken immediately before and immediately after the read (Step 2) plus Step 3's exact four counts. In
   qoder1's words: **keep them, do not upgrade them to confidence.** The online backup API resolves the
   page-snapshot half by construction; it does not resolve a count that changed while I was reading.

## The command sequence, in order, with its cost

Every step gated on qoder1's **`SUSTAINED-UNDER4`** post — load1 < 4.0 for five consecutive minutes, not a
dip — **and** the hard floor clear: `MemAvailable > 1,500 MB` / `SwapFree > 800 MB`. Approval of the plan is
explicitly *not* a licence to start.
One statement per invocation, never a retry loop; a failed step aborts the sequence and is reported.

**Step 0 — preflight, cheap, may run any time (`stat`/`df`/`fuser` only).**
```
uptime; free -m; df -b /home | tail -1        # need > 14 GB free for the copy + headroom
stat -c '%n %F %s %.19y' /home/ubuntu/radd-stream-data/fast_fetch.db \
                          /opt/radd-stream/Fast_Fetch/fast_fetch.db   # both must still be `symbolic link`
for s in vegamovies bolly4u katmoviehd filmyhit mp4moviez; do stat -c '%n %s %.19y' $s.db $s.db-wal; done
fuser /home/ubuntu/radd-stream-data/merged_catalog_20261025.db        # INFORMATIONAL ONLY — record it
```
Abort condition: if either `fast_fetch.db` name has stopped being a symlink, or its target is no longer
`merged_catalog_20261025.db`, the picture changed under me again and everything reverts to a blocker report.

**C2, and this is a real bug I had written into the plan.** I had `fuser` as a gate with the expectation
"expect pid 1835070 only". qoder1 measured it at 01:44: `fuser` on the live catalog returns **nothing**, and
`/proc/1835070/fd` holds **zero** `.db` files — the service opens a connection per request and closes it. An
empty `fuser` is therefore the *healthy* state, so my abort condition fired on the normal case every single
time, and since a sub-4 window is the scarcest resource on this box, the cost of that bug was the window
itself. `fuser` output is now recorded and never an abort. The load-bearing guard moves to Step 2: the
source's `stat -c '%F %s %.19y'` taken **immediately before** the `.backup` and **immediately after** it,
where `mtime` unchanged at `2026-10-29 10:52:37` and `size` unchanged at `6,396,899,328` are what prove no
writer moved production during the read. If either changed: discard and report, never re-run silently.

**Step 1 — calibrate the read cost, a 349 MB read (its own duration is part of what it measures), no
production touch.** Timed `.backup` of `vegamovies.db` to `/tmp` gives MB/s on a large file; the 8 MB
calibration below is warm-cache and does not extrapolate.
```
time sqlite3 -readonly /home/ubuntu/radd-stream-data/vegamovies.db ".backup /tmp/q3_throughput.db"; rm -f /tmp/q3_throughput.db
```
Measured reference (this session, warm cache): 8,269,824 B in **0.249 s** via `.backup` and **0.243 s** via
`VACUUM INTO`, sqlite3 3.45.1. Extrapolating the *warm* figure to 6,396,899,328 B gives ~193 s, and that
number is **not** the estimate — the catalog is 6.4 GB on a box with ~3.1 GB available, so it cannot be
cached and the real pass is disk-bound. **Duration of step 2: unmeasured.** Expect minutes, order 3-10.

**Step 2 — the copy, once, never twice. This is the heavy production read the freeze is about.**
```
stat -c '%n %F %s %.19y' /home/ubuntu/radd-stream-data/merged_catalog_20261025.db   # BEFORE: record it
time sqlite3 -readonly /home/ubuntu/radd-stream-data/merged_catalog_20261025.db \
  ".backup /home/ubuntu/radd-stream-data/merged_catalog_premerge_20261101.db"
stat -c '%n %F %s %.19y' /home/ubuntu/radd-stream-data/merged_catalog_20261025.db   # AFTER: must be identical
```
`.backup` not `cp` (a WAL source, mid-WAL per the table above) and not `VACUUM INTO` (measured: it
**defragments**, 8,269,824 → 8,208,384, i.e. about −0.7 %, and forces `journal_mode=delete` on the output —
so its size would not match the source and the size check stops meaning anything). Verification, cheap and
structural, in the order that makes the guard load-bearing rather than decorative: the source's `stat` pair
**immediately before and immediately after** the read must agree (`regular file`, 6,396,899,328 B, mtime
10-29 10:52:37) — per C2 that pair, not `fuser`, is what proves no writer moved production during the copy,
because the service holds no `.db` fd between requests; then copy size **equals** 6,396,899,328 B exactly
and `stat -c %F` on the copy is `regular file`; and the `-wal`/`-shm` pair my open created on the source is
gone again (measured behaviour: a clean close deletes it — the catalog's pair from 00:23 was absent by 00:32).

**Step 3 — verify the copy before it is a merge target. Heavy (a full pass), once.**
```
sqlite3 -readonly /home/ubuntu/radd-stream-data/merged_catalog_premerge_20261101.db "PRAGMA integrity_check;"
sqlite3 -readonly /home/ubuntu/radd-stream-data/merged_catalog_premerge_20261101.db \
  "SELECT (SELECT COUNT(*) FROM posts), (SELECT COUNT(*) FROM releases),
          (SELECT COUNT(*) FROM download_sources), (SELECT COUNT(*) FROM posts WHERE is_18_plus=1);"
```
Expected exactly the source's measured values: **150,799 / 1,780,121 / 4,073,865 / 15,068**. Any difference
is not noise: it means either a writer moved production between 10-29 10:52 and the copy, or the snapshot is
inconsistent, and in both cases the copy is discarded and the step is reported, not re-run silently. Cost of
`integrity_check`: one more full 6.4 GB pass, **unmeasured**; it runs on the copy, never on production.

**Step 3.5 — baseline the verified copy, before any merge write (C4, added by qoder1).**
```
nice -n 19 cp /home/ubuntu/radd-stream-data/merged_catalog_premerge_20261101.db \
              /home/ubuntu/radd-stream-data/merged_catalog_premerge_20261101.db.baseline
stat -c '%n %F %s' /home/ubuntu/radd-stream-data/merged_catalog_premerge_20261101.db{,.baseline}  # sizes must agree
```
Cost: one local 6.4 GB read + write on `/dev/sda1`, `nice -n 19`, and **no production read**. It runs only
after Step 3's four counts agree, so the baseline is a known-good state and not a copy of a bad one. The
reason it is worth a second 6.4 GB on disk: this plan's rollback for a count mismatch was "discard the
copy", and discarding means Step 2 again — a second full read of the live catalog, which means winning a
second sub-4 window that tonight may not arrive before the owner wakes. With a baseline, rollback is
`cp .db.baseline -> .db` at zero cost to production. **Do not delete the baseline until the report is
written and qoder1 has read it.** Free-space check moves to 2 × 6.4 GB plus headroom; qoder1 measured
97,298,190,336 B (≈90 GiB) free on `/`, so copy + baseline + merge growth fits.

**Step 4 — source WAL assertion, read-only, no write (see the retirement above).**
```
stat -c '%n %s %.19y' /home/ubuntu/radd-stream-data/{vegamovies,bolly4u,katmoviehd,filmyhit,mp4moviez}.db-wal
```
0 bytes or absent → proceed and record it. Non-zero → **stop**, report, and let qoder1 decide on the
checkpoint, because that is the one case where the frames hold rows the main file does not. Per C1 there is
no checkpoint in this plan for the sources at all, and per the 01:43 stat-only re-run all five are already
clean — but I still take the reading at execution time, because "clean as of 01:43" is not a statement about
my window. **No stop after Step 4** — C3R restates the gates: copy → verify → baseline → vegamovies runs
through without a separate go, and the single in-sequence stop is the per-post rate report after Step 6.

**Step 5 — the merges, sequential, calibrated on the first one.**
```
cd /tmp/q3_premerge/Fast_Fetch
# Step 5.0 — the DB_PATH assertion from qoder1's [Q1-DBPATH-HAZARD], run BEFORE any write:
nice -n 19 timeout 60 python3 -S -c "import sys; sys.path.insert(0,'.'); import config; print(config.DB_PATH)"
```
It must print a path **inside my own worktree**, and it must not name `merged_catalog_20261025.db`. Measured
2026-11-01 from `/tmp/q3_premerge`: `/tmp/q3_premerge/Fast_Fetch/fast_fetch.db` — and that file **does not
exist**, because `DB_PATH` is `BASE_DIR`-relative (`config.py:119`, `BASE_DIR` at `:101`) while `.gitignore:18
*.db` keeps a worktree from ever receiving the link. That is the structural reason this lane is clean, not a
lucky one; the hazard is real in `/opt/radd-stream`, where `Fast_Fetch/fast_fetch.db` has been a symlink onto
the live catalog since 00:32:17 (`/home/ubuntu/radd-stream-data/fast_fetch.db` likewise, at 00:32:29 — both
measured, both **reported as found and not fixed**, creator unknown). So a default-path write from the live
tree *is* a production write and the command line looks identical either way, which is why Step 5.0 exists
rather than a rule of thumb. If the print names the merged catalog: **stop**, do not merge, report.
```
nice -n 19 python3 -S merge_catalogs.py /home/ubuntu/radd-stream-data/vegamovies.db \
  --target-db /home/ubuntu/radd-stream-data/merged_catalog_premerge_20261101.db \
  2>&1 | tee /home/ubuntu/radd-stream-data/merge_01_vegamovies.log
```
Order and reason: **vegamovies first** — 13,370 posts, the lowest row count of the five mergeable sites, so
it buys a measured per-post rate for the cheapest possible price. Then **pause and report the rate** before
bolly4u (15,192), katmoviehd (38,154 — the largest walk), filmyhit (16,943). The `--target-db` must be the
copy's full path, and the invocation must never omit it: `merge_catalogs.py:478` (qoder1 corrected my `:473`
— that was drift, re-verified at the line I cite now) falls back to
`$RADD_DB_PATH` (now exported at `.bashrc:158` as the live catalog) and then to `BASE_DIR/fast_fetch.db`
(now the symlink) — both spellings land on production.
Cost, mechanism not number: the per-post path is **O(posts) connection cycles**, not O(bytes) —
`save_scraped_data` (`:380`) and `fast_fetch.get_db()` (`:393`) each open their own connection, and
`get_db` (`fast_fetch.py:880-896`) runs `journal_mode=WAL`, `busy_timeout`, `foreign_keys` then commit and
close every time, on a 6.4 GB → 7 GB WAL database on one vCPU. Progress prints are gated at one line per 100
posts (`:413`), so stdout is ~840 lines and is not the cost. **Duration: unmeasured.** Which is why step 5
ends with a report, not a continuation.

**Step 5.5 — mp4moviez, LAST (C3R): convert to a new vault, then merge the vault.**
```
nice -n 19 python3 -S /tmp/q3_premerge/Fast_Fetch/importers/convert_mp4moviez.py \
  --source /home/ubuntu/radd-stream-data/mp4moviez.db \
  --target /home/ubuntu/radd-stream-data/mp4moviez_staging_20261101.db \
  2>&1 | tee /home/ubuntu/radd-stream-data/convert_05_mp4moviez.log
stat -c '%n %F %s %.19y' /home/ubuntu/radd-stream-data/mp4moviez.db   # must STILL be 31,354,880 / 2026-10-27 22:51:22
nice -n 19 python3 -S merge_catalogs.py /home/ubuntu/radd-stream-data/mp4moviez_staging_20261101.db \
  --target-db /home/ubuntu/radd-stream-data/merged_catalog_premerge_20261101.db \
  2>&1 | tee /home/ubuntu/radd-stream-data/merge_05_mp4moviez.log
```
Two guards, both measured tonight rather than assumed. **(a) The target must be a new name.** The path
qoder1's dispatch used, `mp4moviez_staging.db`, already exists (34,193,408 B, 2026-10-29 05:25:00) and the
converter **refuses an existing target without `--force`** (`convert_mp4moviez.py:548-549`), so the command as
dispatched exits non-zero and converts nothing. A fresh name also keeps the 05:25 vault on disk as the
evidence for (b); `--force` is the alternative and it is safe for the legacy file either way — the build goes
to a `mkstemp` sibling and `os.replace`s onto the target (`:453`, `:519`), and `--source == --target` is
refused outright (`:432`) — but it destroys the only artifact that shows the delta. **(b) Assert against the
converter's own printed accounting, never against the file that happens to sit at that path.** The 05:25
vault holds 11,403 / 54,263 / 54,263 / 43 flagged where the 10-29 measurement recorded 28,066 works / 54,267
releases / 54,267 sources / 88 adult rows, and its mtime precedes both converter commits (`81cdff8` 05:53,
`eac15bb` 07:55). If tonight's convert output does not reproduce the 10-29 numbers: **stop, report the delta,
merge nothing from it** — that is qoder1's own instruction and I take it literally, because the −45 flagged
rows in the stale vault are an adult-exposure gap and those do not get discovered after a deploy.
Cost: a 31 MB read + a ~34 MB write for the convert (nothing like Step 2), and the merge itself is the same
O(posts) connection-cycle shape as Step 5 at 28,066-post scale — the 10-29 proof measured **710 s** for
exactly that merge into a throwaway target, so this is the one merge in the plan with a measured duration
instead of an unmeasured one, and it is the largest single site walk after katmoviehd.

**Step 6 — after each merge, cheap assertions on the copy (never a second `integrity_check`).**
```
stat -c '%n %s' merged_catalog_premerge_20261101.db-wal merged_catalog_premerge_20261101.db-shm
sqlite3 merged_catalog_premerge_20261101.db "PRAGMA wal_checkpoint(TRUNCATE);"   # ONLY here: this file is mine, no other writer
sqlite3 -readonly merged_catalog_premerge_20261101.db "SELECT (SELECT COUNT(*) FROM posts), ...same four..."
```
The checkpoint is legitimate on the copy and nowhere else, and the reason is exactly the one rule in this
plan: I am the only opener of that file, and the source-side checkpoint is retired (C1). The pair must be
absent or 0 bytes when the merge process exits; a stray pair is reported, not deleted.
**STOP after Step 5+6 for vegamovies only: report the measured per-post rate and wait for qoder1's go.**
Then bolly4u, katmoviehd, filmyhit run **one at a time**, each followed by Step 6 — never a batched loop,
because the rate the first merge measures is the only number that says whether the remaining sites fit in the
window that is paying for them. **mp4moviez goes last** (Step 5.5), on qoder1's reasoning and not mine: it is
the one step in this plan whose behaviour they have read but not executed, so it is the one that gets bought
with the most measured room rather than spent inside it.

**Step 7 — the report** at `/home/ubuntu/DATABASE_MERGE_REPORT.md`: per-site `posts_created` /
`posts_merged` / `releases_merged` / `sources_merged` / `posts_conflicted`, the adult fold's
`exposures_found` / `adult_rows_folded` / **`adult_exposures_remaining`**, before/after counts of the four
counted tables (`posts`, `releases`, `download_sources`, and `posts WHERE is_18_plus=1` — "four" there names
tables, not sites; five sites are merged) and of `is_18_plus=1`, the copy's size and `integrity_check` text,
timings per step, and the
deployability verdict. **mp4moviez is reported as INCLUDED, merged = FIVE sites** (C3R-final), through its
converted vault, and the report carries the converter's own accounting rather than a restatement of my table:
works / releases / sources as printed by the run, plus **344 duplicate pages merged, 16,168 rows skipped for
having no release, 9 takedown notices dropped, 88 adult rows carried, 0 null keys** as the 10-29 measurement
predicted them — and if tonight's converter output disagrees with those numbers, the run **stops and reports
the delta instead of merging the surprise**, which is the same paragraph's requirement in Step 5.5 and must
not be reconciled after the fact in prose. The report also names the legacy `mp4moviez.db` re-verification
(31,354,880 B / 2026-10-27 22:51:22) to prove the source was never written, and the stale 05:25 vault
(11,403 / 54,263 / 54,263 / 43) as the comparator that was deliberately left intact by using
`mp4moviez_staging_20261101.db` instead of `--force`. No path may contain a credential value; the report names
files, not tokens.

## Expected row-count delta — computed from measured inputs, bounded rather than predicted

Inputs, each measured once read-only:

| site | posts | releases | sources | flagged | mergeable? |
|---|---|---|---|---|---|
| vegamovies | 13,370 | 131,658 | *not recorded* | 445 | yes (family `unified`) |
| bolly4u | 15,192 | 41,004 | 22,003 | 972 | yes |
| katmoviehd | 38,154 | 146,244 | 163,972 | 1,017 | yes |
| filmyhit | 16,943 | 25,520 | 112,973 | 117 | yes |
| **four direct** | **83,659** | **344,426** | **298,948 (+vegamovies, unrecorded)** | **2,551** | |
| mp4moviez **legacy** | 29,848 | 54,267 | **no table** | 91 | only through the converter (C3R) |
| → vault, 10-29 **measured** | **28,066** | **54,267** | **54,267** | **88** | yes — this is the target |
| → vault, on disk since 05:25 | 11,403 | 54,263 | 54,263 | 43 | **STALE — merging it is the surprise** |
| **five sites** | **111,725** | **398,693** | **353,215 (+vegamovies, unrecorded)** | **2,639** | |

Legacy `mp4moviez.db` and both vault variants were counted read-only tonight (`29,848 / 54,267 / 91 flagged /
0 NULL flags`; `11,403 / 54,263 / 54,263 / 43`), so the stale-vault delta is measured here, not inherited
from the 10-29 log. The "five sites" row uses the **measured conversion target** (28,066), not the legacy
page count, because 344 duplicate pages collapse and 16,168 rows are skipped for having no release.

Target copy starts at **150,799 posts / 1,780,121 releases / 4,073,865 download_sources / 15,068 flagged**.
Upper bound with zero dedup — qoder1's restated bound with C3R included: **posts 150,799 + 83,659 + 28,066 =
≤ 262,524**; releases ≤ 2,178,814; download_sources ≤ 4,427,080 (+vegamovies' unrecorded contribution);
flagged ≥ 17,707 before the fold and higher after it, since the fold only ever adds flags. The honest form of
the expectation: the tool counts `posts_created` separately from `posts_merged` and retargets colliding
canonical keys (`:330-365`, counted in `posts_conflicted`), so **new posts = `posts_created`, somewhere in
0…111,725**, and I will not put a single predicted total in the report — the assertion is that the copy's
after-count equals 150,799 + the `posts_created` the tool itself printed. If they disagree, the merge is
wrong and the copy is discarded.

## Blockers that must be resolved before, not during

Status after C3R: **1 closed** (mp4moviez included via the converter, with two decisions landed — new target
name approved, no `--force` outside my own vault), **2 answered** (adult fold runs default-on), **3 and 4
still open as measurement gaps**, **5 standing as law**. Item 1 is kept in full because the reason it closed —
a grep of the fleet's own history — is the finding, not the closure.

1. **`mp4moviez.db` — CLOSED BY C3R: INCLUDED, through the converter.** This blocker went through three
   states in one night and the record of all three is the useful part. **(a)** I raised it: the legacy tables
   are `sitemap_cache, posts, sqlite_sequence, releases` — no `sources`, no `download_sources` — so
   `_source_family` (`merge_catalogs.py:41-47`) raises before a row moves. **(b)** qoder1's C3 ruled
   *exclude*, on four reasons: new code under a load hold, 29,848 zero-link tiles, folding adult flags against
   an empty evidence set, and unmeasurable dedup. **(c)** qoder1 reversed C3 at 01:5x
   (`/tmp/q1_c3_reversal.txt`) after finding the answer in **my own lane's record**: the code to do it exists
   and is on trunk — `Fast_Fetch/importers/convert_mp4moviez.py` with `test_convert_mp4moviez.py` beside it
   (`81cdff8`, then `eac15bb` "conserve every legacy row and account the skipped releases") — and
   [`20261029-…-mp4moviez-becomes-mergeable-and-a-fleet.md`](20261029-2026-10-29-session-mp4moviez-becomes-mergeable-and-a-fleet.md)
   already measured the whole path end to end: 29,848 legacy pages → **28,066 works / 54,267 releases / 54,267
   sources**, 344 duplicate pages merged, 16,168 rows skipped for having no release, 9 takedown notices
   dropped, 88 adult rows carried, 0 null keys, and a completed `merge_site_db` run in **710 s** with
   `posts_conflicted=0`. I re-checked every one of those claims against the tree rather than accepting them:
   the converter opens the source with `file:…?mode=ro` (`:436`), refuses `--source == --target` (`:432`),
   builds into a `mkstemp` sibling and `os.replace`s it onto the target (`:453`, `:519`), and contains no
   `DROP TABLE` / `RENAME TO` / `ALTER TABLE` at all. So three of the four exclusion reasons collapse — there
   is no 2 am code to write, the works are not zero-link (54,267 source rows), and the fold has evidence to
   corroborate against. **The one reason that survives is a reporting caveat, not a blocker:**
   `posts_conflicted` still cannot distinguish a flagged twin from an unflagged one.
   **What the grep would have missed, and what measurement caught:** the dispatch's exact `--target`,
   `mp4moviez_staging.db`, is **already on disk** — 34,193,408 B, mtime 2026-10-29 05:25:00 — and the
   converter **refuses an existing target without `--force`** (`:548-549`), so that command exits non-zero and
   converts nothing. Counted read-only, that file is **11,403 posts / 54,263 releases / 54,263 sources / 43
   flagged** — not the measured 28,066 / 54,267 / 54,267 / 88 — and its mtime precedes both converter commits,
   so it is pre-`81cdff8` output that was never rebuilt after the row-conservation fix. Two decisions follow,
   both qoder1's to make and neither of them mine to guess: the target name (I recommend
   `mp4moviez_staging_20261101.db`, which keeps the stale vault as evidence and costs 34 MB), and whether the
   43-vs-88-vs-91 adult-flag spread (stale vault / measured conversion / legacy table) is investigated before
   the merge. It should be: 16,663 posts and 45 flags is exactly the shape of defect this fleet does not get to
   find after a deploy, which is why Step 5.5 asserts against the converter's own printed accounting and
   merges nothing from a surprise.
   **The process rule, recorded because qoder1 asked for the rule and not just the correction:** their third
   wrong reason in this window (the "56-byte empty databases" line, the `wal_checkpoint` instruction, the C3
   exclusion) all failed the same way — a conclusion drawn from the document in front of them instead of from
   the record; the first two fell to a measurement, this one to a `grep mp4moviez` they had not run. The rule
   for the next lane, in both directions: **before you rule on an object, search the fleet's own history for
   its name** — and equally, the reversal was only safe because the checkpoint that answered it had been kept
   verbatim and indexed, which is the entire argument for the rotation layout.
2. **The adult reconciliation shape.** qoder1's condition is `MAX(is_18_plus)` per `canonical_key`; the
   standing law forbids a raw key-level `MAX` as an un-corroborated rule, because one mislabelled twin then
   hides a legitimate work forever. The merge already carries the sanctioned shape —
   `reconcile_adult_on_merge` (`:244-275`) folds via `fast_fetch.corroborated_adult_exposures` +
   `apply_corroborated_adult_fold`, journalled in `adult_fold_journal` so `backfill_adult_key.py --undo`
   reverses it — and it is **default-on** (`:280` in the signature, opt out with `--no-adult-fold` at
   `:465`). I will run it
   default-on and treat `adult_exposures_remaining != 0` as **NOT DEPLOYABLE**, stated in the report in those
   words. Its one weakness is ordering: the fold runs at the **end** of each merge (`:429`), which is fine on
   this copy (nobody reads it) and would not be fine on a live file. Line cites re-checked in this tree at
   `ef91096` rather than copied: the `def merge_site_db(...)` line is `:279` and `adult_fold: bool = True`
   lands on `:280`; qoder1's "`:464`" for `--no-adult-fold` is one line above the block — the
   `parser.add_argument("--no-adult-fold", …)` is at `:465-466`. Same construct, no disagreement; I quote the
   lines that carry the token.
3. **Dub collisions still have no number.** q2's `[Q2-DUB-COLLISION-CENSUS]` query exists and its corpus
   figures are queued on the load hold, so nothing may be claimed about the same film arriving twice under
   different dub sources (`themoviebox` is the named demonstrator). `posts_conflicted` is the only figure I
   will have, and it does not distinguish a flagged twin from an unflagged one.
4. **vegamovies' `post_sources`/`download_sources` count was never taken** — recorded as a gap rather than
   remembered as a number. Step 3's after-count is where it comes from.
5. **Deploy is the owner's, and the alias stays.** Per the decision: the copy is the merge product, the
   service keeps reading `merged_catalog_20261025.db` until the owner swaps it; no service restart, no tag,
   and **no repointing or deleting of the `fast_fetch.db` symlinks by this lane** — whoever made them at 00:32
   may be relying on the alias, and changing what `fast_fetch.py` opens is not a lane's call.

## What this plan is still waiting on

Everything I asked for has been answered, except one thing, and it is not mine to grant:

| ask | status |
|---|---|
| yes/no on mp4moviez | **answered, then re-answered: C3 excluded it, C3R includes it** through `convert_mp4moviez.py`, and my `--target` correction to `mp4moviez_staging_20261101.db` is **APPROVED as C3R-final** — with the standing rule *no `--force` on any path outside my own new vault* |
| acknowledgement that Step 2 is the one full production read | **given, and C4 halves its exposure: the baseline makes rollback a local `cp` instead of a second production read** |
| the gate | `load1 < 4.0` is **not** the gate any more. It is qoder1's **`SUSTAINED-UNDER4`** post (load1 < 4.0 for five consecutive minutes — "a dip is not a lift") **and** `MemAvailable > 1,500 MB` **and** `SwapFree > 800 MB`. qoder1 holds a persistent monitor for exactly this. |

Plan approval is explicitly **not** a licence to start. `load1 3.45 / load5 3.99 / load15 5.08` at read time
is a dip, and I treat it as one — and C3R's own arithmetic says tonight will not fund this plan: the sub-4
window qoder1 caught at 01:52 (load1 3.48) closed at 01:55 (load1 4.85) after **~3 minutes**, against my
**3–10 minute** estimate for the 6.4 GB copy read, so the window was shorter than the step it would have to
hold. load1 was **5.57** when qoder1 re-read it for the consistency note. Nothing starts until
`SUSTAINED-UNDER4` is posted with load5 trending down, or qoder1 says plainly that no window is coming — and
in that case the plan stays queued, which is a valid outcome and not a failure.

## Status

**Gated, corrected, C3-reversed, and STOPPED at the sha.** Nothing above has been executed: no copy, no
baseline, no convert, no merge, no `integrity_check`, no checkpoint, no write to any database. Executions in
this window, all `nice -n 19` and all read-only or `/tmp`-scratch: `stat`/`df`/`fuser`; one 8 MB `.backup` +
`VACUUM INTO` calibration and one crash-simulated WAL test on a scratch copy (removed afterwards); row counts
on `mp4moviez.db` (31 MB) and on both vault variants (34 MB) through `sqlite3 -readonly`; a grep and two
`sed`/`awk` reads of `convert_mp4moviez.py` and `merge_catalogs.py` to check the reversal's claims instead of
adopting them; and the offline docs module. C1–C4 and the C3R reversal are landed in place in this same file;
the pre-correction version remains readable at `ef91096` and the C3-exclusion version in the commit before
this one, which is the point of keeping the plan in git rather than in a chat log — a reversal that only
exists in the last message is indistinguishable from a rumor.
**Landed: trunk `f12ab3f`** (main == master), Backend CI `completed success` on both refs (runs 41247930663 /
41247930667), footprint exactly this lane's four documentation paths. Three index lines were corrected during
the landing and all three are re-verified here against the directory rather than taken on faith:
`Fast_Fetch/CONTINUITY.md` now claims **65 session files (63 dated + 2 undated)** — measured
`ls Fast_Fetch/checkpoints/*.md` minus `README.md` = 65, 63 dated, 2 undated; `docs/SESSION_CHECKPOINT.md`
item 1 now claims **60 files** — measured 60 of 61 paths minus `README.md`, 58 of them dated; and
`checkpoints/README.md` keeps both q5 bullets plus this lane's single merged `[Q3-PREMERGE-PLAN] +
[Q3-PREMERGE-P]` bullet, with my earlier separate line dropped — indexing a retired verdict twice is a second
index bug wearing a union's clothes. All three are what `test_the_index_counts_are_the_directory_listings`
compares, which is why an either/or merge resolution goes red here instead of going quiet. That module re-run
offline in the re-based tree: 22 tests OK.

**Re-branch onto `4b025bf` (trunk's 6th landing), 06:2x — and the counts above are now history, not current.**
q1 moved trunk from `f12ab3f` through `6014dd5` to `4b025bf` (q5's release-row truth, operator-port dated read,
and a continuity rotation), so a head sitting on `f12ab3f` stopped being fast-forwardable and gating it would
have reverted trunk. This commit was re-branched as `q3-premerge-exec-on-4b025bf`; the cherry-pick applied with
**no conflict**, because trunk gained nothing under `docs/` that this lane had edited — the numbers in the
paragraph above are therefore a true record of *that* tree and a stale claim about *this* one, which is why the
rule is to re-measure rather than to assume a clean cherry-pick means nothing moved underneath. Measured here,
`nice -n 19`, read-only listings, no test module (q1 revoked the partial lift at 06:2x on load 7.41):
`ls Fast_Fetch/checkpoints/*.md` minus `README.md` = **67**, of which **65 dated + 2 undated**, and
`Fast_Fetch/CONTINUITY.md:10` claims exactly that; `ls docs/checkpoints/*.md` minus `README.md` = **60**,
**58 dated**, and `docs/SESSION_CHECKPOINT.md:7` claims exactly that. Byte ceilings hold: `CONTINUITY.md`
10,765 B and this file's `SESSION_CHECKPOINT.md` 11,941 B, both under the 12,000 the guard enforces.

**Freeze, restated so nobody over-reads the load number:** load is genuinely under 4 now (load1 1.62), and
qoder1 released exactly one inch of it — single offline test modules, one at a time, `nice -n 19`,
timeout-wrapped. That release does **not** cover this merge, which is frozen for **irreversibility, not for
load**, nor Gradle (owner-gated at load < 0.5), nor any crawl, nor any production read — and a pre-merge
`.backup` of the 6.2 GB catalog **is** a production read, so Steps 2 and 3.5 stay queued however idle the box
gets. Per the standing instruction, **this lane stops at the sha.**
