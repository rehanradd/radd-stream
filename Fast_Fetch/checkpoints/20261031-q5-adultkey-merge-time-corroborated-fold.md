# 2026-10-31 — q5 adult-key lane: the merge-time corroborated fold, and the gate that now fails closed

Branch `q5-adultkey-reconciliation` (worktree `/tmp/q5_adultkey`, from trunk `7bc47ba`).

## What was wrong

The adult law is per row (`posts.is_18_plus`), but media identity is per work (`canonical_key`).
An existing row keeps the key it was filed under, and staging vaults declare `canonical_key`
PRIMARY KEY/UNIQUE — so a twin cannot be born *inside* one staging DB, but a legacy slug-keyed
row in the unified ledger and an evidence-backed copy merged from a site do share a work under
two keys. The measured residual at the correct identity (2026-10-29): 2,600 keys carry both a
flagged and an unflagged row, 3,486 publicly served rows under them.

## What landed

- `fast_fetch.adult_rule_agrees(row)` — re-derives the flag from the row's own text via
  `is_adult_title(clean_title, title, slug, source_site=…)`. Evidence, not assertion.
- `fast_fetch.work_identity(row)` — `(clean_title-or-title.strip().lower(), year)`, same dual
  identity `ledger_canonical_key` files new rows under. Empty/non-digit identity → None.
- `fast_fetch.corroborated_adult_exposures(conn)` — finds unflagged rows reachable through a
  flagged sibling, first by `canonical_key`, then by `(clean_title, year)`; the second pass is
  what reaches the legacy slug-keyed residual. The degenerate `unknown`/empty key is refused.
  Each exposure carries its evidence string.
- `fast_fetch.apply_corroborated_adult_fold(conn, exposures)` — flips only rows that are not
  already flagged, journals every flip (`adult_fold_journal`), so it is reversible.
- `fast_fetch.undo_corroborated_adult_fold(conn)` — unflips only rows whose flag is not
  justified by their own text and has no non-journaled flagged sibling under the same key.
- `merge_catalogs.reconcile_adult_on_merge(conn, apply=True)` — the production consumer, run
  by `merge_site_db` after posts settle; `--no-adult-fold` skips it. Merge is already an
  operator write; the fold is journalled and undoable.
- `backfill_adult_key.py` — `--audit` (report the split, write nothing) and `--corroborate`
  (evidence-scoped apply), both refusing under `MemAvailable < 2000 MB`.
- `redact.link_is_adult` now returns True when the row is missing as well as when flagged —
  the fail-closed behaviour its docstring and root `AGENTS.md` have always claimed.

## The boundary that was deliberately not crossed

Mission item 2 asked for a read-time `MAX(is_18_plus)` filter in `viewer.py`. A raw key-level
MAX was measured once to hide **407 mainstream works / 3,490 clean rows**: 10,816 of 15,068
stored flags are asserted-only (no textual evidence). So the fold is evidence-scoped, undo
never unflags a row justified by its own text, and `inherit_key_adult()` — the write-time
same-key law pinned by `test_database.py::KeyLevelAdultIdentityTests` — is untouched. Existing
readers (`redact.adult_clause` in `api_v1_get_posts` and `media_search`) hide both copies
because the flag is now on the row, not because the query grew a predicate.

## Measured, queued, or unverified

- **Nothing was executed under the fleet hard freeze** (load 4.49 > 4 at commit time).
  Queued for a quiet window: `test_adult_corroborated_fold.py` (44 tests),
  `test_redact.py`, `test_merge_catalogs.py` (8), `test_operator_adult_projection.py`,
  `test_database.py`, `test_media_search.py`, `test_posts_query_plan.py`,
  `test_docs_invariants.py`, plus the CI module list on this branch.
- Only `ast.parse` syntax checks were run on `fast_fetch.py` and `merge_catalogs.py`.
- Two assertions inherited from `/tmp/q4_test_adult_corroborated_fold.py` were arithmetically
  corrected while porting (both counted a second public row that the fixture never wrote).

## Queued for the owner

- `backfill_adult_key.py --audit` against production, read-only, in a quiet window; then
  `--corroborate` only with `--owner-go`. Production stays read-only until then.
- Cross-branch note: unmerged `q5_ci` carries a docs pin describing the gate as fail-OPEN;
  this branch makes it fail closed, so the merge must update that pin.
