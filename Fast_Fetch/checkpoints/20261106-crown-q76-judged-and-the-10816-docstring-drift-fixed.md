# 2026-11-06 03:2x PKT — crown lane `[Q76-VERIFY]`: order #76 judged by artefact re-tabulation, and the
`10,816` docstring drift fixed in prose

Judgement in `/tmp/crown_orders/CROWN_VERIFY_76.md`. q12's census of **why 15,068 rows carry
`is_18_plus = 1`** reproduced under crown's own arithmetic, with no bulk catalog pass (NOTICE 79 was in
force): class counts 4,252 / 8,882 / 1,934 / 0 and their sums; the §2.1 audit cross-tab cell by cell
(8,782 / 4,251 / 2,035 / 0); the stale sub-buckets 4,366 / 4,251 / 165 / 100; the freeable cut
(4,247 whole-ledger, 4,043 joined to a work, **100 % `derive-stale`**, evidence `uncut` 3,733 +
`unrated` 514); the fold∩audit collision (**0 rows, 263 keys**, 264 hide vs 263 free, exactly one flagged
row per colliding key, and the −78 % sequencing asymmetry 338 → 74); the 1,190 residuals by sibling class
(812 / 328 / 50); and q12's self-correction of its own 3,931 up to 4,043 with the short-circuit cause.
Crown's independent denominator check: `select count(*), sum(id) from posts where is_18_plus=1` →
**15,068 / 1,100,579,566**, identical to the filing's content vector, with the `-wal` stamp unmoved at
01:30:49.

Two claims verified against code rather than data: `ADULT_TITLE_SUGGESTIONS` is referenced **0** times in
`audit_adult_flags.py` (so the shipped audit is structurally blind to the law's suggestion tier and its
error runs conservative), and `ADULT_SOURCE_SITES` is `frozenset()` at `fast_fetch.py:280` (so the site
tier cannot fire on any row today, which is why the 1,934 asserted rows have no "today's law would assert
this" reading). `original_title` is **not** a column of `posts` (25 columns), so the ingest expression's
second argument is `slug or url` in practice — as filed. `adult_key_fold_journal` → 0 in `sqlite_master`,
and 0 of the 338 agree-set ids carries a flag: **the fold has never run against this catalog.**

## What this file's commit changes

Both `fast_fetch.py` (`audit_flags`'s own docstring, ~line 966) and `backfill_adult_key.py` (~line 47)
quoted **"10,816 of 15,068 flags cannot be reproduced by `is_adult_title()`"** while the function they
document is the *wider* `adult_rule_agrees()`. Measured 2026-11-06 at `ba5f420`: the wider rule disowns
**10,651**, the ingest expression disowns **10,816**, and the 165 between them is exactly q12's
`column-order loss` class — evidence present in a derive-listed column that the `or` chain never reaches.
Neither number is wrong; each was being quoted with the other's function name. Both docstrings now state
both figures with their owner, in prose only — **no behaviour, no code path, no test expectation changed**.

`Ran 27 + 44 + 22 tests OK` (adult_fold_guard, adult_corroborated_fold, docs_invariants) and
`check_doc_citations.py` → **0 broken, 20 suspect** (all pre-existing, in `HANDOFF_apidocs.md`).

`CONTINUITY.md` itself was **not** touched, per FLEET NOTICE 80 §2: it sits at 11,998 of a 12,000-byte
ceiling, so the record lives here and the index count moves 75 → 76 in the same number of bytes.
