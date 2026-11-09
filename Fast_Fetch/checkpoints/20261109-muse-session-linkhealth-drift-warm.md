# Phase E item 4 — link-health wiring + coin drift-guard test + pre-warming (2026-11-09)

Builder session, parent = main chat. Branch `session-linkhealth-drift-warm`,
base main `32f2c19`. No merge, no live writes: the sweep runner is an
operator CLI, the panel change is read-only, the warm change is a tick
limit. Gate: 66 modules (was 65).

## What changed

`Fast_Fetch/link_sweep.py` (new, +~700 lines) — the bounded link-health
sample `docs/LINK_HEALTH_SWEEP.md` §8 item 2 lists as unbuilt. `plan | run |
status | merge`, `--target` required (catalog), `--staging` defaults to
`/tmp/link_sweep.db`:

- Sample: stratified by registered host of `cat_links.url`
  (`link_health._host_of`), proportional allocation by largest remainder,
  reservoir draw per host (seedable). Default 1,000 links buys ±3.1 % at
  95 % (the budget test's numbers, re-implemented locally, not imported
  from the test module).
- Probing through `link_health.probe_many` (workers 8), so the per-host
  serialiser + 1.0–1.2 s spacing is enforced. A host answering 429 is
  parked for the rest of the run (its remaining links counted, never
  probed). Verdicts via `link_state.classify` (401/403/429 → expired, 404
  → dead, blocklisted/invalid_url → no verdict).
- Guards per batch of 500: 10,000-link run cap, load > 4.0 sleeps 60 s and
  re-checks (stops after 30 min), MemAvailable < 2500 MB or SwapFree <
  800 MB stops. A stopped run flushes and exits 0 with a note.
- Staging first (`link_sweep_sample` / `link_sweep_evidence` /
  `link_sweep_run`); a second run against the same file resumes the stored
  sample. `merge` applies staged evidence through
  `catalog_v2.apply_evidence` (replay is a no-op: dedup on
  link_id+probed_at) and stamps `link_sweep_last_run` into
  `cat_projection_meta` — the stored number the panel reads.
- `plan` and `run` open the catalog read-only; only `merge` writes it, as
  the operator's explicit action.

`Fast_Fetch/test_link_sweep.py` (new, 21 tests) — registered in
backend-ci.yml right after `test_link_sweep_budget.py`. Offline: fake
prober, temp DBs. Covers allocation sums, seed determinism, verdict
mapping, mixed outcomes, 429 parking (the park bites after the batch that
discovered the 429 — the three links in that batch were already knocked on
together), resume (second run probes nothing), load + memory guards, the
run cap, merge moving verdicts onto a real projection + the stamp +
replay idempotence, and the CLI plan/status paths.

`Fast_Fetch/admin_panel.py` — `screen_link_health` now reads the stamped
`links_by_state` / `link_coverage` from `cat_projection_meta` when present
(the dashboard's §6 rule: no coverage figure is ever computed by
scanning; the live GROUP BY stays only as the fallback for a stamp-less
catalog), plus `sweep` = the stamped `link_sweep_last_run` and `propagate`
= the latest `link_state_runs` row + the `serve` cursor — all stored
reads, no scans. The Link health card renders the sweep table and the
maintenance-propagate line. Six new tests in `test_admin_panel.py` (113
total): stamp wins, fallback without a stamp, stamped coverage, sweep
stamp surfaces (counts only — no URL/site/provenance), propagate row
surfaces, the sweep renders on the HTML page.

`Fast_Fetch/test_coins_engine.py` — new `DriftGuard` class (5 tests, 91
total). After every mutation the served API balance and
`engagement.coin_balance` are both compared against a `SUM(delta)`
recomputed by the test's own SQL: a refund clawback moves the balance by
exactly the refund; 20 server grants then a 21st raises
`VelocityLimitReached` and writes no row; a refund credit counts toward
velocity like a grant; a grant idempotency replay mints no second coin;
a spend replay deducts once.

`Fast_Fetch/maintenance.py` + `test_maintenance.py` — the first tick after
`serve` starts now warms the whole eager set (`FIRST_TICK_WARM_LIMIT =
200`, the scale plan's top-200 by rank_score, public links only,
lazy-first freshness preserved); later ticks top up 20. Implemented as a
pure `_first_tick_kwargs` helper the loop uses once (4 new tests, 16
total). A 200-link warm is minutes of network work in the daemon thread —
it delays only that tick's heal job, never a request.

## Verification

- `test_link_sweep.py` 21 OK; `test_admin_panel.py` 113 OK;
  `test_coins_engine.py` 91 OK; `test_maintenance.py` 16 OK;
  `test_docs_invariants.py` 22 OK (gate count 66).
- Local gate (`run-backend-gate.py`): see the branch report (parent runs
  CI by run id; a Fast_Fetch-only branch triggers Backend CI only).
- Not run live: no sweep has been run against the real catalog (that is an
  operator CLI on a snapshot copy, then a reviewed merge), and no warm of
  200 has run against the live service (it runs on the next serve start
  after this lands).

## Deliberately left out

- No per-host 384-link tables yet (the design's item 4): the sample
  supports the overall claim; naming a host needs 384 within that host,
  which is a `--limit` the operator chooses per host, not a default.
- No change to `api_v2` stats: the v2 stats endpoint still computes its
  own GROUP BYs; the panel is the operator surface this item wires.
- No runtime drift guard in `engagement.py`: the balance is already
  derived by construction (`SUM(delta)`), so the guard is a test that
  fails if any path ever serves a different number — not a second stored
  balance that could itself drift.
- `WARM_LIMIT_PER_TICK` stays 20: the eager fill is a first-tick event,
  not a per-tick cost.
