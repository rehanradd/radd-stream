# 2026-11-06 03:1x PKT — crown supervisor lane `[Q75-LAND]`: three producer characters, landed

Record written by crown for order `CROWN_ORDER_75_Q14_PRODUCER_FIXES.md` and filing
`Q14_RESULT_75_PRODUCER_FIXES.md`; judgement in `/tmp/crown_orders/CROWN_VERIFY_75.md`.

## What landed

Three producer defects q14 measured in order #72 and fixed in order #75, each with a test that was red
against the shipped code before the fix:

1. `Fast_Fetch/import_katmoviehd.py:961-963` — `_LEADING_DANGLE_RE` listed `and` three lines below a
   comment that says *"Deliberately \*not\* the/a/an/and: those open real titles"*. The word is deleted
   from the alternation. `And God Created Woman` stops becoming `God Created Woman`; `Andaz` is still
   safe because `\b` was already doing that work, and the list was **not** widened to articles.
2. `Fast_Fetch/import_hindilinks4u.py:328` — the punctuation class `[\(\[\]\{\}<>&]` had `\(` and no
   `\)`, which is why 201 hl4u rows still carry a `)` in `clean_title` after re-running the cleaner. One
   character added; it is a punctuation strip, **not** a bracket-group deletion, so `Dharma (The Chosen
   One)` keeps its words and `Space Jam (1996)` still yields year 1996.
3. `Fast_Fetch/import_katmoviehd.py:944` `_TITLE_NOISE_PATTERNS[9]` — a bare `Season` alternative ate
   the last word of real titles (`Mating Season` → `Mating`). Now `Season\s*[IVXLC]+\b` (the roman form
   the bare alternative was accidentally catching) and nothing else.

New module `Fast_Fetch/test_producer_cleaner_fixes.py` (18 tests, red-first: `FAILED (failures=10)`
against unfixed code) and one CI step registering it: 🧪 step count **47 → 48**.

## Crown's independent verification (not the lane's word)

* `git archive 55301dd | tar -x` into a fresh tree, copy the test module in, run: **10 failures, the same
  assertion text as the filing**. Apply `git diff` from the lane's worktree: `APPLIES CLEAN`, then
  **18 OK**.
* The 13-row migration demand re-derived from stored rows by primary key, pristine producer vs patched:
  the 7 katmoviehd rows gain exactly the words filed (`And` ×2, `Season` ×5) and **0 rows lose a token**;
  the 6 hl4u rows move from a leading-underscore key (`_1992`) to a year-as-title key (`2024_1992`) — both
  junk, caused by the `:330-331` raw-title fallback that this order deliberately did not touch.
* **Crown was wrong once and the lane was right:** I first checked the closer re-key exception with the
  wrong string and concluded "0, not 1". Re-run with the fix's own transformation —
  `generate_canonical_key('WWE SummerSlam PPV (Night 02  3rd August 2025 ', 2025)` →
  `wwe-summerslam-ppv-night-02-3rd-august-2025_2025` — the exception is real: deleting a stray closer can
  re-open an earlier bracket group and stop the tokeniser swallowing the words inside it. **51 → 1 stands.**
* `test_import_katmoviehd.py::test_a_real_season_still_projects_as_a_series` red at pristine 55301dd in
  crown's own tree (`Ran 40 tests in 17.029s`, line 996, `0 != 1`) — so the red is **not** caused by this
  patch, and the defect it exposes (`merge_catalogs` re-keys `mobland_s1` to `mobland_2025`, dropping the
  importer's season suffix) is filed for a future order. That suite is in `test_docs_invariants.py::UNREGISTERED`,
  so the hosted gate cannot see it either way.
* Suites run in the landing tree before commit, all `ionice -c3 nice -n19`, one module per invocation:
  producer_cleaner_fixes 18 OK · docs_invariants 22 OK · katmoviehd 5 OK · katmoviehd_import 14 OK ·
  hindilinks4u 24 OK · hindilinks4u_retry 13 OK · adult_fold_guard 27 OK · key_refusal_guard 40 OK.

## Corrections to crown's own record, accepted from this filing

Class counts are predicates, not facts: leading-conjunction **10 → 4**, closer re-key **51 → 1**,
eaten-real-title-word **274/408 → 38,020** under a broad vocabulary (the stop-list was measuring `p`, `MB`,
`GB`, `Vegamovies`), and #72's **277** is unreproducible under any of five definitions. `CROWN_VERIFY_72`'s
"12 of 14 numbers reproduce exactly" is retired as a claim of truth: it was a claim of arithmetic.

## Limits

No production write, no `UPDATE`, no re-key, no `key_census.py --apply`, no tag, no restart, no deletion,
no `/opt/radd-stream` edit. The live edge stayed `bf9e565` and answers `200`; the owner's deploy choice
(A / B / C′) is still open. Catalog reads in this session were 13 primary-key lookups plus one
single-row read — NOTICE 79 (bulk-I/O halt) was in force for the rest of it, and load peaked at **11.16**
with seven `qodercli` processes on a one-core box, two of them accounts this fleet does not supervise.
