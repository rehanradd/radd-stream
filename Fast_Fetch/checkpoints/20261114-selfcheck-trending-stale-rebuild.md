# Session 2026-11-14 — self-check `[TRENDING-STALE-REBUILD]`: the trending 503 flake gets stale-while-revalidate

## What
`/api/v1/trending` (and `sort=trending` on `/api/v1/posts`) 503'd once per
120 s TTL — and once per merge, which bumps the DB fingerprint — because a
cache miss rebuilt the order synchronously on the request thread: one
GROUP BY over the whole catalog, ~10 s cold, against the 10 s nginx read
timeout. Mechanism characterized from code on the 10:20 self-check run;
this session builds the fix.

## Fix (`Fast_Fetch/viewer.py`, branch `trending-stale-rebuild-20261114`)
- `_trending_cache_get` no longer deletes an expired entry: it is the
  stale fallback.
- New `_trending_cache_stale_for(content_type)`: the newest cached order
  for the content type under any fingerprint, scoped to this database
  file (the fingerprint's first element is the catalog path — an entry
  built for another file is never served as this file's order).
- New `_trending_rebuild` / `_trending_rebuild_async`: the build runs in
  a daemon thread on its own connection (the request's connection
  carries the 10 s progress deadline, and this build is the query that
  deadline exists to kill), single-flight per cache key. A rebuild
  failure is not a client error: the stale order stays served and the
  next hit re-triggers.
- `_trending_cached_page`: on a miss with a stale order available, serve
  it at once and rebuild in the background. Only a true cold start (no
  entry for the content type at all) still builds synchronously — once
  per process start, not per TTL. The per-request adult/hide re-check
  still applies to the stale order, so a flag flip hides the work on
  the very next hit either way.

## Tests (`Fast_Fetch/test_home_rails.py`, +2)
- `test_expired_cache_serves_stale_then_rebuilds` (TTL path, fingerprint
  frozen): the expiry hit answers the old order, a later hit answers
  the new top row.
- `test_fingerprint_change_serves_stale_then_rebuilds` (merge path):
  same, across a fingerprint bump.
- Both mocks use path-shaped fingerprints `(str(db_path), …)` mirroring
  the real `_trending_db_fingerprint` shape — required, because the
  stale scan is scoped to the catalog path.

## Test-caught bug, fixed in the same session
The first cut of `_trending_cache_stale_for` scanned every entry
regardless of database file. In one process that serves several
throwaway DBs (the test suite), a miss served another DB's order:
`test_trending_route` lost its top row, `test_trending_shows_one_salaar`
saw 0 rows, `test_envelope_is_a_posts_page` read a foreign total. The
path scoping above is the fix; all three pass now. In production the
service holds one DB_PATH for its whole life, so this could not bite
there — but the scoping is the correct invariant regardless.

## Verdicts (local, this box)
- `test_home_rails.py`: 47 OK (45 baseline + 2 new)
- `test_database.py`: 236 OK (skipped=1)
- `test_posts_query_plan.py`: 8 OK
- `test_catalog_api.py`: 135 OK
- `test_redact.py`: 96 OK (`python3 -S -m unittest test_redact` from
  `Fast_Fetch/`; from the repo root it errors on module lookup — run it
  from `Fast_Fetch/`)

## Not done here
- NOT live: the live tree is still `bcacd5ea` and the service still runs
  it. Deploy goes through the gate only (backup + live-tree ff +
  restart + live proofs) — the supervisor's call, never a self-check
  deploy.
- `CONTINUITY.md` could not take a line for this session: it sits at
  11,997 / 12,000 bytes, so any added line breaks
  `test_docs_invariants.py`. The session is indexed in
  `checkpoints/README.md` (newest first, the complete index) and the
  archive count there was bumped 143 → 144. A future lane that needs
  the CONTINUITY.md newest-list to grow must rotate lines out first,
  not append past the budget.
- The gate deploy of `c8b61fec` (warm-on-tap) is still pending ahead of
  this branch; this branch builds on `c8b61fec`.
- CI verdict on the branch is pending at push time.
