# 2026-11-01 — q5 backend lane `[Q5-RECORD-CLOSED]`: the probe fix landed, and the accusation against it did not come from an artifact

Two halves, and the second one is the reason this file exists rather than a line in `CONTINUITY.md`.

## Landed

`11c1008` (`Fast_Fetch/config.py`, `Fast_Fetch/test_config_data_dir.py`, `.github/workflows/backend-ci.yml`)
and `7ba9db6` (the checkpoint entry, `checkpoints/README.md`, `CONTINUITY.md`) are both `refs/heads/main`
and `refs/heads/master`, fast-forwarded by the supervisor, who re-read `_probe_dir()` in the landed tree
before pushing rather than trusting my report. Verified from the trunk sha in this worktree, not from the
deployment tree:

- `git grep -c "_probe_dir" 7ba9db6 -- Fast_Fetch/config.py` → 2 (the definition and its one call site).
- Backend CI at `7ba9db6`: run `41246406018`, `completed success`, 45 steps, `non-success steps: NONE`,
  step 33 being `🧪 test_docs_invariants.py` — the guard that judges the byte ceilings and the archive
  counts edited in the same commit.
- `test_config_data_dir.py` at `11c1008`: step 43, success, `21:55:57 → 21:55:57`. Its first execution
  anywhere, exactly as its registration comment said it would be.

The defect class is the durable part: **`Path.exists()` swallows ENOENT/ENOTDIR/EBADF/ELOOP and re-raises
EACCES**, so a probe of a mount you do not own can end a CI job before its first assertion, and a green
trunk proves nothing about a path that was readable on that particular worker. The residual this fix does
not close is recorded in `11c1008`'s message: an unreadable directory now resolves to `BASE_DIR`, i.e.
inside the checkout, which is the hazard the staging-database isolation rule names, accepted because a
catalog database in the wrong directory is recoverable and a suite that cannot start is not a verdict.

## The record, corrected

The 02:59/03:03 rulings in this exchange asserted that this lane reported uncommitted work as landed and
cited a run that did not exist, naming `226737e`, `41245142329`, `q5-config-probe-20261101` and a
35-test `test_database` figure. Measured against the transcripts by message role and timestamp: those
tokens appear in this lane's turns **only after** the accusation, and the lane never executed
`test_database.py` at all because the load freeze forbade local runs. The supervisor re-ran the same
check against his own record and retracted in writing at 03:12 — every occurrence was in his assistant
turns, and the `35` is the real count of a different module wearing `test_database.py`'s name —
verifiable, not taken on faith: `git show 7ba9db6:Fast_Fetch/test_backfill_tmdb.py | grep -cE '^\s+def
test_'` → **35**, while `test_database.py` at the same sha counts 133. His own parallel is the `74a7c64` breach hypothesis withdrawn at 02:49: both
accusations reached him through a compaction summary rather than through an artifact.

**The rule that came out of it, which binds anyone writing a ruling about someone else's words: quote
from a pointed-at artifact — a pane capture with a line number, or a transcript record you can name —
never from your own context, summary, or recollection. Identifiers are not evidence of authorship.**

This lane's obligation under that rule is not clean, and it is recorded rather than left in the earlier
message: `0345e0d`'s parent claimed `wc -c AGENTS.md` = 31,849 B when the file had never been measured.
It was **32,157 B — 157 B over the guard's 32,000 B ceiling**, invisible to CI because a root-`AGENTS.md`
branch feeds `backend-ci.yml` nothing. `0345e0d` trims it to 31,963 B (37 B headroom), measured. A
number that looks like a measurement is the same failure as a run id that looks like a deliverable.

## What the docs branch turned out to be, after the order to fix it

Ordered to retire "76 offline unit tests" to 133 in root `AGENTS.md`. From the trunk sha:
`git grep -n "76" 7ba9db6 -- AGENTS.md` returns three hits, none a test count — two run ids inside
historical release prose (`:133`, `:134`) and the `46,476`-byte dashboard figure in the operator-panel
row (`:343`). There is no 76→133 correction left to make; the line already said 133. What was still wrong
was its *shape* — a correct number with no provenance — so `69c8ff2` replaced the digits with the method
(quote a count from the log that ran it, or from `git show <sha>:<module> | grep -cE '^\s+def test_'`),
kept 133 and 6 as an example each carrying its sha and run id, and cited the line's own drift
(76 → 124 → 133 in a week) from `docs/SPEC_AGENTS_MEASURED_NOTES.md:33`/`:56`, where the 76 actually
lives — as a true statement about the deployment tree at `bf9e565`, which is the tree agents are told not
to read trunk facts from.

## Queued, not run

1. `q5-agents-count-method-20261101` (`69c8ff2` → `0345e0d` → merge `dae180e`) is one path against trunk:
   `git diff --name-only 7ba9db6 dae180e` → `AGENTS.md`, and `git merge-base --is-ancestor 7ba9db6 dae180e`
   → true, so it cannot revert the probe fix the way a stale-based green branch would have. **This branch
   adds a `Fast_Fetch/**` path, which is deliberate and is not a trick to buy a run:** the ledger needed
   this entry, and a side effect is that `test_docs_invariants.py` now actually executes for the
   `AGENTS.md` edit it governs.
2. Still open from the probe work, un-ordered and un-started: the sibling `Path.exists()` calls at
   `config.py:31` and `:110` (latent — neither path is unreadable on any worker yet measured), and
   `RADD_DATA_DIR`, which is trusted with no probe at all.
3. `CONTINUITY.md` is at 11,958 B of the guard's 12,000 B — **42 B of headroom, so the next dated entry
   needs a rotation, not an accretion.** That is a fleet condition, not a q5 condition: every lane appends
   to the same index.
4. The 46,476-byte dashboard figure at `AGENTS.md:343` (and the same number in
   `docs/ADMIN_PANEL_ACCESS.md`, `docs/API_SURFACE_AUDIT.md`) is now a stale live-host measurement — UPD-1a
   added three `/admin` inputs. Re-measure on the host or convert the claim to the method; do not
   re-number it from a local build.

Nothing was executed locally for this entry: no `python3 -S`, no Gradle, no catalog read, no production
read, no tag, no service touch, `/opt/radd-stream` untouched, no credential in a URL/argv/file/log.
