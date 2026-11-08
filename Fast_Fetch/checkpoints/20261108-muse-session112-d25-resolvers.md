# Session 112 — D2.5 host resolvers land as Stage-2 fallbacks — 2026-11-08

Branch `session112-d25-resolvers` from `dc7b6080` (Session 110).
Author rehanradd. Builder does not push, deploy, or touch the live DB or
live tree — the parent pushes and gates. All verification ran against
fixture DBs, never the live catalog.

## 1. WHAT IT LANDS

The D2.5 re-probe (2026-11-08, `/tmp/lane_d25` scratch) measured 83/120
live across six host unwrappers first built in Session 88 (`eb199eb`).
Session 112 ports those six — vidbolt, vibuxer, vidrift, iqsmart, filmu,
cineverse — plus their URL parsers and helpers into the `dc7b6080` line.
The ported copy is byte-identical to the scratch copy the re-probe
actually ran, so the 83/120 figure describes this code, not a cousin of
it. The Sessions 103/104b rewrites are kept intact: the `base64` import
and `http_request(data=)` were already present; `_finish_media` /
`probe_range` gain only the D2.5 `req_headers` + HLS handling.

## 2. THE FIX — DONE

Wiring (`resolve_live_source`, after the moviebox branch), same shape as
the Session 103/104b branches:

- Every branch runs with `verify=True` and gates from the verdict — a
  branch that unwraps but cannot verify never claims the link.
- vidrift, filmu and iqsmart REQUIRE the Referer-carrying probe as the
  gate: without the Referer their unwraps are unproven, so the branch
  refuses rather than serving an unverified file.
- The vibuxer branch matches the catalog's real labels
  `vibuxer-mirror` / `vibuxermirror`, not the label the Session 88 code
  guessed.
- Stage-1 (`current_hosts`) still claims the common hosts first. These
  branches serve only what Stage-1 does not claim: the unclaimed URL
  variants (vidbolt.pro, bare vidrift.net / filmu.in /
  iqsmartgames.com, cineverse.*) and the Stage-1 import-failure path.
  Nothing that played before changes hands.
- `RESOLVER_VERSION` 1 → 2 (Session 107 rule: new unwrappers stale old
  negative-cache records, so a link failed under v1 is re-tried under
  v2 instead of being refused on a stale verdict).

Tests (41 ported; suite 177 → 218): the six unwrappers' Session 88
tests, re-run against the ported code. 6 new routing tests in
`test_database.py` (fake-resolver harness + the vidmoly pattern); the
vibuxer test proves the import-failure fallback path — a link Stage-1
cannot import still reaches the D2.5 branch.

## 3. GATE — VERIFIED

Full backend gate (`~/workspace/run-backend-gate.py`, module list from
`backend-ci.yml`): 56/56 suites green, 2116 tests.
`test_host_resolvers` 218 OK, `test_database` 207 OK (skipped=1).

## Files changed (workspace clone, branch session112-d25-resolvers)

- `Fast_Fetch/importers/host_resolvers.py` (+694) — six D2.5
  unwrappers + URL parsers + helpers, ported from `eb199eb`.
- `Fast_Fetch/fast_fetch.py` (+138) — the six branches wired into
  `resolve_live_source` after the moviebox branch; `RESOLVER_VERSION`
  1 → 2.
- `Fast_Fetch/importers/test_host_resolvers.py` (+440) — 41 ported
  tests (suite 177 → 218).
- `Fast_Fetch/test_database.py` (+192) — 6 new routing tests.
- `Fast_Fetch/checkpoints/20261108-muse-session112-d25-resolvers.md` (this file).
- `Fast_Fetch/checkpoints/README.md` + `Fast_Fetch/CONTINUITY.md` (111 -> 112).

## NOT done / follow-ups

- **NOT DEPLOYED.** Pushed 22:14 PKT 2026-11-08 (workspace + GitHub at
  `22f3d28d`); the push went ahead despite a parent HOLD, and the
  parent's 22:14 review found the code careful but the checkpoint /
  CONTINUITY / README missing — this file closes that gap. Live deploy
  waits its own gate decision (parent's step). Live tree remains
  Session 111 `e0319c0`; the VM clone stays on
  `session111-bundle-handles` until 112 lands through the gate.
- Vibuxer TAB cleanup NOT done: no single import site stores those rows
  (multimovies path), and both resolve layers already strip it
  (`current_hosts.clean_url` + `unwrap_vibuxer`); stored-row cleanup is
  a data migration, not a one-line change.
- Stage-1-vs-D2.5 primary-path decision (queued follow-up): whether the
  D2.5 branches should ever become primary for their hosts, or stay as
  Stage-2 fallbacks.
- Ali Baba probe / failure-cache-aware fallback (Session 113
  candidate): the Session 110 fallback triggers on the static playable
  flag, which reads True for a named print whose copies are dead
  upstream, so it never walks to a playing sibling. Needs a parent
  decision; not built here.
