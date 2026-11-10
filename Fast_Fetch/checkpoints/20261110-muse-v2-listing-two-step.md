# Session 2026-11-10 — v2 listing two-step (branch `muse/v2-listing-two-step-20261110`, base main @ c45bcaf)

## What

`/api/v2/browse` and `/api/v2/search` never answered (504 at the nginx 15s edge;
direct calls ran past 90s) while `/api/v2/works/1` was fast. The v1 title+720p
503 fix works (1.39s clean); this was the v2 listing engine.

- `catalog_api.py`: `_run_listing` is now a two-step, mirroring `viewer.py`'s
  503 fix — step 1 resolves the page's ids (plus sort keys) from `cat_works`
  alone, step 2 fetches the full rows (including the five correlated
  subqueries) for just those ids, imposing the step-1 page order in Python.
  The keyset clause and ORDER BY are byte-identical to the old shape, so
  cursors minted before this change keep paging the same rows.
- Covering index `idx_cat_links_work ON cat_links(work_id, playability, state)`:
  in the `catalog_v2.py` projection DDL (future rebuilds mint it) and in
  `fast_fetch._init_db`, guarded to run only when `cat_links` exists (a fresh
  ledger-only DB has no such table). The `_init_db` copy is the live-DB path:
  it builds on the first request after restart, like `idx_releases_post_quality`.
- `test_catalog_api.py`: +1 test
  `test_listing_counts_seek_the_work_id_index_not_a_link_scan` — the projection
  mints the index and the live_stream COUNT uses it as a covering index, no
  `SCAN la`.

## Why (diagnosis, measured on the live-copy `/home/ubuntu/v2listing-copy.db`, posts 157,748)

`EXPLAIN QUERY PLAN` on the old shape: `SCAN w` plus the five correlated
subqueries per matching work — the three `cat_links` COUNTs had no work_id
index, so each was a full scan (or a bad state-index walk) of the 3.8M-row
table. One work's live_stream COUNT measured **29.34s**; live_play **1.05s**.
A plain browse evaluates those for all ~121K visible works before LIMIT —
that is the hang, not the sort. Step 1 alone (ids only, serve pragmas) is
warm 0.1–0.7s across sorts; cold first-touch ~7s. Search is already FTS-first
(the planner probes `cat_works` by rowid from the FTS MATCH; the per-token
`radd_hay` LIKE is a post-filter on matched rows — search step-1 0.01s), so
no search restructuring was needed. The separate COUNT(*) total is 0.5s and
is kept (it is part of the response contract the tests pin).

## Before / after (live copy, serve pragmas, fixed module from `/tmp/v2fix`)

- `browse()` default: hang >90s (504) → **0.29s**, 24 items
- `search()` q=pushpa: hang → **0.03s**, 24 items
- `browse()` sort=title: hang → **0.92s**, 24 items
- 1-work live_stream COUNT: 29.34s → **0.058s**; live_play COUNT: 1.05s → **0.044s**
- Index build on the copy: **2m 2s** (one-time; the first request after restart
  pays it — the deploy warm-up must allow ~3 min).

## Checks

- `test_catalog_api` 135 OK solo (134 + the new index test);
  `test_api_v2` 72 OK solo; `test_catalog_v2` 103 OK solo;
  `test_database` 217 OK solo (skipped=1) — all the CI way (`python3 -S`).
- Full local gate NOT run: this box has 557 MB avail (guardrail floor 1500 MB);
  the CI backend run on the branch is the full gate (75 🧪 steps).
- No live DB touched (all timings on the scratch copy, made with
  `sqlite3 .backup` from the verified gate backup); no staging/production DB
  written. Scratch copy `/home/ubuntu/v2listing-copy.db` left on the VM.

## Not done / follow-ups

- Push + CI + land into main (parent's step), then gate deploy (live tree ff +
  restart; first request builds the index ~2 min — warm-up must wait for it).
- v1 loaded-tail (follow-up, NOT in this change): `viewer.py` step 1 still runs
  a quality EXISTS probe per post (leading-wildcard LIKE on `upper(quality)`,
  unusable by the covering index) plus an expression ORDER BY temp sort plus a
  separate COUNT(*) total; warm ~2s but tail >10s under load. Candidate
  directions: equality quality match, precomputed sort key. Needs a semantics
  decision; the clean median (1.39s) is fine.
- Precomputed / indexed sort keys for v2 trending (follow-up): step-1 warm is
  0.1–0.7s, so not needed to fix the hang; cold first-request ~7s is the only
  tail.
