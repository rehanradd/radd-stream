# Session 2026-11-10 — Phase 7 backend half (branch `muse/phase7-v2-migration-20261110`, base main @ 9bb3014)

## What

The backend half of the Phase 7 build (audit
`~/workspace/goals/radd-stream-on-oracle-vm/hidden_files/phase7-audit-20261110.md`).
The app half is logged in `App/docs/SESSION_HISTORY.md` (Session 127).

- `catalog_api.py`: `_work_ref_for()` mints `work_ref` on `_browse_item` and on the
  `work` object of `work_detail`, from `_PUBLIC_CONTEXT["secret"]`. When the key or the
  secret is missing the value is `None` — never a token minted with an empty secret
  (forgeable). `work_ref` is allow-listed for public payloads (`redact.py:814`).
  `_browse_item` always carries the key (value `None` when unconfigured); the
  `work_detail` work object does the same.
- `test_api_v2.py`: +1 test
  `test_browse_search_and_detail_carry_the_account_handle` — browse/search items
  carry a `work_ref` that unmints to their `cat_works.work_key` with the mount's
  secret; the detail work object carries one too; `assert_clean` on both; with no
  secret configured the handle is `None`, never forged.
- `test_catalog_api.py`: the exact-shape pin
  `test_browse_item_carries_exactly_the_documented_grid_shape` now lists `work_ref`
  in the pinned key set (the shape changed deliberately, not weakened) and asserts
  it is `None` in that fixture, which configures no secret.

## Why

The app migrates home/search/detail onto the v2 GET catalog routes, and the sync
account only accepts the minted `work_ref` (favorites, progress) — so a v2 row must
name its work the way v1 rows do. The `work_ref` is also the v1 bridge:
`GET /api/v1/posts?work_ref=…` turns a v2 work back into its v1 post, which is how a
v2 detail still reaches cast (the projection carries none) and the real post id.

## Checks

- `test_api_v2` 72 OK solo (71 + the new handle test); `test_catalog_api` 134 OK
  solo after the shape-pin update.
- Full gate `run-backend-gate.py` (62 modules in the script's list; CI runs 75
  `🧪` steps): 60 PASS, 2 FAIL on the first run — this shape pin and the
  `CONTINUITY.md` byte budget (`test_docs_invariants`: the file must stay ≤ 12,000
  bytes; the session entry moved here, into this checkpoint, to keep it under).
  After the fixes the two modules re-run green solo; the other 60 modules' results
  stand (the fixes touch only a test pin, two docstrings and docs).
- No importer touched; no staging/production DB written.

## Not done

- Push (parent's step after CI green on the branch, then parent lands into main).
- Gate deploy must still add the four nginx locations (`/api/v2/works`,
  `= /api/v2/browse`, `= /api/v2/search`, `/api/v2/resolve`) — see the
  `ORACLE_DEPLOYMENT.md` addendum in this branch. Until then the app falls back to
  v1 on every v2 call, so the migration ships safe but unverified end to end.
