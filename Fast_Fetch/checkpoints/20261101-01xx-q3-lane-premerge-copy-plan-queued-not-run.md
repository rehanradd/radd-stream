# 2026-11-01 01:2x — q3 backend lane `[Q3-PREMERGE-PLAN]`: the frozen merge, planned to the command,
# costed where I measured it and marked unmeasured where I did not

Lane: **qoder3**. Tree: `/tmp/q3_coins`, branch `q3-coins-engine` at `4aefac3`. Requested by
`Q1 TARGET DECISION plus a CORRECTION 01:20`: prepare the sequence, the measured cost per step and the
expected row-count delta as a **queued action**, hand the sha, and do not run it — load1 was 9.91 at the
notice and 6.57 at 01:23, so the freeze holds. **Nothing in this file ran against the catalog.** The only
executions were on 8 MB staging files and a scratch db in `/tmp`, all `nice -n 19`.

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
the live catalog read-write "to be safe" would itself rewrite production state. Controls, in order:

1. `-readonly` on every open of anything that is not mine, always, and verify after each step that the
   source's size and mtime are unchanged (measured here: `animahd.db` came out of both copy methods at
   8,269,824 B / mtime 10-28 22:57:00 with no sidecars created).
2. Still measure the five sources' `-wal` before touching them (three are 0 bytes: vegamovies 00:22:57,
   bolly4u 00:23:09, katmoviehd 00:23:11; two have no pair at all — filmyhit, mp4moviez — and `animahd.db`
   reads `journal_mode=delete`, which is what a no-sidecar db looks like rather than a WAL one). If any
   `-wal` is **non-zero**, that is new information and I stop and report instead of checkpointing.
3. The gap I cannot close honestly: I tested a *dead* WAL with no writer. I did not test `.backup` against
   a **live concurrent writer**, because that means writing to production to test it. The online backup API
   is documented to resolve that by taking a page snapshot and catching up, and the catalog's mtime has been
   10-29 10:52:37 throughout tonight, so the window in which a writer could change a count is narrow — but
   the compensating check is step 3's row counts, not my confidence.

## The command sequence, in order, with its cost

Every step gated on: qoder1 posts `load1 < 4.0`, and `MemAvailable > 1,500 MB` / `SwapFree > 800 MB` hold.
One statement per invocation, never a retry loop; a failed step aborts the sequence and is reported.

**Step 0 — preflight, cheap, may run any time (`stat`/`df`/`fuser` only).**
```
uptime; free -m; df -b /home | tail -1        # need > 14 GB free for the copy + headroom
stat -c '%n %F %s %.19y' /home/ubuntu/radd-stream-data/fast_fetch.db \
                          /opt/radd-stream/Fast_Fetch/fast_fetch.db   # both must still be `symbolic link`
for s in vegamovies bolly4u katmoviehd filmyhit mp4moviez; do stat -c '%n %s %.19y' $s.db $s.db-wal; done
fuser /home/ubuntu/radd-stream-data/merged_catalog_20261025.db        # expect pid 1835070 only
```
Abort condition: if either `fast_fetch.db` name has stopped being a symlink, or its target is no longer
`merged_catalog_20261025.db`, the picture changed under me again and everything reverts to a blocker report.

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
time sqlite3 -readonly /home/ubuntu/radd-stream-data/merged_catalog_20261025.db \
  ".backup /home/ubuntu/radd-stream-data/merged_catalog_premerge_20261101.db"
```
`.backup` not `cp` (a WAL source, mid-WAL per the table above) and not `VACUUM INTO` (measured: it
**defragments**, 8,269,824 → 8,208,384, i.e. about −0.7 %, and forces `journal_mode=delete` on the output —
so its size would not match the source and the size check stops meaning anything). Verification, cheap and
structural: copy size **equals** 6,396,899,328 B exactly; `stat -c %F` on the copy is `regular file`; the
source's mtime is **still** 10-29 10:52:37; and the `-wal`/`-shm` pair my open created on the source is gone
again (measured behaviour: a clean close deletes it — the catalog's pair from 00:23 was absent by 00:32).

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

**Step 4 — source WAL assertion, read-only, no write (see the retirement above).**
```
stat -c '%n %s %.19y' /home/ubuntu/radd-stream-data/{vegamovies,bolly4u,katmoviehd,filmyhit,mp4moviez}.db-wal
```
0 bytes or absent → proceed and record it. Non-zero → **stop**, report, and let qoder1 decide on the
checkpoint, because that is the one case where the frames hold rows the main file does not.

**Step 5 — the merges, sequential, calibrated on the first one.**
```
cd /tmp/q3_coins/Fast_Fetch
nice -n 19 python3 -S merge_catalogs.py /home/ubuntu/radd-stream-data/vegamovies.db \
  --target-db /home/ubuntu/radd-stream-data/merged_catalog_premerge_20261101.db \
  2>&1 | tee /home/ubuntu/radd-stream-data/merge_01_vegamovies.log
```
Order and reason: **vegamovies first** — 13,370 posts, the lowest row count of the four mergeable sites, so
it buys a measured per-post rate for the cheapest possible price. Then **pause and report the rate** before
bolly4u (15,192), katmoviehd (38,154 — the largest walk), filmyhit (16,943). The `--target-db` must be the
copy's full path, and the invocation must never omit it: `merge_catalogs.py:473` falls back to
`$RADD_DB_PATH` (now exported at `.bashrc:158` as the live catalog) and then to `BASE_DIR/fast_fetch.db`
(now the symlink) — both spellings land on production.
Cost, mechanism not number: the per-post path is **O(posts) connection cycles**, not O(bytes) —
`save_scraped_data` (`:380`) and `fast_fetch.get_db()` (`:393`) each open their own connection, and
`get_db` (`fast_fetch.py:880-896`) runs `journal_mode=WAL`, `busy_timeout`, `foreign_keys` then commit and
close every time, on a 6.4 GB → 7 GB WAL database on one vCPU. Progress prints are gated at one line per 100
posts (`:413`), so stdout is ~840 lines and is not the cost. **Duration: unmeasured.** Which is why step 5
ends with a report, not a continuation.

**Step 6 — after each merge, cheap assertions on the copy (never a second `integrity_check`).**
```
stat -c '%n %s' merged_catalog_premerge_20261101.db-wal merged_catalog_premerge_20261101.db-shm
sqlite3 merged_catalog_premerge_20261101.db "PRAGMA wal_checkpoint(TRUNCATE);"   # ONLY here: this file is mine, no other writer
sqlite3 -readonly merged_catalog_premerge_20261101.db "SELECT (SELECT COUNT(*) FROM posts), ...same four..."
```
The checkpoint is legitimate on the copy and nowhere else, and the reason is exactly the one rule in this
plan: I am the only opener of that file. The pair must be absent or 0 bytes when the merge process exits; a
stray pair is reported, not deleted.

**Step 7 — the report** at `/home/ubuntu/DATABASE_MERGE_REPORT.md`: per-site `posts_created` /
`posts_merged` / `releases_merged` / `sources_merged` / `posts_conflicted`, the adult fold's
`exposures_found` / `adult_rows_folded` / **`adult_exposures_remaining`**, before/after counts of all four
tables and of `is_18_plus=1`, the copy's size and `integrity_check` text, timings per step, the mp4moviez
blocker, and the deployability verdict. No path may contain a credential value; the report names files, not
tokens.

## Expected row-count delta — computed from measured inputs, bounded rather than predicted

Inputs, each measured once read-only:

| site | posts | releases | sources | flagged | mergeable? |
|---|---|---|---|---|---|
| vegamovies | 13,370 | 131,658 | *not recorded* | 445 | yes (family `unified`) |
| bolly4u | 15,192 | 41,004 | 22,003 | 972 | yes |
| katmoviehd | 38,154 | 146,244 | 163,972 | 1,017 | yes |
| filmyhit | 16,943 | 25,520 | 112,973 | 117 | yes |
| mp4moviez | 29,848 | 54,267 | **no table** | 91 | **NO — raises** |
| **four mergeable** | **83,659** | **344,426** | **298,948 (+vegamovies, unrecorded)** | **2,551** | |
| **all five** | 113,507 | 398,693 | — | **2,642** | |

Target copy starts at **150,799 posts / 1,780,121 releases / 4,073,865 download_sources / 15,068 flagged**.
Upper bound with zero dedup (four sites): **234,458 / 2,124,547 / 4,372,813 / ≥ 17,619**. The honest form of
the expectation: the tool counts `posts_created` separately from `posts_merged` and retargets colliding
canonical keys (`:330-365`, counted in `posts_conflicted`), so **new posts = `posts_created`, somewhere in
0…83,659**, and I will not put a single predicted total in the report — the assertion is that the copy's
after-count equals 150,799 + the `posts_created` the tool itself printed. If they disagree, the merge is
wrong and the copy is discarded.

## Blockers that must be resolved before, not during

1. **`mp4moviez.db` cannot be merged at all.** Its tables are `sitemap_cache, posts,
   sqlite_sequence, releases` — no `sources`, no `download_sources` — so `_source_family`
   (`merge_catalogs.py:41-47`) raises `ValueError("Source database has neither download_sources nor
   sources table")` before a row moves. Its 29,848 posts / 54,267 releases / 91 flagged rows are therefore
   *outside* the 783 MB the mission counted. The fix is a schema decision (promote its `releases` into the
   staging shape, or exclude it and say so in the report) — not a retry, and not a `--force`.
2. **The adult reconciliation shape.** qoder1's condition is `MAX(is_18_plus)` per `canonical_key`; the
   standing law forbids a raw key-level `MAX` as an un-corroborated rule, because one mislabelled twin then
   hides a legitimate work forever. The merge already carries the sanctioned shape —
   `reconcile_adult_on_merge` (`:244-275`) folds via `fast_fetch.corroborated_adult_exposures` +
   `apply_corroborated_adult_fold`, journalled in `adult_fold_journal` so `backfill_adult_key.py --undo`
   reverses it — and it is **default-on** (`:279-302`, opt out `--no-adult-fold` at `:464`). I will run it
   default-on and treat `adult_exposures_remaining != 0` as **NOT DEPLOYABLE**, stated in the report in those
   words. Its one weakness is ordering: the fold runs at the **end** of each merge, which is fine on this
   copy (nobody reads it) and would not be fine on a live file.
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

## What I need from qoder1 to un-freeze it

`load1 < 4.0` posted; an explicit yes/no on (1) above (merge four sites and report mp4moviez as excluded, or
hold the whole mission for its schema decision); and acknowledgement that step 2 is a **full read of the
production catalog** — the one production read this plan requires, run once, never retried.

## Status

Queued only. Nothing above has been executed: no copy, no merge, no `integrity_check`, no checkpoint, no
write to any database. Executions in this window: `stat`/`df`/`fuser`/`awk`/`grep`, one 8 MB `.backup` +
`VACUUM INTO` calibration and one crash-simulated WAL test in `/tmp` (scratch removed afterwards), and the
offline docs module. `q3-coins-engine` remote head after this entry is recorded in the commit that carries
it.
