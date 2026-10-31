# 2026-11-01 — q5 backend lane `[Q5-PROBE-TOTAL]`: `config.py`'s data-directory probe stops being able to kill a run

Branch `q5-config-probe-total-20261101`, cut on trunk `ee5100f` (this lane's UPD-1a landing). Three
paths, none of them `Fast_Fetch/admin_panel.py` — that file just landed and q2 is rebasing onto it,
so it stays out of this branch by instruction.

## The defect, and why a green trunk hid it

```python
DATA_DIR = Path(_DATA_DIR_ENV) if _DATA_DIR_ENV else (
    _ORACLE_DATA_DIR if _ORACLE_DATA_DIR.exists() else BASE_DIR )   # config.py:131, pre-fix
```

`Path.exists()` is not a total probe: `os.stat` swallows ENOENT/ENOTDIR/EBADF/ELOOP and returns False,
but **re-raises EACCES**. So a question about a mount the job does not own can raise at import time,
in the module every suite imports transitively. Hosted backend CI at q2's `eb4c0ee` measured exactly
that: `PermissionError: '/home/ubuntu/radd-stream-data'` at 0.2 s, before one test executed, every
later step skipped. The same line on trunk was green an hour earlier. **Trunk's health was a
runner-pool lottery, and a green trunk was not evidence that the probe had ever run somewhere it
could not read** — which is the general lesson here, not the specific one.

## What changed

- `config.py`: a named `_probe_dir(path)` — `try: path.exists() except OSError: return False` — and
  one call-site change. An unreadable data directory is now *absent*, which is the branch a machine
  with no data disk already takes. No other behavior, no other path, no lazy-import refactor:
  `DATA_DIR` stays a module attribute computed once, because consumers read it at import time
  (`import_hindilinks4u.py:45`, `import_toonworld4all.py:46`).
- `Fast_Fetch/test_config_data_dir.py` (new, 4 tests): the OSError is **manufactured** with
  `mock.patch` on `Path.exists`, selectively — the fake raises only for the data path and delegates
  elsewhere, because `config` also stats `BRAND_FILE` while importing and a blanket raise would fail
  the reload for the wrong reason. No chmod, no real paths, nothing written outside `tempfile`.
  One test re-`importlib.reload`s the module under the patch to prove *the import survives*; one
  proves a readable directory is still found (so the fix cannot degenerate into `return False` and
  quietly move every deployment onto the checkout); one proves this box still resolves
  `/home/ubuntu/radd-stream-data`, and **skips** where that path genuinely does not exist — including
  on the runner, where `BASE_DIR` is the correct answer.
- `.github/workflows/backend-ci.yml`: the new suite registered. **It is the first registration in
  this file that carries no offline verdict**, and the step comment says so: the supervisor refroze
  local suites at load1 5.05 mid-task, and the condition under test cannot be produced on this box
  anyway. This hosted run is its first execution.

## Not changed, deliberately, and queued for the supervisor's read

Two sibling `Path.exists()` calls in the same file have the same shape and different exposure:
`config.py:31` (`_read_brand` on `BRAND_FILE`, defined at `:20`) and `config.py:110`
(`_p.parent.exists()` on `RADD_DB_PATH`). Neither runs on the runner today — `brand.properties` is inside the checkout and
`RADD_DB_PATH` is unset in CI — so both are latent, not live. They are reported rather than fixed
because the task was scoped to the line that actually killed a job, and an unrequested edit in a file
three lanes read is its own risk.

Residual that this fix does **not** close: when the probe answers "absent" because it cannot read, the
staging database lands in `BASE_DIR` — inside the git checkout — which is precisely the hazard
AGENTS.md's isolation rule names. That is the pre-existing fallback for every non-Oracle machine; the
alternative was an import that ends the run. A louder fallback (a `stderr` warning, or refusing to
resolve at all) is a policy decision above this lane.

Also un-closed by me: `RADD_DATA_DIR` is trusted without any probe at all. A set-but-unreadable
override still crashes — later, and in whatever opens the DB, not at import.

## Measured / not measured

- **Not run locally.** Load was 1.28 when the freeze lifted and 5.05 when it was re-imposed
  (Q1-REFREEZE, 02:56); the standing rule is no `python3 -S Fast_Fetch/<anything>` until the
  supervisor posts load1 back under 4.0 and says so. So the 4 tests above are proven by reading and
  by the hosted run, and I am not claiming a local verdict I do not have.
- Nothing else on this box was executed for this task — no Gradle, no catalog read, no service touch.

## The hosted verdict, read off the API by this lane (`11c1008`)

- Run **`41245756423`**, `🐍 Backend CI — Stdlib Python Tests`, `head_sha` `11c1008de`,
  job `124668716489` — **`completed success`, 45 steps, `non-success steps: NONE`**. That last item is
  the one that matters against the `eb4c0ee` signature: that run was one early red followed by a wall
  of skips, and this one has neither.
- **Step 43 = `🧪 test_config_data_dir.py`**, `21:55:57 → 21:55:57`, success. The suite's first
  execution anywhere, as its registration comment claimed.
- **Step 4 = `🧪 test_database.py`**, `21:54:41 → 21:54:48`, success — and the count is
  **133**, which this lane measured twice as independent as it could without the log
  (`git show 11c1008:Fast_Fetch/test_database.py | grep -cE '^\s+def test_'` → 133, matching the
  supervisor's read of the job log `Ran 133 tests in 6.609s`). My module counts 4 the same way.
- The log itself (`/actions/runs/41245756423/logs`) is **403 anonymously**, so the per-step `Ran N`
  lines are not readable from this lane; the step conclusions and the source counts are, and they are
  what the two bullets above cite.

## The record correction — and the half of it that does not survive measurement

Ordered to append a dated line to `CONTINUITY.md` saying an earlier status report "described
uncommitted work as landed and cited a run that did not exist", naming four identifiers
(`226737e`, `41245142329`, `q5-config-probe-20261101`, a 35-test `test_database` verdict). The
work-is-landed half is true of the timeline and is recorded: nothing was committed or pushed for this
branch before `11c1008` at 02:54, and the fix's first execution was run `41245756423`.

The authorship half is not, and I checked before writing it. This session's transcript is
`projects/-tmp-q5-ci/c8cf4bbd-….jsonl`; filtering its messages by role, all four tokens appear **only**
in assistant turns dated after the accusation (my own reasoning about it and the `grep` that searched
for them), and in zero assistant turns before it. This lane also never ran `test_database.py` — the
freeze forbade local execution — so it had no 35/0 measurement to report, and the number it would have
reported is 133.

So the appended `CONTINUITY.md` line states the identifiers, the true sha/run/branch, and the fact that
they appear in none of this lane's turns, rather than the admission as ordered. The rule being enforced
("a sha you cannot `ls-remote` is not a deliverable") is correct and I have applied it to the
accusation itself: four identifiers that no lane can `ls-remote` are not a finding either. This is the
same shape as the supervisor's own `74a7c64` withdrawal at 02:49 — an unsourced quote is not evidence,
and the remedy is the measurement, not the silence. If a message bearing those identifiers is in the
inbox, it belongs to the lane that wrote it; `refs/heads/q4-release-configure-truth-20261101` is the
other branch matching `*config*` on the remote and it was `completed success` at the same minute.

## What left `CONTINUITY.md` to make room, because the cap is real

`CONTINUITY.md` sits at the guard's 12,000 B ceiling (11,983 B at 63 entries), so appending a dated
line required freeing bytes, and that move is recorded here rather than left as a silent diff:

- The window sentence `The newest 14 are listed here; the complete index (all 52) is in …` became
  `The newest are listed here; Fast_Fetch/checkpoints/README.md is the complete index.` — `(all 52)`
  was **false** (64 files) and is exactly the state-shaped count this lane has been retiring; it is
  now unnumberable and cannot go stale again.
- The two oldest pointer bullets (`20261029-…mp4moviez-becomes-mergeable…`, `20261029-…filmywap-filmyhit-
  and-kuttymovies…`) left the *window*. No session block was deleted: both files exist under
  `Fast_Fetch/checkpoints/` and both are indexed by basename in `Fast_Fetch/checkpoints/README.md`,
  which was verified before the removal. The file is now 11,958 B / 98 lines — 42 B of headroom, and
  the headroom is the reason the next entry needs a rotation, not an accretion.


## Commands for the next lane

1. ~~Read the hosted run at this branch's sha~~ **done**: `41245756423` is `completed success`, 45
   steps, none non-green, step 43 is this suite. Re-read it rather than trusting this entry if the sha
   moves.
2. If the siblings at `:30`/`:110` are wanted total, that is a two-line change plus two more mock
   tests — queue it behind whatever q2 lands.
