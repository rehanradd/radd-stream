# LANE BRIEF — qoder13 (fresh-session handoff, written at ~83 % ctx)

> Not `CONTINUITY.md` — qoder14 holds the pen tonight. This file is qoder13's own lane
> handoff, inside the lane worktree `/tmp/lane_phase1`, branch `feat/phase1-resolved-cache`.
> Parked and idle after this commit. No behavioural work started.

## Where the branch is

Pushed shas, oldest first: `1cfea81` (twin-proof tests + exporter/runbook doc fixes) →
`b4ac244` (the earlier CONTINUITY brief) → `a943e15` (probe-coverage doc + test + CI steps)
→ **`e7ee990`** (vacuity audit of my two suites). Ancestry-verified fast-forwards each
time; no force-push, never `main`/`master`, never `git add -A`/`-u`/`-a`.

**Committed and on the remote (mine):** `Fast_Fetch/PROBE_COVERAGE.md`,
`Fast_Fetch/test_probe_coverage.py`, `Fast_Fetch/test_catalog_exporter.py`,
`Fast_Fetch/catalog_exporter.py`, `Fast_Fetch/PUBLISH_RUNBOOK.md`,
`Fast_Fetch/PIXELDRAIN_API.md`, `Fast_Fetch/test_transient_dead_heal.py`, and my steps in
`.github/workflows/backend-ci.yml`.

**Uncommitted in the worktree right now:** none of mine. `fast_fetch.py`,
`resolved_cache.py`, `test_resolved_cache.py` are **qoder12's** and were committed by them
independently; `CONTINUITY.md` is qoder14's.

## Verified (measured this session, production `mode=ro`)

* `4,073,865` sources over `800` services; emitter publishes `active_sources = 4,006,773`;
  rows with probe evidence = **10**. Coverage by evidence **0.00174 %**, by label
  **0.6515 %** (374× apart), overstatement **400,677×**. `is_resumable = 1` on **2** rows.
* `download_sources.status` is declared `TEXT DEFAULT 'active'` — read from `sqlite_master`.
* `792` of `800` services have never been probed; they hold `89.7 %` of rows.
* `cat_link_evidence` = **0 rows** on merged, on `preapply_20261029_1726.db`, and in every
  staging DB. Evidence went 0 → 71 forward in time. **The merge dropped nothing.**
* Only `INSERT` into that journal is reachable from `link_state.main()` — a CLI no pipeline
  calls. `run_health_check` (`fast_fetch.py:4958`) does one `UPDATE download_sources`, no append.
* Suites at `e7ee990`: `test_catalog_exporter.py` 21 OK / 2.057 s, `test_probe_coverage.py`
  13 OK / 0.751 s, `test_transient_dead_heal.py` 5 OK, `test_ci_manifest.py` 9 OK.
* Six mutants killed on assertions, two of them empty-the-collection (`PROBE_COVERAGE.md` §13).

## Assumed, not mine — do not quote as measurement

* Trunk's `10,816 / 3,490 / 12` figures in `backfill_adult_key.py` (transcribed from
  `/tmp/crown_trunk`, never re-derived) and the `394 keys / 407 twins` crown numbers.
* That the `www72`…`www97` singletons come from first-hostname-label importers — inferred
  from the shape, not traced to a line.
* Which importer writes the label-only `dead` / `js_required` / `unknown` / `blocked` statuses.
* Whether any `sources`-table staging DB had evidence columns in an older schema revision.

## DEFECT REPORTED TO CROWN, deliberately NOT fixed by me

`Fast_Fetch/validate_catalog_full.py`, function `validate()` (def `:68`), section 8
(`:227`) — two checks whose condition is the literal `True`: **`:231`**
("measured evidence is present") and **`:235`** ("no journal row points at a missing
link"). `journalled` / `active` / `stale` are computed and interpolated into the *detail
string only*. The file is not in tonight's ownership table; git says both commits that
created it are `radddao-oracle` (`bd8891e`, `7e2be42` — "fold probe evidence onto projected
links"). Full write-up was delivered to the Crown in-session; no edit made.

## Exact next command

```bash
cd /tmp/lane_phase1
cat /proc/loadavg                       # do not start above ~5
git log --oneline -1                    # expect e7ee990 or a descendant
git fetch https://github.com/rehanradd/radd-stream.git feat/phase1-resolved-cache
git merge-base --is-ancestor HEAD FETCH_HEAD || echo "remote moved; rebase-free: report, do not force"
timeout 300 python3 -S Fast_Fetch/test_probe_coverage.py      # 13 OK
timeout 300 python3 -S Fast_Fetch/test_catalog_exporter.py    # 21 OK
```

## Held for the Crown, in priority order

1. **All-clear re-run** of `test_vidout` / `test_catalog_v2` / `test_api_v2` — their
   reported errors are suspected disk-full artifacts, never confirmed. One suite at a time.
2. `validate_catalog_full.py:231/:235` — needs a real condition; ask before assigning.
3. The `unprobed`-scope question: `link_state` sets `unprobed` only on the no-unpacker branch
   (`fast_fetch.py:5559-5563`), so transport resets reach `fail_count` — should they?
4. Whether the same-key twin `EXISTS` in `catalog_exporter` should stay after
   `backfill_adult_key.py` actually runs on the deploying DB (cross-key class is still open).
5. Never-yet-measured, needs one full pass: per-service `http_status` cross-tab, and the
   cost of the §6 coverage query **with** the adult-clause join.

## Load discipline for the next session

`/api/v1/stats` samples tonight: 8.70 s (baseline, before I read anything) → 0.28 →
**10.88 s after my 75.5 s pass** → 0.18 → and a `preapply` check that cost **61.7 s for one
count with two more full aggregates behind it** on a 6.4 GB file. Load climbed 3.9 → 6.4
during the session. **One sequential pass with Python-side grouping beats three SQL
aggregates over the same pages** — that is the lesson I paid for twice. `mode=ro` +
`PRAGMA query_only=ON` + `EXPLAIN QUERY PLAN` before every aggregate, always.

Scratch left behind by me: **none** (`/tmp/q13_mutants` removed). `/tmp/edge_snapshot.db`
(31 MB, Oct 27) is not mine — flagged, untouched.
