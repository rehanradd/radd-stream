# 2026-11-11 — Muse self-check [DIDYOUMEAN-RECALL]: relevance-ordered correction window

## What
`Fast_Fetch/did_you_mean.py::correct_token` ordered candidates `ORDER BY
p.id DESC LIMIT 200` — newest-first. A typo sharing grams with thousands
of newer titles never reached an old title: "avengrs" / "avengerss" got
no correction on the live catalog (157,748 posts), while the same code
passed its unit tests on a 5-row fixture.

## Fix
- Candidates now order by gram-match count DESC, `p.id` DESC within a
  tie, and the window widened 200 → 1000 (the LIKE scan already reads
  the table; the limit only bounds rows fetched).
- Exact-word check now runs over the whole window first, so a newer
  misspelling ("batmann") can never outrank the exact title word
  ("batman").
- Regression tests: old title corrects despite 250 newer crowd rows
  sharing one gram, at `limit=200` (the window truncates there, so only
  the ordering can save it); exact word wins over a newer misspelling.
  Both new tests fail on the old code (2 failures), pass on the new.

## The trap found while verifying
The first relevance-ordering version joined the score terms without
parentheses: in SQLite `+` binds tighter than `LIKE`, so
`a LIKE ? + b LIKE ?` parses as a chained comparison, not a sum of 0/1
matches — the score was meaningless and the ordering fell back to
recency. The unit tests still passed because the fixture never
truncates the window. Caught by probing the live catalog read-only
("incepton" stayed None while Inception rows scored 4 in a literal
query), then a minimal repro (a 6-term score on one known row returned
0). Terms are now parenthesised, with a comment saying why, and the
test pins the truncating limit.

## Evidence
- `test_did_you_mean.py` 11/11, `test_search_forgiving.py` 11/11,
  `test_viewer_search_forgiving.py` 8/8, all solo the CI way.
- Live catalog, read-only probe (`mode=ro`, `/tmp/dym-verify` copy):
  avengrs → avengers, avengerss → avengers, titanicc → titanic,
  batmann → batman, incepton → inception.
- Branch `muse/didyoumean-recall-20261111`, pushed via the bundle
  route; landing through the gate is the parent's — self-check never
  deploys.

## Still open
- Prefetch sweep (12:31) still running at ~12:55, pool 70.
- Pool rows born stale ~59% (pre-existing phase-1 behaviour).
- Parent A1: staging DB unchanged since 12:24, no process — quiet.
