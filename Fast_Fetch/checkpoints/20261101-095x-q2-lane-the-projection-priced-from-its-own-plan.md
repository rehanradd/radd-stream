# 2026-11-01 09:5x — q2 lane `[Q2-PROJECTION-PRICED-FROM-ITS-PLAN]`

Task: #18, the queued v2 projection rebuild — "safe to type, **not** sized". This slice makes it
sized-with-stated-assumptions, and does it without one content read.

## The finding that changes what #18 is waiting on

The rebuild's cost is **resident memory**, not CPU-seconds. `catalog_v2.project:918` runs

    SELECT p.id AS post_id, p.*  FROM posts p  ORDER BY p.id

and `_WorkAccumulator.absorb` (`catalog_v2.py:726`) appends **every row it reads** to
`self.posts`, which lives in `works` for the whole run. So the peak is the ledger's text volume
(whole `synopsis` and `backdrop_urls` fields included), retained while 146k-plus works are folded,
sorted, and written. A window sized in CPU-minutes — the way #37 is sized — would have admitted this
job and still OOM-killed it. That is why nobody had sized it: the question was the wrong shape.

**Calibrated on a synthetic ledger, not on production** (3,000 rows in the engine's own `posts` shape,
1,800 B synopsis, run through that exact retention pattern): peak RSS 17 → 23 MB while 5,925,000 B of
row text was retained. So **resident ≈ retained text, factor 1.01, ±10%** — `ru_maxrss` is a peak with
1 MB granularity on a 17 MB base, and the tool publishes the raw numbers and lets
`test_price_projection.py` recompute the factor against a tolerance rather than trusting either.
At the code-recorded 146,176 posts and 1,975 B/row that is **≈ 292 MB**; at a 4 KB mean row it is
≈ 590 MB. Both are *estimates from a quotation* — `RECORDED["posts"]` is quoted from
`catalog_v2.py:968`, and the tool says so in its own output, because a fresh count is a content read.

## The plan, taken from SQLite rather than from the clock

`EXPLAIN QUERY PLAN` describes a statement without executing it, which is what makes a cost answer
legal under this freeze. On an engine-shaped ledger (`fast_fetch.init_db`'s four Layer-0 tables and
its three join indexes) the planner says:

    head pass             SCAN p
    sources per post      SEARCH post_sources USING INDEX idx_post_sources_post (post_id=?)
    releases per post     SEARCH releases       USING INDEX idx_releases_post (post_id=?)
    downloads per release SEARCH download_sources USING INDEX idx_sources_rel (release_id=?)

Strip those three indexes and the same four statements become `SCAN post_sources` / `SCAN releases` /
`SCAN download_sources` — i.e. **one table scan per outer row, 146k times**, and `price_projection.py`
turns that into `does not fit` on the plan alone. That is the drift check #18 actually needs before it
runs against anything: it is not the ledger's size that decides whether the rebuild is feasible, it is
whether three named indexes exist over `post_id` / `post_id` / `release_id`.

**A claim of mine the planner falsified before the sha:** I had written into the suite that
`WHERE post_id = ? ORDER BY id` sorts once per post (146,176 sorts, priced as a cost). It does not:
the `post_id` index emits (post_id, rowid) order and a rowid-table scan visits rows in rowid order, so
`ORDER BY id` is free — measured on both shapes, `USE TEMP B-TREE FOR ORDER BY` appears only when the
sort key is a text column. The suite now asserts the *absence* of the sort, with a positive control
(`ORDER BY quality` → `SEARCH+sort`) so "no sort" is a checked fact rather than an unchecked string.

## Two defects the empirical run caught that a re-derivation would not have

- `EXPLAIN QUERY PLAN SELECT … WHERE post_id = ?` still needs the placeholder **bound**:
  `sqlite3.ProgrammingError: Incorrect number of bindings`. `plan()` now supplies NULLs — nothing
  executes, so a NULL never reaches a row.
- `price()` reported `retains_rows` from `STATEMENTS` but did not carry the key into its own result
  rows, so the stale-model guard died on `KeyError` instead of guarding.

## The check I ran that proved nothing, named because it is the same trap

My first verification of the CI gate invariants read the workflow **without `re.MULTILINE`**, so both
regexes matched nothing, both lists came back empty, and the script cheerfully reported
`steps==runs: True` and every module on disk "undeclared". An empty list satisfies an equality
assertion. Caught only because I then printed the counts and saw 0. It is the vacuous-test failure mode
again, one layer up: I had built the thing meant to catch a wrong claim and let it assert over an
empty input. Any check that can pass by matching nothing must print how many things it matched.

## #18 status after this slice

Priced under stated assumptions, **still not run**. `price_projection.py <ledger> --plan-only` is the
free half (schema only, LIGHT per the 09:07 ruling) and answers the index question for any ledger it
is pointed at. The remaining unknown is `--mean-row-bytes` — the real ledger's mean retained row text —
which needs either a window to count or the structural fix: stage the head pass so `project()` folds
works without keeping every page of every work alive. That refactor, not a quieter box, is what would
make #18 admissible.

**Fresh host read, not a DB read:** `MemAvailable = 1,933 MB` at 09:5x — 433 MB above the 1,500 MB
floor, so nothing heavy was admissible while this was being written, and the ~292 MB estimate above is
*not* comfortable against it.

## Do not re-derive

- The head pass retaining every row is the finding; a CPU-minute window plan for #18 is a category
  error. Read `catalog_v2.py:726` before re-planning.
- `ORDER BY id` costs no sort here (rowid). Do not re-add it as a cost.
- Counts are inputs to `price_projection.py`; a `--posts` value that was not measured by someone is a
  fabrication, and the exit code for "no counts typed in" is 4 on purpose.
- The 3 expected index names are `fast_fetch.py:986/:1012/:1120`. If a ledger lacks them the answer is
  "does not fit", not "retry later".
