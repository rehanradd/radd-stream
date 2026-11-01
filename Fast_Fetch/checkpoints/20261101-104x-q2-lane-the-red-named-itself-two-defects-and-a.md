# [Q2-THE-RED-NAMED-ITSELF] 2026-11-01 10:4x — q2 lane, #18's suite green on `11395d0`

Tag: `[Q2-THE-RED-NAMED-ITSELF]`. Lane: q2 (`/tmp/q2_admin_auth`, branch `q2-census-pricing`).
Slice: task #18's guard suite, which had been red on the hosted runner for two pushes.
Nothing here is a production read; no service touched; no tag; no merge.

## What I came in believing, and what was false

I came in to fix a **version-dependent planner claim** — that `test_price_projection.py` was red
because the hosted runner words `EXPLAIN QUERY PLAN` differently than this box does. The channel
built below disproved that in one line: the runner reports `sqlite 3.45.1 | python 3.12.3`, the same
pair this box reports, and **26 of the suite's 28 assertions passed unchanged on the first hosted
execution of that file ever**. Zero planner-wording assertions moved. The two failures were ordinary
bugs, both of them mine, and one of them was in the tool rather than the test.

## The channel (this is the reusable part)

`/actions/runs/{id}/logs` answers **401** without a token, and the token-less lanes on this box have
no token; `GITHUB_TOKEN` reads 401 on `/user` and on the repo. But
`/repos/{o}/{r}/check-runs/{id}/annotations` answers **200 to anyone**, and the check-run id is
`jobs[*].id` from `/actions/runs/{id}/jobs`, also 200 unauthenticated. A `::error::` workflow command
printed by the step's *own process* on stdout becomes one of those annotations. So a suite can publish
its own diagnosis:

    ::error::<up to 2500 chars, %-escaped (%25 / %0D / %0A), ≤10 annotations per check run>

`test_price_projection.py` now does this in its `__main__` block (exit codes unchanged: green 0, red 1;
the step's `run:` line is unchanged, so `test_docs_invariants.py`'s step↔run pairing is unaffected — it
was verified over the workflow with the suite's own regexes: 44 steps / 44 runs, no duplicates, nothing
undeclared against the 48-item `UNREGISTERED` list and 92 on-disk modules).

**Two rules for anyone copying this:** print three traceback lines per failure, not one — `assertEqual`
puts the value it *got* above the value it wanted, and with one line the second failure below arrived as
the useless `+ does not fit`. And keep it to one annotation: the runner caps a check run at ten and
drops the rest silently, so a per-failure annotation plan loses the diagnosis exactly when there are
many failures.

## Defect 1 — the assertion that could never pass

    AssertionError: 'no Layer-0 table' not found in 'no layer-0 table(s): posts, post_sources, releases, download_sources'

`test_a_database_without_the_layer0_tables_is_refused` normalised the exception message with `.lower()`
and then searched it for a **mixed-case** needle. The refusal was correct on every run; the check was
unsatisfiable. Fixed by lower-casing the needle (`11395d0`). Same bug family as #46's `NameError`: a
string compared against a transformed copy of itself, which no amount of re-deriving the *semantics*
will surface, because the semantics are fine.

## Defect 2 — a real hole in `price_projection.py`, found by its own test

`test_an_index_less_ledger_is_a_scan_on_the_hot_path_and_does_not_fit` wanted `does not fit` and got
`indeterminate`. The test was right and the tool was wrong: the hot-scan block demoted only a `fits`
the cost model had produced,

    if result["verdict"] == "fits": result["verdict"] = "does not fit"   # was

so **the one ledger shape that guarantees the rebuild will not finish** — `SCAN releases` once per outer
row, 146,176 times — reported "unknown" whenever the operator had not typed in row counts, which is the
common invocation because counts are a frozen content read. `price()` now refuses on the plan alone and
a new case (`test_a_hot_scan_refuses_the_rebuild_on_its_plan_alone`) pins the no-counts call with
`retention is None` next to the verdict, so nobody can read that `does not fit` as a memory claim. The
module docstring and the CI step's comment moved with it: "a run without counts exits 4 rather than
guessing" now names its exception.

## State of #18 after this slice

`test_price_projection.py` is green on the hosted runner: run **41278118306**, job `python3 -S offline
suites`, `completed success`, 29 tests, step #47. The tool's verdicts are now three honest classes —
`fits` / `does not fit` (from memory *or* from plan shape) / `indeterminate` (exit 4).

**#18 is still not run.** What it needs, in order: a decision on staging the head pass (the rebuild
retains every post row, ≈292 MB at the code-recorded 146,176 posts × 1,975 B — a quotation, not a
measurement) or a real `--mean-row-bytes` from a window that can read the ledger, and a supervisor
window that is not frozen. `--plan-only` is free and legal today and answers the index question against
any ledger. #37's three-class sidecar ruling is still outstanding (14 of 19 vaults are barred by
0-byte `-wal`/`-shm` debris; taken literally, the 09:07 abort rule makes #37 unrunnable forever).

## Do not re-derive

- The runner and this box agree on SQLite (3.45.1) and Python (3.12.3). Planner-wording divergence is
  **not** a live theory here; measured on `11395d0`'s run.
- `/actions/runs/{id}/jobs` is readable unauthenticated and `jobs[*].id` *is* the check-run id; the log
  endpoint is not. Both facts are measured, not assumed.
- `project_readonly` → `catalog_v2` imports pull neither `config` nor `fast_fetch` (checked with
  `'config' in sys.modules`), so `test_price_projection.py`'s `import project_readonly` inside a test is
  safe on a runner that has no `/home/ubuntu`.
- The exact fixture plans on 3.45.1, in case someone wants them without rebuilding the ledger: head pass
  `SCAN p`; `sources per post` / `releases per post` / `downloads per release` = `SEARCH … USING INDEX
  idx_post_sources_post (post_id=?)` / `idx_releases_post (post_id=?)` / `idx_sources_rel (release_id=?)`;
  strip those three indexes and each becomes a bare `SCAN <table>`; `ORDER BY quality` instead of
  `ORDER BY id` adds `USE TEMP B-TREE FOR ORDER BY` — the positive control for the rowid-order claim.
