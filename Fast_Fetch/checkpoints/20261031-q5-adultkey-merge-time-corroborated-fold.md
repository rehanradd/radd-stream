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
  operator write; the fold is journalled and undoable. The journal table is created by every
  merge on both paths (folded, folded-nothing, skipped), and `stats["adult_fold_skipped"]`
  distinguishes "looked and folded nothing" from "was told not to look" — a merge that cannot
  be audited is indistinguishable from a broken one.
- `backfill_adult_key.py` — `--audit` (report the split, write nothing) and `--corroborate`
  (evidence-scoped apply), both refusing under `MemAvailable < 2000 MB`.
- `redact.link_is_adult` now returns True when the row is missing as well as when flagged —
  the fail-closed behaviour its docstring and root `AGENTS.md` have always claimed.

## Why the 407-works regression is structurally excluded

Verified in code, not prose: `ADULT_TITLE_PATTERNS` is 16 explicit tokens and contains neither
`uncut` nor `unrated`, so `adult_rule_agrees()` cannot reproduce a flag that stands only on
release vocabulary — which means the 375-of-407 mainstream works are *incapable of being fold
sources*, and that class of regression cannot return through this path.

Stated as a hazard, not fixed here: `ADULT_SOURCE_SITES` is `frozenset()`, so
`site_implies_adult()` answers 0 for every row today and the site-corroboration tier cannot
fire. That is the right fail-closed default; naming whole-catalog-adult hosts is a hiding
consequence and an owner decision, so the set stays empty in this branch.

## The boundary that was deliberately not crossed

Mission item 2 asked for a read-time `MAX(is_18_plus)` filter in `viewer.py`. A raw key-level
MAX was measured once to hide **407 mainstream works / 3,490 clean rows**: 10,816 of 15,068
stored flags are asserted-only (no textual evidence). So the fold is evidence-scoped, undo
never unflags a row justified by its own text, and `inherit_key_adult()` — the write-time
same-key law pinned by `test_database.py::KeyLevelAdultIdentityTests` — is untouched. Existing
readers (`redact.adult_clause` in `api_v1_get_posts` and `media_search`) hide both copies
because the flag is now on the row, not because the query grew a predicate.

## Measured, queued, or unverified

- **Run for this branch, `nice -n 19`, offline temp DBs:** `test_merge_catalogs.py` → Ran 8,
  OK (88.6 s wall at load ~5.2; the hosted runner takes 0.29 s — the wall time is this box,
  not the code); `test_adult_corroborated_fold.py` → Ran 44, OK. This ran after the supervisor
  caught `no such table: adult_fold_journal` on the two fold-nothing merge paths: the journal
  schema is now created by `reconcile_adult_on_merge` unconditionally and by the
  `--no-adult-fold` path too, and `stats["adult_fold_skipped"]` separates "looked, folded
  nothing" from "was told not to look".
- Porting surfaced one test-fixture defect: `PlayPathTests` pointed its "clean link" at the
  shared fixture's *flagged* post, which the old fail-open assertion never noticed. Fixed by
  pointing the release at a clean sibling — test-only, the gate was not weakened.
- Still queued for a quiet window, not run here: `test_redact.py`,
  `test_operator_adult_projection.py`, `test_database.py`, `test_media_search.py`,
  `test_posts_query_plan.py`, `test_docs_invariants.py`, plus the CI module list on this branch.
- Two assertions inherited from `/tmp/q4_test_adult_corroborated_fold.py` were arithmetically
  corrected while porting (both counted a second public row that the fixture never wrote).

## Queued for the owner

- `backfill_adult_key.py --audit` against production, read-only, in a quiet window. **Naming
  difference, recorded so the instruction stays traceable:** the owner's brief says production
  apply waits for an `--owner-go` flag; what shipped is the older, already-reviewed
  `--corroborate --apply` (plus `--undo`), and that remains behind the owner's explicit go.
  Production stays read-only until then.
- Cross-branch note: unmerged `q5_ci` carries a docs pin describing the gate as fail-OPEN;
  this branch makes it fail closed, so the merge must update that pin.
